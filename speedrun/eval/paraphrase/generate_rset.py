#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Reword each of the 30 R-set cards twice, and ledger each pair as it is made.

The manifest fixes what a rewording is (H4, selection rule step 3): *the same
fact, restated as an exam-style question, with no wording carried over from the
card beyond unavoidable technical terms.* Two things follow, and they are the
whole of this script:

**The model is the agent service's.** Same alias (`gpt-5`), same client, same
key discovery, same Responses API with a strict JSON schema, and the same habit
of recording the id the API *resolved* rather than the alias asked for. What is
not reused is `generators.PROMPT`: that prompt drafts a held-out item from
retrieved corpus passages and checks nothing about a card, because held-out
items are never derived from cards — that is ADR-0004, and reusing its prompt
here would be reusing the wrong tool. The Generation gate is likewise not in the
path: the gate proves a string is copied out of a source, and a rewording that
copies is the exact defect. Nothing here can enter Performance, so nothing here
needs the gate; the check that matters instead is `wording.py`.

**Overlap is enforced before an item ships, not audited after.** A draft whose
prompt reuses the card's phrasing is sent back once, with the offending run
quoted, and the second draft is used if it is clean. Both drafts stay in
`run_log.jsonl` either way. An item that is still not clean on the retry is
**still shipped and still ledgered** — dropping items after seeing them is how a
set gets chosen to flatter a number — and is named in `QUALITY.md` instead.

Ledger discipline, as H2 did it: each item is written to the set file, mirrored
to the path the frozen protocol names, and appended to `MANIFEST.md`'s H4 ledger
by `freeze.py --append-item` before the next card is started.

Usage (from the repo root):

    speedrun/agent/.venv/Scripts/python speedrun/eval/paraphrase/generate_rset.py --plan
    speedrun/agent/.venv/Scripts/python speedrun/eval/paraphrase/generate_rset.py --run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PARAPHRASE_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = PARAPHRASE_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
HOLDOUT_DIR = SPEEDRUN_DIR / "eval" / "holdout"

SELECTION_FILE = PARAPHRASE_DIR / "rset_selection.json"
CARDS_FILE = PARAPHRASE_DIR / "rset_cards.local.json"
#: The canonical R-set file this script owns.
RSET_FILE = PARAPHRASE_DIR / "h4_rset.jsonl"
#: The path the frozen protocol names for H4, kept byte-identical.
HOLDOUT_FILE = HOLDOUT_DIR / "h4_rset.jsonl"
RUN_LOG = PARAPHRASE_DIR / "run_log.jsonl"

sys.path.insert(0, str(AGENT_DIR))

from speedrun_agent import generators  # noqa: E402
from speedrun_agent.environment import key  # noqa: E402

sys.path.insert(0, str(PARAPHRASE_DIR))

from wording import overlap  # noqa: E402

REWORDINGS_PER_CARD = 2

PROMPT = """\
You are writing exam-style questions for an MCAT student, for AAMC content \
category {topic}.

Below is one flashcard from the student's own deck: the prompt they see, with \
the blank marked, and the answer that fills it.

Card prompt: {front}
Card answer: {answer}

Write {count} DIFFERENT questions that test exactly the same fact.

Rules, all of them binding:

1. Same fact. The correct answer to each of your questions must be the card's \
answer and nothing broader or narrower. If the card's answer is a list, your \
question must ask for the whole list.
2. Different words. Do not reuse the card's phrasing. No run of more than three \
consecutive words may appear in both your question and the card prompt. The \
only wording you may carry over is a technical term that has no ordinary \
synonym - a molecule, an enzyme, an anatomical structure, a named pathway.
3. Not the answer. Your question must not contain the answer, or a synonym of \
it, anywhere in its text.
4. Self-contained. A student must be able to answer it with no card and no \
passage in front of them. No "according to the card", no blanks, no cloze \
markers, no options list - it is a short-answer question.
5. Your two questions must differ from each other, not just from the card: \
approach the fact from different directions where the fact allows it.

Give the expected answer for each question in the student's own terms, short.

If the card is not a single answerable fact - it is an image with no readable \
text, or it is malformed - set "skip" to true and explain in "note".
{feedback}"""

RETRY_FEEDBACK = """
A previous draft was rejected for reusing the card's wording:
{problems}
Write new questions that do not reuse those runs of words.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rewordings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["prompt", "answer"],
                "additionalProperties": False,
            },
        },
        "skip": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["rewordings", "skip", "note"],
    "additionalProperties": False,
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------


class Rewriter:
    """The agent service's model, asked to reword rather than to draft."""

    def __init__(self, model: str = generators.OPENAI_MODEL, max_output_tokens: int = 8000) -> None:
        from openai import OpenAI  # noqa: PLC0415

        self._client = OpenAI(api_key=key("OPENAI_API_KEY"))
        self.model = model
        self._max_output_tokens = max_output_tokens

    def draft(self, prompt: str) -> tuple[dict[str, Any] | None, str, str]:
        """(parsed body, resolved model id, why it is empty if it is)."""
        response = self._client.responses.create(
            model=self.model,
            max_output_tokens=self._max_output_tokens,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "reworded_cards",
                    "schema": SCHEMA,
                    "strict": True,
                }
            },
        )
        if response.status != "completed" or not response.output_text:
            return None, getattr(response, "model", ""), f"status={response.status}"
        return json.loads(response.output_text), response.model, ""


def build_prompt(card: dict[str, Any], problems: list[str]) -> str:
    return PROMPT.format(
        topic=card["topic"],
        front=card["front"].replace("\n", " / "),
        answer=card["answer"],
        count=REWORDINGS_PER_CARD,
        feedback=RETRY_FEEDBACK.format(problems="\n".join(f"- {p}" for p in problems))
        if problems
        else "",
    )


def item_record(
    *,
    item_id: str,
    card: dict[str, Any],
    index: int,
    body: dict[str, str],
    model: str,
    prompt: str,
    attempt: int,
    checks: dict[str, object],
) -> dict[str, Any]:
    """One R-set row. The first five fields are what H4's item hash covers."""
    return {
        "id": item_id,
        "card_id": card["card_id"],
        "rewording_index": index,
        "prompt": body["prompt"].strip(),
        "answer": body["answer"].strip(),
        # --- not covered by the hash: provenance and bookkeeping ---
        "topic": card["topic"],
        "card_answer_sha256": sha256(card["answer"]),
        "card_front_sha256": sha256(card["front"]),
        "overlap": checks,
        "generator": "openai",
        "model": model,
        "draft_attempt": attempt,
        "prompt_sha256": sha256(prompt),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "live",
    }


def existing_ids() -> set[str]:
    if not RSET_FILE.exists():
        return set()
    return {
        json.loads(line)["id"]
        for line in RSET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def append_and_ledger(records: list[dict[str, Any]]) -> bool:
    """Write a card's pair, mirror it to the protocol's path, ledger it. In order."""
    with RSET_FILE.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    HOLDOUT_FILE.write_bytes(RSET_FILE.read_bytes())
    result = subprocess.run(
        [sys.executable, str(HOLDOUT_DIR / "freeze.py"), "--append-item", "--set", "H4"],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    return result.returncode == 0


def log(row: dict[str, Any]) -> None:
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------


def run(cards: list[dict[str, Any]], *, max_attempts: int) -> int:
    RSET_FILE.touch()
    HOLDOUT_FILE.write_bytes(RSET_FILE.read_bytes())
    done = existing_ids()
    rewriter = Rewriter()
    shipped = 0
    unclean = 0

    for position, card in enumerate(cards, 1):
        ids = [f"h4-{position:02d}-{k}" for k in range(1, REWORDINGS_PER_CARD + 1)]
        if all(i in done for i in ids):
            print(f"  {ids[0][:-2]}  already in the set, skipped")
            continue

        problems: list[str] = []
        chosen: list[dict[str, Any]] | None = None
        for attempt in range(1, max_attempts + 1):
            prompt = build_prompt(card, problems)
            started = time.time()
            try:
                body, model, why = rewriter.draft(prompt)
            except Exception as exc:  # noqa: BLE001 - one failed call is not the run
                log(
                    {
                        "card_id": card["card_id"],
                        "attempt": attempt,
                        "outcome": "error",
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"  card {position:02d}  error  {type(exc).__name__}: {exc}")
                break
            seconds = round(time.time() - started, 1)
            if body is None:
                log({"card_id": card["card_id"], "attempt": attempt, "outcome": "empty", "detail": why})
                print(f"  card {position:02d}  empty  {why}")
                continue
            if body.get("skip"):
                log(
                    {
                        "card_id": card["card_id"],
                        "attempt": attempt,
                        "outcome": "skipped_by_model",
                        "note": body.get("note", ""),
                    }
                )
                print(f"  card {position:02d}  model declined: {body.get('note', '')[:90]}")
                break

            drafts = body.get("rewordings", [])[:REWORDINGS_PER_CARD]
            if len(drafts) < REWORDINGS_PER_CARD:
                log(
                    {
                        "card_id": card["card_id"],
                        "attempt": attempt,
                        "outcome": "short",
                        "count": len(drafts),
                    }
                )
                print(f"  card {position:02d}  only {len(drafts)} rewording(s), retrying")
                continue

            checked = [
                (draft, overlap(card["front"], draft["prompt"], card["answer"])) for draft in drafts
            ]
            log(
                {
                    "card_id": card["card_id"],
                    "topic": card["topic"],
                    "attempt": attempt,
                    "outcome": "drafted",
                    "seconds": seconds,
                    "model": model,
                    "prompt_sha256": sha256(prompt),
                    "drafts": [
                        {"prompt": d["prompt"], "answer": d["answer"], **o.as_dict()}
                        for d, o in checked
                    ],
                }
            )
            problems = [f"'{o.shared_text}' ({o.why})" for _, o in checked if not o.clean]
            chosen = [
                item_record(
                    item_id=ids[k],
                    card=card,
                    index=k + 1,
                    body=draft,
                    model=model,
                    prompt=prompt,
                    attempt=attempt,
                    checks=check.as_dict(),
                )
                for k, (draft, check) in enumerate(checked)
            ]
            if not problems:
                break
            if attempt < max_attempts:
                print(f"  card {position:02d}  redraft: {problems[0][:100]}")

        if chosen is None:
            print(f"  card {position:02d}  NO ITEMS")
            continue
        ledgered = append_and_ledger(chosen)
        shipped += len(chosen)
        unclean += sum(1 for r in chosen if not r["overlap"]["clean"])
        for record in chosen:
            flag = "" if record["overlap"]["clean"] else "  [OVERLAP]"
            print(f"  {record['id']}  {record['prompt'][:88]}{flag}")
        if not ledgered:
            print("    !! ledger append failed - stop and fix before continuing")
            return 1

    print(f"\nshipped {shipped} rewording(s); {unclean} still over the overlap thresholds")
    print(f"run log: {RUN_LOG}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="call the model and write items")
    parser.add_argument("--plan", action="store_true", help="show the cards; no model call")
    parser.add_argument("--limit", type=int, default=0, help="first N cards only (debugging)")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args(argv)

    if not CARDS_FILE.exists():
        raise SystemExit(f"{CARDS_FILE} is missing — run select_rset.py --draw first")
    cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))["cards"]
    selection = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
    if [c["card_id"] for c in cards] != [c["card_id"] for c in selection["cards"]]:
        raise SystemExit("rset_cards.local.json does not match rset_selection.json")
    if args.limit:
        cards = cards[: args.limit]

    if args.plan or not args.run:
        for position, card in enumerate(cards, 1):
            print(f"{position:02d}  {card['topic']}  {card['front'][:100]!r} -> {card['answer']!r}")
        print(f"\n{len(cards)} cards x {REWORDINGS_PER_CARD} = {len(cards) * REWORDINGS_PER_CARD} rewordings")
        return 0
    return run(cards, max_attempts=args.max_attempts)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

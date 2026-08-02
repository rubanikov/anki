#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Put 94 generated cards into the three frozen buckets, without asking gpt-5.

**The one thing this file may not do.** The generator is `gpt-5`. Asking `gpt-5`
whether its own card is correct is banned by the ticket and by
`speedrun/agent/gate.py`'s own reasoning: a generator and a checker drawn from
the same weights share a blind spot, so the pair reads as two confirmations
while being one. The fake-organ result is what settles it. Grading therefore
happens in three layers, in a precedence fixed before any bucket was computed:

1. **Mechanical, against the source.** The answer is looked for verbatim
   (whitespace- and typography-folded) across the whole indexed book, using the
   corpus's own span matcher. **Not found anywhere → `wrong`**, with no model
   involved: an answer that is in no page is by the manifest's definition
   "something the source does not support".
2. **A blind model grade.** A *different* model (`o4-mini`, not the gpt-5 that
   drafted the cards) sees one card, its gold pair, and the source text around
   the cited span, under a prompt that shares no wording with the generation
   prompt. It never sees which arm the card came from, the cards are shuffled
   together under a fixed seed, and the ids it sees are opaque tokens.
3. **Mechanical teaching defects.** The failure modes `pset/QUALITY.md` found by
   hand — an option list naming the same thing twice, an answer that is a
   sentence rather than a term, a near-duplicate of another card in the batch —
   are detected by rule and put the card in `correct but bad teaching`, unless
   layer 1 or 2 already called it wrong.

Precedence: layer 1 wins over everything; layer 2's `wrong` wins over layer 3;
layer 3 wins over layer 2's `correct and useful`. A card the grader cannot place,
or whose response does not parse, goes to `correct but bad teaching` — the
conservative bucket the manifest chose in advance for exactly this case.

**This is model-assisted grading with a hand-checked sample. It is not human
grading throughout, and the artifact says so.** `--sample` prints a stratified
sample for a person to bucket by hand; `--report` prints the agreement rate
between those hand buckets and the automated ones. An agreement rate is the only
thing that makes layer 2 evidence rather than an assertion.

Usage (from the repo root, with the agent's own interpreter):

    ... speedrun/eval/aicheck/grade.py --mechanical      # no model call
    ... speedrun/eval/aicheck/grade.py --sample 30       # dump the hand-check sample
    ... speedrun/eval/aicheck/grade.py --grade           # the blind model pass
    ... speedrun/eval/aicheck/grade.py --report          # buckets, cutoff, agreement
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

AICHECK_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = AICHECK_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
HOLDOUT_DIR = SPEEDRUN_DIR / "eval" / "holdout"
INDEX = CORPUS_DIR / "out" / "index.sqlite3"
OUT_DIR = AICHECK_DIR / "out"

GOLD_FILE = HOLDOUT_DIR / "h3_gold.jsonl"
HANDCHECK = AICHECK_DIR / "handcheck.json"
#: A second hand read, of cards the prompt revision never looked at.
HANDCHECK2 = AICHECK_DIR / "handcheck_holdout.json"

#: Which grading prompt produced the buckets. **Version 1 is kept on disk, not
#: deleted**, because it is the evidence for the strongest claim in AICHECK.md:
#: a blind LLM judge agreed with a hand read only 43% of the time, and the two
#: reasons were both prompt defects rather than hard cases.
#:
#: v1 → v2 changed exactly two things:
#:   * v1 showed only ±700 characters around the cited span. Cards whose fact is
#:     stated elsewhere in the book were called `wrong` for being "not in the
#:     passage" — a truncated excerpt was doing the work of a source. v2 shows
#:     the retrieved passages the card was actually drafted from, and says in so
#:     many words that silence is not contradiction.
#:   * v1 asked for a bucket and got `correct_and_useful` 84 times out of 94,
#:     with "plausible distractors" as the reason for cards whose distractors
#:     were two names for one thing. v2 makes it enumerate the specific defects
#:     from `pset/QUALITY.md` before it picks, which is the standard fix for a
#:     judge that defaults to approval.
#:
#: The hand buckets were **not** touched between the two passes. That ordering
#: is the whole reason the agreement number means anything — and it also means
#: the v2 agreement rate on those same 30 cards is a fitted number, which is why
#: `--sample2` exists and why AICHECK.md reports a held-out rate as well.
PROMPT_VERSION = 2
GRADES = OUT_DIR / f"grades_v{PROMPT_VERSION}.jsonl"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(CORPUS_DIR))

import spans  # noqa: E402
from index import CorpusIndex  # noqa: E402
from speedrun_agent.environment import key  # noqa: E402

#: The grader. Deliberately not `gpt-5`, which drafted every card here, and not
#: a `gpt-5` snapshot under another alias. Same vendor — the only key on this
#: machine is an OpenAI one — which is a real limit on how independent the two
#: are, and AICHECK.md states it rather than implying a second opinion.
GRADER_MODEL = "o4-mini"

#: Shuffle seed for the blind pass. Written here so the order the grader saw is
#: reproducible and was not re-rolled.
SHUFFLE_SEED = 20260802

CORRECT = "correct_and_useful"
WRONG = "wrong"
BAD_TEACHING = "correct_but_bad_teaching"
BUCKETS = (CORRECT, WRONG, BAD_TEACHING)


# --------------------------------------------------------------------------
# Layer 1 and 3: mechanical
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .,;:?!\"'()")


class Source:
    """The indexed book, asked one question: is this string in it, verbatim?"""

    def __init__(self) -> None:
        self._index = CorpusIndex.open(INDEX)
        self._db = sqlite3.connect(INDEX)
        self._db.row_factory = sqlite3.Row

    def contains(self, answer: str) -> str | None:
        """The citation of the first page containing `answer`, or None.

        Searched over the whole book rather than the item's own retrieval: the
        question at this layer is "does the source support this at all", which
        is a weaker and fairer test than the gate's "is it in what *this*
        attempt retrieved".
        """
        span = self._index.support(answer, limit=25)
        if span is not None:
            return span.as_citation()
        # FTS tokenisation can miss a phrase whose words are common; fall back to
        # a folded scan of every page. Slow, and only reached for the handful of
        # answers the index does not turn up.
        folded, _ = spans._normalize(answer)  # noqa: SLF001
        if not folded:
            return None
        for row in self._db.execute("SELECT source_id, text FROM page"):
            page, _ = spans._normalize(row["text"])  # noqa: SLF001
            if folded in page:
                return f"{row['source_id']} (folded page scan)"
        return None

    def context(self, source_id: str, start: int, end: int, window: int = 700) -> str:
        text = self._index.page_text(source_id)
        return text[max(0, start - window) : min(len(text), end + window)]

    def chunk_text(self, chunk_id: str) -> str:
        row = self._db.execute(
            "SELECT text FROM chunk WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return row["text"] if row else ""

    def close(self) -> None:
        self._index.close()
        self._db.close()


_LIST_JOINERS = re.compile(r"\b(and|or)\b|,|;")


def teaching_defects(item: dict[str, Any], batch: list[dict[str, Any]]) -> list[str]:
    """The `pset/QUALITY.md` failure modes, as rules rather than as a reading.

    Each rule is one of the defects a person found by hand in the last batch.
    They are deliberately narrow: a rule that fires on a merely easy question
    would be scoring difficulty, which is not a defect.
    """
    found: list[str] = []
    answer = normalise(item["answer"])
    stem = normalise(item["stem"])
    options = [item["answer"], *item["distractors"]]
    folded = [normalise(o) for o in options]

    if answer and answer in stem:
        found.append("stem contains the answer")
    # "option lists naming the same thing twice" — the defect h2-1D-02 had, where
    # "citric acid cycle" and "Krebs cycle" were both offered.
    #
    # **This rule was wrong the first time and the correction is recorded rather
    # than quietly applied.** It originally fired on substring containment as
    # well as equality, on the theory that one option containing another names
    # the same thing. It does not: it fired on 13 option sets, and every one was
    # a minimal pair — competitive / noncompetitive inhibition, sympathetic /
    # parasympathetic, thyroid / parathyroid, unipolar / pseudounipolar,
    # hypothalamus / thalamus, spontaneous / nonspontaneous. Those are the
    # *best* distractors an item can have, not a defect, and a rule that
    # penalised them would have moved 13 cards out of "correct and useful" for
    # being well written. Exact equality after folding is all that is left,
    # which fires on nothing here; genuine synonym pairs are left to the blind
    # grader, which is told to look for them.
    for i, a in enumerate(folded):
        for b in folded[i + 1 :]:
            if a and b and a == b:
                found.append(f"two options are the same string: {a!r}")
    if len(item["answer"].split()) > 8:
        found.append("answer is a clause, not a term")
    # A near-duplicate of another card in the batch: same answer, same Topic.
    for other in batch:
        if other["id"] == item["id"]:
            continue
        if (
            normalise(other["answer"]) == answer
            and other["topic"] == item["topic"]
            and answer
        ):
            found.append(f"near-duplicate answer of {other['id']}")
            break
    return found


# --------------------------------------------------------------------------
# Layer 2: the blind grade
# --------------------------------------------------------------------------

#: Shares no wording with `speedrun_agent.generators.PROMPT`, on purpose: a
#: grader primed with the drafting instructions grades the instructions rather
#: than the card. It is told what the three buckets are in the manifest's own
#: words and nothing about how the card was made.
GRADE_PROMPT = """\
You are reviewing one multiple-choice flashcard that a study tool produced from a \
biology textbook. You are not writing or fixing the card. Work through the two \
steps below in order.

REFERENCE FACT (written by a person from the same textbook, for the same topic):
  Q: {gold_question}
  A: {gold_answer}

EXCERPTS FROM THE TEXTBOOK (the passages this card was drafted from, plus the \
sentences around the phrase the answer was taken from):
{context}

THE CARD
  Question: {stem}
  Options: {options}
  Marked correct: {answer}

STEP 1 - is it wrong?
Wrong means: the marked answer contradicts the reference fact, or contradicts \
the excerpts, or is false biology. These excerpts are a few pages of a large \
textbook. If a fact simply does not appear in them, that is NOT evidence the \
book contradicts it, and is NOT a reason to call the card wrong. A card that \
asks about a different fact from the reference fact is not wrong for that reason \
either.

STEP 2 - if it is not wrong, check every one of these defects and list the ones \
that apply. Check them one at a time; do not skip to a verdict.
  a. two of the four options name the same thing, or one option is a synonym or \
a paraphrase of another, or a more general option that also contains the marked \
answer.
  b. the question already contains the answer, its definition, or a synonym of \
it - so a student could answer without knowing the biology.
  c. the question names one of the four options, or otherwise rules an option \
out by its wording.
  d. the options are not the same kind of thing (one is a process and another is \
a structure; one is a noun phrase and another a verb phrase), or some are \
implausible on sight given what the question asks for.
  e. the marked answer is a phrase lifted out of prose rather than a term, name \
or number a student could produce.
  f. the card tests two facts at once, or its fact is trivia with no bearing on \
the topic the reference fact is about.

If any defect applies, the card is "correct_but_bad_teaching". If none does, it \
is "correct_and_useful". An easy question is not a defect and neither is a \
question about a fact the reference fact does not mention. A card you cannot \
place goes in "correct_but_bad_teaching".

Reply with the defect letters you found (empty if none), the category, and one \
short sentence of reason.
"""

GRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "defects": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": list(BUCKETS)},
        "reason": {"type": "string"},
    },
    "required": ["defects", "category", "reason"],
    "additionalProperties": False,
}


def blind_grade(client: Any, card: dict[str, Any]) -> dict[str, Any]:
    response = client.responses.create(
        model=GRADER_MODEL,
        max_output_tokens=4000,
        input=GRADE_PROMPT.format(**card["prompt_fields"]),
        text={
            "format": {
                "type": "json_schema",
                "name": "card_grade",
                "schema": GRADE_SCHEMA,
                "strict": True,
            }
        },
    )
    if response.status != "completed" or not response.output_text:
        return {"category": None, "reason": f"grader status {response.status}"}
    parsed = json.loads(response.output_text)
    parsed["grader_model"] = response.model
    return parsed


# --------------------------------------------------------------------------
# Assembling the cards
# --------------------------------------------------------------------------


def load_arms() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm in ("gated", "ungated"):
        path = OUT_DIR / f"{arm}.jsonl"
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def load_gold() -> dict[str, dict[str, Any]]:
    return {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in GOLD_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def build_cards() -> list[dict[str, Any]]:
    """Every card, with its gold pair, its source context and its blind token.

    The blind token is what the grader sees instead of an id. `g19` and `u19`
    would tell it the arm; `card-047` tells it nothing.
    """
    items = load_arms()
    gold = load_gold()
    source = Source()
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_arm.setdefault(item["arm"], []).append(item)

    cards: list[dict[str, Any]] = []
    try:
        for item in items:
            pair = gold[item["gold_id"]]
            span = item["span"]
            # The four passages the generator was handed, then the sentences
            # around the phrase the answer came from. The first is what the card
            # was drafted from, so it is the fair thing to judge the card
            # against; the second is where the exact answer string lives.
            drafted_from = "\n".join(
                f"  [passage {n + 1}] {source.chunk_text(cid)}"
                for n, cid in enumerate(item["retrieved"][:4])
            )
            context = (
                drafted_from
                + "\n  [around the cited phrase] ..."
                + source.context(item["source_id"], span["start"], span["end"])
                + "..."
            )
            cards.append(
                {
                    "id": item["id"],
                    "arm": item["arm"],
                    "gold_id": item["gold_id"],
                    "topic": item["topic"],
                    "stem": item["stem"],
                    "answer": item["answer"],
                    "distractors": item["distractors"],
                    "answer_in_retrieved": item["answer_in_retrieved"],
                    "answer_in_source": source.contains(item["answer"]),
                    "defects": teaching_defects(item, by_arm[item["arm"]]),
                    "prompt_fields": {
                        "gold_question": pair["question"],
                        "gold_answer": pair["answer"],
                        "context": context.replace("\n", " "),
                        "stem": item["stem"],
                        "options": "; ".join(
                            sorted([item["answer"], *item["distractors"]])
                        ),
                        "answer": item["answer"],
                    },
                }
            )
    finally:
        source.close()

    order = random.Random(SHUFFLE_SEED)
    order.shuffle(cards)
    for index, card in enumerate(cards):
        card["blind_token"] = f"card-{index:03d}"
    return cards


def bucket_for(card: dict[str, Any], model_bucket: str | None) -> tuple[str, str]:
    """The precedence rule, in one place. Returns (bucket, why)."""
    if not card["answer_in_source"]:
        return WRONG, "mechanical: answer is in no page of the source"
    if model_bucket == WRONG:
        return WRONG, "blind grader: wrong"
    if card["defects"]:
        return BAD_TEACHING, "mechanical: " + "; ".join(card["defects"])
    if model_bucket in (CORRECT, BAD_TEACHING):
        return model_bucket, "blind grader"
    return BAD_TEACHING, "grader gave no usable bucket; conservative tie-break"


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------


def cmd_mechanical() -> int:
    cards = build_cards()
    ungrounded = [c for c in cards if not c["answer_in_source"]]
    with_defects = [c for c in cards if c["defects"]]
    for arm in ("gated", "ungated"):
        arm_cards = [c for c in cards if c["arm"] == arm]
        print(
            f"{arm:<8} items {len(arm_cards):>3}  "
            f"answer in retrieved {sum(c['answer_in_retrieved'] for c in arm_cards):>3}  "
            f"answer in source {sum(bool(c['answer_in_source']) for c in arm_cards):>3}  "
            f"teaching defects {sum(bool(c['defects']) for c in arm_cards):>3}"
        )
    print(f"\nungrounded anywhere in the book: {len(ungrounded)}")
    for card in ungrounded:
        print(f"  {card['id']} {card['gold_id']}  {card['answer']!r}")
    print(f"\nmechanical teaching defects: {len(with_defects)}")
    for card in with_defects:
        print(f"  {card['id']} {card['arm']:<8} {card['answer'][:30]:<32} {card['defects']}")
    (OUT_DIR / "cards.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nwrote {OUT_DIR / 'cards.json'} ({len(cards)} cards)")
    return 0


def cmd_sample(size: int, *, seed_offset: int = 1, exclude: set[str] | None = None) -> int:
    """Dump a stratified sample for a person to bucket by hand, arm hidden.

    Stratified by arm so the agreement rate is not measured on one arm, and
    drawn with its own fixed seed so the sample was not chosen after seeing
    which cards the model found hard.

    `exclude` is how the **held-out** sample is drawn: the grading prompt was
    revised once after the first hand-check disagreed with it, so an agreement
    rate measured on those same 30 cards is fitted to them. `--sample2` draws
    from the cards the revision never saw, and that rate is the honest one.
    """
    cards = json.loads((OUT_DIR / "cards.json").read_text(encoding="utf-8"))
    if exclude:
        cards = [c for c in cards if c["blind_token"] not in exclude]
    picker = random.Random(SHUFFLE_SEED + seed_offset)
    chosen: list[dict[str, Any]] = []
    for arm in ("gated", "ungated"):
        pool = sorted([c for c in cards if c["arm"] == arm], key=lambda c: c["blind_token"])
        chosen += picker.sample(pool, size // 2)
    chosen.sort(key=lambda c: c["blind_token"])
    for card in chosen:
        fields = card["prompt_fields"]
        print(f"\n=== {card['blind_token']}   (gold {card['gold_id']})")
        print(f"  gold : {fields['gold_question']}  ->  {fields['gold_answer']}")
        print(f"  stem : {card['stem']}")
        print(f"  opts : {fields['options']}")
        print(f"  ans  : {card['answer']}")
        print(f"  src  : ...{fields['context'][:900]}...")
    print(f"\n{len(chosen)} cards sampled, {size // 2} per arm.")
    return 0


def cmd_grade(workers: int) -> int:
    from openai import OpenAI  # noqa: PLC0415

    cards = json.loads((OUT_DIR / "cards.json").read_text(encoding="utf-8"))
    done = set()
    if GRADES.exists():
        done = {
            json.loads(line)["blind_token"]
            for line in GRADES.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    todo = [c for c in cards if c["blind_token"] not in done]
    client = OpenAI(api_key=key("OPENAI_API_KEY"))

    def one(card: dict[str, Any]) -> dict[str, Any]:
        try:
            graded = blind_grade(client, card)
        except Exception as exc:  # noqa: BLE001 - one failed call is not the run
            graded = {"category": None, "reason": f"{type(exc).__name__}: {exc}"}
        return {
            "blind_token": card["blind_token"],
            "id": card["id"],
            "model_bucket": graded.get("category"),
            "model_defects": graded.get("defects", []),
            "model_reason": graded.get("reason", ""),
            "grader_model": graded.get("grader_model", GRADER_MODEL),
            "graded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, todo):
            with GRADES.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  {row['blind_token']}  {str(row['model_bucket']):<26} {row['model_reason'][:70]}")
    print(f"\ngraded {len(todo)} card(s) with {GRADER_MODEL}")
    return 0


def final_buckets() -> list[dict[str, Any]]:
    cards = json.loads((OUT_DIR / "cards.json").read_text(encoding="utf-8"))
    grades = {
        json.loads(line)["blind_token"]: json.loads(line)
        for line in GRADES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    out = []
    for card in cards:
        grade = grades.get(card["blind_token"], {})
        bucket, why = bucket_for(card, grade.get("model_bucket"))
        out.append(card | {"bucket": bucket, "why": why} | {
            "model_bucket": grade.get("model_bucket"),
            "model_reason": grade.get("model_reason", ""),
        })
    return out


def cmd_report() -> int:
    graded = final_buckets()
    #: The manifest's denominator is 50 — the number of generation requests —
    #: not the number of cards that came back. A request that produced nothing
    #: is not a card in a bucket, and dividing by 47 would quietly reward an arm
    #: for declining.
    denominator = 50

    print(f"{'':<10} {'correct+useful':>15} {'wrong':>8} {'bad teaching':>14}   of 50 requests")
    rates: dict[str, dict[str, float]] = {}
    for arm in ("gated", "ungated"):
        cards = [c for c in graded if c["arm"] == arm]
        counts = {b: sum(c["bucket"] == b for c in cards) for b in BUCKETS}
        rates[arm] = {b: 100.0 * counts[b] / denominator for b in BUCKETS}
        print(
            f"{arm:<10} {counts[CORRECT]:>7} {rates[arm][CORRECT]:>6.0f}% "
            f"{counts[WRONG]:>3} {rates[arm][WRONG]:>4.0f}% "
            f"{counts[BAD_TEACHING]:>7} {rates[arm][BAD_TEACHING]:>5.0f}%"
            f"   (no card: {denominator - len(cards)})"
        )

    print("\nthe frozen cutoff, all three of which must hold")
    ok1 = rates["gated"][CORRECT] >= 70.0
    ok2 = rates["gated"][WRONG] <= 10.0
    ok3 = rates["gated"][WRONG] < rates["ungated"][WRONG]
    print(f"  1. correct and useful >= 70%      gated {rates['gated'][CORRECT]:.0f}%   {'PASS' if ok1 else 'FAIL'}")
    print(f"  2. wrong <= 10%                   gated {rates['gated'][WRONG]:.0f}%   {'PASS' if ok2 else 'FAIL'}")
    print(
        f"  3. gated wrong < ungated wrong    {rates['gated'][WRONG]:.0f}% vs "
        f"{rates['ungated'][WRONG]:.0f}%   {'PASS' if ok3 else 'FAIL'}"
    )
    print(f"\n  overall: {'PASS' if (ok1 and ok2 and ok3) else 'FAIL'}")

    by_token = {c["blind_token"]: c for c in graded}
    for label, path, caveat in (
        ("hand-check (prompt was revised against these — fitted)", HANDCHECK, ""),
        ("hand-check, HELD OUT (never seen by the prompt revision)", HANDCHECK2, ""),
    ):
        if not path.exists():
            print(f"\n{label}: {path.name} absent — not measured{caveat}")
            continue
        hand = json.loads(path.read_text(encoding="utf-8"))["buckets"]
        agree = [t for t, b in hand.items() if by_token[t]["bucket"] == b]
        print(
            f"\n{label}: {len(agree)} of {len(hand)} agree "
            f"({100.0 * len(agree) / len(hand):.0f}%)"
        )
        for token, mine in hand.items():
            auto = by_token[token]["bucket"]
            if auto != mine:
                print(
                    f"  disagree {token} ({by_token[token]['id']}): "
                    f"hand={mine} auto={auto}  [{by_token[token]['why']}]"
                )

    (OUT_DIR / "buckets.jsonl").write_text(
        "\n".join(
            json.dumps(
                {k: c[k] for k in ("id", "arm", "gold_id", "topic", "answer", "bucket", "why", "model_bucket", "model_reason")},
                ensure_ascii=False,
            )
            for c in graded
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {OUT_DIR / 'buckets.jsonl'}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mechanical", action="store_true")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument(
        "--sample2",
        type=int,
        default=0,
        help="a second hand-check sample, excluding everything in handcheck.json",
    )
    parser.add_argument("--grade", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    if args.mechanical:
        return cmd_mechanical()
    if args.sample:
        return cmd_sample(args.sample)
    if args.sample2:
        already = set(json.loads(HANDCHECK.read_text(encoding="utf-8"))["buckets"])
        return cmd_sample(args.sample2, seed_offset=2, exclude=already)
    if args.grade:
        return cmd_grade(args.workers)
    if args.report:
        return cmd_report()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

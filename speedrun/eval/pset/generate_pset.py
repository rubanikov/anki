#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate the P-set (H2) — Held-out items, desktop-side, never in the Collection.

This script does **not** generate anything itself. It drives `speedrun/agent/`,
which owns retrieval, the model call and the Generation gate, and it writes what
that service ships to a file the Collection never sees. Two things are this
script's own responsibility and nothing else is:

**1. Making the requests genuinely distinct.** The first sweep sent the same
prompt three times per Topic — `seed` selects among the *stub's* canned claims
and is not passed to a model — so 27 attempts produced 20 distinct citations.
Three copies of one item is one item, and a held-out set of copies measures a
student once. Each attempt here differs in three ways at once:

- a **target concept**, taken from the AAMC Outline's own itemised topic list for
  that category (`corpus/outline.json`), chosen by a fixed rule below;
- the **retrieved passages**, because the concept is prepended to the Outline
  query BM25 runs, so different attempts on one Topic read different pages;
- the **question type**, rotated through four fixed forms.

The concepts come from the Outline rather than from anything we hoped the book
would say, and they are picked by a stated rule rather than by hand, so the plan
is reproducible: `--plan` prints it without calling a model.

**2. Asking for an item a student could actually be given.** The gate proves an
answer is *grounded*; it cannot tell a term from a whole sentence lifted out of
the prose, and the first sweep shipped two of the latter. The prompt this script
installs adds the constraint the gate cannot check — a short, specific answer —
on top of the service's own prompt, which is otherwise used verbatim.

That addition is a deliberate, reported deviation: `speedrun/agent/generators.py`
keeps one prompt for both providers so a Yield comparison stays a retrieval
finding, and these items are therefore **not** comparable with the Yield table in
the agent's README. The prompt each item was produced under is recorded on the
item.

**What never happens here.** No item text, and no previously accepted answer,
enters a generation prompt — that would be Leakage under the H2 protocol, so
distinctness is bought with the Outline and the corpus, never with "don't repeat
these". Nothing this script writes goes near the Collection.

Ledger discipline: an item is appended to `MANIFEST.md`'s H2 ledger by
`freeze.py --append-item` **as it is produced**, before the run continues.

Usage (from the repo root, with the agent's own interpreter):

    speedrun/agent/.venv/Scripts/python speedrun/eval/pset/generate_pset.py --plan
    speedrun/agent/.venv/Scripts/python speedrun/eval/pset/generate_pset.py --run
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PSET_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = PSET_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
HOLDOUT_DIR = SPEEDRUN_DIR / "eval" / "holdout"

#: The canonical item file this script owns.
PSET_FILE = PSET_DIR / "h2_pset.jsonl"
#: The path the frozen protocol names for H2. `freeze.py` reads this one, and it
#: is byte-identical to the file above — the protocol was frozen before this
#: ticket and its path is not ours to move.
HOLDOUT_FILE = HOLDOUT_DIR / "h2_pset.jsonl"
RUN_LOG = PSET_DIR / "run_log.jsonl"
OUT_DIR = PSET_DIR / "out"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(CORPUS_DIR))

from speedrun_agent import generators, topics  # noqa: E402
from speedrun_agent.attribution import latest, payload  # noqa: E402
from speedrun_agent.corpus_gateway import Bm25Corpus, RetrievedChunk  # noqa: E402
from speedrun_agent.generators import OpenAIGenerator  # noqa: E402
from speedrun_agent.graph import GATE, Request, build_graph  # noqa: E402
from speedrun_agent.rejections import AttemptLog  # noqa: E402
from speedrun_agent.tracing import LocalTracer  # noqa: E402

# --------------------------------------------------------------------------
# The plan: what makes one attempt different from the next
# --------------------------------------------------------------------------

#: Four question forms, rotated across a Topic's attempts. Fixed here rather
#: than sampled, so the same plan comes out of `--plan` every time.
QUESTION_TYPES: tuple[str, ...] = (
    "an identification question - name the structure, molecule or term the "
    "passage describes",
    "a function question - what the named thing does, or what it is for",
    "a mechanism question - what happens at a specific step, or what causes what",
    "a discrimination question - which of two similar things the described case is",
)

#: How many attempts each Topic gets. Nine Bio/Biochem categories x 4 = 36
#: generation calls, which is the cost ceiling this ticket was given.
ATTEMPTS_PER_TOPIC = 4

#: Outline lines that are section headings rather than concepts. A heading is
#: short and ends in its own subject-code parenthesis, e.g. "Amino Acids (BC, OC)".
_HEADING_WORDS = 5

#: Lines made only of these say nothing about *what* to ask — "Description;
#: structure" is a bullet the AAMC page indents under a real concept, and the
#: transcription flattened the nesting (the Outline's own provenance note says
#: so). Dropped rather than steered on.
_EMPTY_WORDS = {
    "description",
    "definition",
    "structure",
    "function",
    "general",
    "concept",
    "concepts",
    "principles",
    "and",
    "of",
    "the",
}


def _is_concept(line: str) -> bool:
    text = line.strip()
    if len(text) < 12:
        return False
    if text.endswith(")") and len(text.split()) <= _HEADING_WORDS:
        return False
    words = {w.strip(" .,;:()") for w in text.casefold().split()}
    return bool(words - _EMPTY_WORDS)


def _outline() -> Any:
    import outline  # noqa: PLC0415  (corpus/ is a script directory, not a package)

    return outline.load_outline(CORPUS_DIR / "outline.json")


def demo_section_topics() -> list[str]:
    """The nine Bio/Biochem categories — the only section this corpus indexes."""
    return [category.id for category in _outline().in_section("BB")]


def concepts_for(topic_id: str, count: int) -> list[str]:
    """`count` target concepts for a Topic, spread across the Outline's own list.

    The rule: keep the lines that read as concepts rather than headings, then
    take `count` of them at evenly spaced positions — (2i+1)/2n through the list
    — so four attempts on one category land in four different corners of it
    instead of four times in its first paragraph. Deterministic, and derived
    from AAMC's words, not ours.
    """
    category = _outline().get(topic_id)
    lines = [line.strip() for line in category.all_topic_text() if _is_concept(line)]
    if not lines:
        return [category.title] * count
    picked = []
    for i in range(count):
        index = min(len(lines) - 1, (2 * i + 1) * len(lines) // (2 * count))
        picked.append(lines[index])
    return picked


@dataclass(frozen=True)
class Attempt:
    topic_id: str
    index: int
    concept: str
    question_type: str


def plan(topic_ids: list[str], per_topic: int) -> list[Attempt]:
    attempts: list[Attempt] = []
    for topic_id in topic_ids:
        for index, concept in enumerate(concepts_for(topic_id, per_topic)):
            attempts.append(
                Attempt(
                    topic_id=topic_id,
                    index=index,
                    concept=concept,
                    question_type=QUESTION_TYPES[index % len(QUESTION_TYPES)],
                )
            )
    return attempts


# --------------------------------------------------------------------------
# The prompt: the service's own, plus the constraint the gate cannot check
# --------------------------------------------------------------------------

ADDENDUM = """\
Target concept: {concept}
Ask about that concept specifically. Ignore the parts of the passages that are \
about something else, and if the passages do not support a question about it, \
set "skip" to true rather than asking about whatever they do support.

Question type: {question_type}.

The correct answer must be SHORT and specific - a term, a name, a number, or a \
noun phrase of at most six words - and still copied verbatim from a passage. A \
whole sentence, or a clause lifted out of the prose, is not an answer: if the \
only verbatim string you can find is a sentence, pick a different fact in the \
passages or set "skip" to true. The three distractors must be the same kind of \
thing as the answer and of similar length.

The stem must read as an exam question a student could answer with no passage in \
front of them: self-contained, one or two sentences, no "according to the \
passage", no reference to the text.
"""


class _PerThreadPrompt:
    """Stands in for `generators.PROMPT` so each attempt can carry its own.

    The generator reads the module-level `PROMPT` at call time and formats it
    with `topic_id` and `passages`. Installing an object with the same `.format`
    contract lets one attempt's addendum reach its own model call and no other
    thread's, without touching `speedrun/agent/` — which this ticket does not
    own and which is right to keep one prompt of its own.
    """

    def __init__(self, base: str) -> None:
        self._base = base
        self._local = threading.local()

    def use(self, addendum: str) -> None:
        head, _, tail = self._base.partition("Passages:")
        self._local.template = f"{head}{addendum}\nPassages:{tail}"

    @property
    def current(self) -> str:
        return getattr(self._local, "template", self._base)

    def format(self, **values: Any) -> str:
        return self.current.format(**values)


# --------------------------------------------------------------------------
# Retrieval: the concept steers which passages the model is handed
# --------------------------------------------------------------------------


class ConceptSteeredCorpus:
    """The real corpus, queried with the target concept in front of the Outline query.

    Retrieval, matching and page text are all still the corpus package's. What
    changes is the query string: `"<concept> <Outline query>"`, so BM25 ranks the
    pages about this attempt's concept above the category's general prose. The
    concept is AAMC's own words and never the candidate answer, which is the
    property `topics.py` cares about — a query derived from the answer would hand
    the gate the string it is about to look for.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._local = threading.local()

    def steer(self, concept: str) -> None:
        self._local.concept = concept

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]:
        concept = getattr(self._local, "concept", "")
        return self._inner.retrieve(
            f"{concept} {query}".strip(), limit=limit, categories=categories
        )

    def page_text(self, source_id: str) -> str:
        return self._inner.page_text(source_id)

    def stats(self) -> dict[str, Any]:
        return self._inner.stats()

    def close(self) -> None:
        self._inner.close()


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    return " ".join(ch for ch in text.casefold().split() if ch).strip(" .,;:?!")


def item_record(
    *,
    item_id: str,
    attempt: Attempt,
    shipped: dict[str, Any],
    attempt_id: str,
    prompt: str,
) -> dict[str, Any]:
    """One P-set row. The first seven fields are what H2's item hash covers."""
    body = shipped["item"]
    span = dict(shipped["span"])
    options = [body["answer"], *body["distractors"]]
    random.Random(item_id).shuffle(options)
    return {
        "id": item_id,
        "topic": attempt.topic_id,
        "stem": body["stem"],
        "options": options,
        "answer": body["answer"],
        "source_id": shipped["source_id"],
        "source_span": {
            "chunk_id": span["chunk_id"],
            "start": span["start"],
            "end": span["end"],
            # The source's own characters, copied out of the page by the gate.
            "quote": span["quote"],
            "block_id": span["block_id"],
            "url": span["url"],
        },
        # --- not covered by the hash: provenance and bookkeeping ---
        "citation": shipped["citation"],
        "generator": body["generator"],
        "model": body["model"],
        "attempt_id": attempt_id,
        "target_concept": attempt.concept,
        "question_type": attempt.question_type,
        "prompt_sha256": _sha256(prompt),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "live",
    }


def _sha256(text: str) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _existing_items() -> list[dict[str, Any]]:
    if not PSET_FILE.exists():
        return []
    return [
        json.loads(line)
        for line in PSET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_and_ledger(record: dict[str, Any]) -> bool:
    """Write one item, mirror it to the protocol's path, ledger it. In that order.

    The H2 protocol says an item's id and hash are in the ledger before it is
    shown. Nothing here shows anything, but the ordering is kept literally: the
    item is on disk and in `MANIFEST.md` before the next attempt starts.
    """
    line = json.dumps(record, ensure_ascii=False)
    with PSET_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    HOLDOUT_FILE.write_bytes(PSET_FILE.read_bytes())
    result = subprocess.run(
        [sys.executable, str(HOLDOUT_DIR / "freeze.py"), "--append-item", "--set", "H2"],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    return result.returncode == 0


def log_run(row: dict[str, Any]) -> None:
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------


def run(attempts: list[Attempt], workers: int) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PSET_FILE.touch()
    HOLDOUT_FILE.write_bytes(PSET_FILE.read_bytes())

    prompt = _PerThreadPrompt(generators.PROMPT)
    generators.PROMPT = prompt  # type: ignore[assignment]

    corpus = ConceptSteeredCorpus(Bm25Corpus.open())
    # 8000 rather than the constructor's 4000: a single attempt was observed
    # spending 2112 tokens on reasoning before writing a 60-token item, and a
    # truncated response is counted as `generator_empty` — a budget artefact
    # masquerading as a generator declining. Nothing else is reconfigured; the
    # model, the reasoning effort and the schema are the service's own.
    generator = OpenAIGenerator(max_output_tokens=8000)
    log = AttemptLog(OUT_DIR / "attempts.jsonl")
    tracer = LocalTracer(OUT_DIR / "trace.jsonl")
    graph = build_graph(corpus=corpus, generator=generator, log=log, tracer=tracer)

    lock = threading.Lock()
    seen_stems: set[str] = set()
    seen_answers: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    # Resume from whatever is already in the set: ids keep counting up, and an
    # item generated on an earlier run still blocks a duplicate of itself. The
    # file is append-only by protocol, so this is the only safe way to re-run.
    for existing in _existing_items():
        counts[existing["topic"]] = counts.get(existing["topic"], 0) + 1
        seen_stems.add(normalise(existing["stem"]))
        seen_answers.add((existing["topic"], normalise(existing["answer"])))

    # An id has to exist before the item does, and two threads must not mint the
    # same one. Reserved under the lock, in completion order.
    def mint(topic_id: str) -> str:
        counts[topic_id] = counts.get(topic_id, 0) + 1
        return f"h2-{topic_id}-{counts[topic_id]:02d}"

    def one(attempt: Attempt) -> dict[str, Any]:
        started = time.time()
        corpus.steer(attempt.concept)
        prompt.use(
            ADDENDUM.format(
                concept=attempt.concept, question_type=attempt.question_type
            )
        )
        used = prompt.current
        request = Request(topic_id=attempt.topic_id, seed=attempt.index)
        row: dict[str, Any] = {
            "topic": attempt.topic_id,
            "attempt_index": attempt.index,
            "target_concept": attempt.concept,
            "question_type": attempt.question_type,
            "attempt_id": request.attempt_id,
            "prompt_sha256": _sha256(used),
        }
        try:
            state = graph.invoke({"request": request, "trail": []})
        except Exception as exc:  # noqa: BLE001 - one failed call is not the run
            row |= {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"}
            row["seconds"] = round(time.time() - started, 1)
            return row
        row["seconds"] = round(time.time() - started, 1)
        shipped = payload(latest(state.get("trail", []), GATE))
        if shipped is None:
            ruling = state.get("rejection")
            row |= {
                "outcome": "dropped",
                "reason": str(ruling.reason) if ruling else "unattributed_output",
                "detail": (ruling.detail if ruling else "")[:300],
            }
            return row

        body = shipped["item"]
        stem_key = normalise(body["stem"])
        answer_key = (attempt.topic_id, normalise(body["answer"]))
        with lock:
            if stem_key in seen_stems or answer_key in seen_answers:
                row |= {
                    "outcome": "duplicate",
                    "answer": body["answer"],
                    "citation": shipped["citation"],
                }
                return row
            seen_stems.add(stem_key)
            seen_answers.add(answer_key)
            record = item_record(
                item_id=mint(attempt.topic_id),
                attempt=attempt,
                shipped=shipped,
                attempt_id=request.attempt_id,
                prompt=used,
            )
            ledgered = append_and_ledger(record)
        row |= {
            "outcome": "shipped",
            "item_id": record["id"],
            "answer": record["answer"],
            "answer_words": len(record["answer"].split()),
            "citation": record["citation"],
            "ledgered": ledgered,
        }
        return row

    shipped_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, attempts):
            log_run(row)
            shipped_count += row["outcome"] == "shipped"
            print(
                f"  {row['topic']}#{row['attempt_index']} "
                f"{row['outcome']:<9} {row.get('reason', ''):<28} "
                f"{row.get('answer', '')[:60]}"
            )

    tally = log.tally()
    print(f"\nattempts {len(attempts)}  shipped {shipped_count}")
    print(f"gate tally: {json.dumps(tally, ensure_ascii=False)}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="generate items")
    parser.add_argument(
        "--plan", action="store_true", help="print the attempt plan; no model call"
    )
    parser.add_argument(
        "--topics", default="", help="comma-separated Topic ids (default: all Bio/Biochem)"
    )
    parser.add_argument("--per-topic", type=int, default=ATTEMPTS_PER_TOPIC)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)

    ids = (
        [t.strip() for t in args.topics.split(",") if t.strip()]
        if args.topics
        else demo_section_topics()
    )
    attempts = plan(ids, args.per_topic)

    if args.plan or not args.run:
        for attempt in attempts:
            print(
                f"{attempt.topic_id}#{attempt.index}  {attempt.concept}\n"
                f"          {attempt.question_type}"
            )
        print(f"\n{len(attempts)} attempts across {len(ids)} topics")
        return 0
    return run(attempts, workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

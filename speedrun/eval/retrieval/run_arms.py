#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""ADR-0006's retrieval comparison: one gate, four arms, Yield as the metric.

The gate, the prompt, the model, the chunk budget and the query set are held
constant. Only the retriever varies. Three arms therefore cost generation calls
— BM25, embeddings, hybrid — and the fourth costs none, because the ungated
control is the hybrid arm's own proposals read with the gate's ruling ignored.
That is not a shortcut: it makes the control a *paired* measurement on exactly
the items the gated arm was judged on, which is stronger than running it
separately would have been.

A fifth set of arms, also free, drives the same three retrievers with the
shipped `RememberedAnswerGenerator` instead of a model. It exists because the
first run of this sweep found the gate rejecting nothing at all, and a gate that
never fires cannot be told from an absent one without a generator that gives it
something to do. See `remembered_controls`.

**Two declared deviations from ADR-0006, both fixed before the first run.**

1. The ADR names 31 content categories. This corpus is OpenStax *Biology* and
   indexes the 9 Bio/Biochem categories only; the other 22 have no chunks at
   all. Running them would produce 66 `no_retrieval` rows and a yield table that
   looked like a retrieval finding while measuring the absence of a book. The
   query set is the 9 categories that exist, and the report says so.

2. The ADR names three generation requests per category. This ticket's cost
   budget is 40-60 generation calls across all arms, and three requests over
   three generating arms is 81. Two requests per category is 54. The smaller
   number is the one that fits, and the consequence — wide confidence intervals,
   arms that may not separate — is reported rather than hidden.

**What makes two requests in one category different requests.** The first sweep
in this project sent one prompt repeatedly and counted the copies, which is one
request reported as three. Every attempt here differs in three ways at once, on
the pattern `speedrun/eval/pset/generate_pset.py` established:

- a **target concept** taken from AAMC's own itemised topic list for the
  category (`corpus/outline.json`), picked by a stated rule;
- the **retrieved passages**, because the concept is prepended to the query all
  four arms share, so two attempts on one category read different pages;
- the **question type**, rotated through four fixed forms.

The concept and the question type are identical across arms for a given
attempt, so anything that moves between arms is retrieval and nothing else.

Usage (from the repo root, with the agent's own interpreter):

    speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/run_arms.py --plan
    speedrun/agent/.venv/Scripts/python speedrun/eval/retrieval/run_arms.py --run
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

RETRIEVAL_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = RETRIEVAL_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
OUT_DIR = RETRIEVAL_DIR / "out"
RESULTS = RETRIEVAL_DIR / "results.json"

for _directory in (str(RETRIEVAL_DIR), str(AGENT_DIR), str(CORPUS_DIR)):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

from retrievers import (  # noqa: E402
    EMBEDDING_MODEL,
    FUSION_DEPTH,
    RRF_K,
    CorpusWideCheck,
    EmbeddingCorpus,
    HybridCorpus,
)
from speedrun_agent import generators  # noqa: E402
from speedrun_agent.attribution import latest  # noqa: E402
from speedrun_agent.corpus_gateway import Bm25Corpus, RetrievedChunk  # noqa: E402
from speedrun_agent.generators import OpenAIGenerator  # noqa: E402
from speedrun_agent.graph import GATE, GENERATE, RETRIEVE, Request, build_graph  # noqa: E402
from speedrun_agent.rejections import AttemptLog  # noqa: E402
from speedrun_agent.tracing import LocalTracer  # noqa: E402

# --------------------------------------------------------------------------
# The plan, fixed before the first run
# --------------------------------------------------------------------------

#: Two requests per category x 9 categories = 18 attempts per arm, 54 across the
#: three generating arms. See the module docstring for why not three.
REQUESTS_PER_CATEGORY = 2

#: The arms that cost generation calls. The control is derived from `hybrid`.
GENERATING_ARMS = ("bm25", "embedding", "hybrid")
CONTROL_SOURCE = "hybrid"

#: Four question forms, rotated across the whole plan rather than within a
#: category, so two categories do not both get only the first two forms.
QUESTION_TYPES: tuple[str, ...] = (
    "an identification question - name the structure, molecule or term the "
    "passage describes",
    "a function question - what the named thing does, or what it is for",
    "a mechanism question - what happens at a specific step, or what causes what",
    "a discrimination question - which of two similar things the described case is",
)

#: OpenAI's published rates for the model this ran on, in USD per million
#: tokens. Written down so the cost line in RETRIEVAL.md can be recomputed from
#: the token counts rather than taken on trust.
USD_PER_MTOK_IN = 1.25
USD_PER_MTOK_OUT = 10.00
USD_PER_MTOK_EMBED = 0.02

# Concept selection, adapted from `speedrun/eval/pset/generate_pset.py`. Copied
# rather than imported: that file belongs to another ticket and this evaluation
# should not break when it changes. The rule is unchanged and stated in full so
# the two can be compared.
_HEADING_WORDS = 5
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


def bio_categories() -> list[str]:
    """The nine Bio/Biochem categories — the only section this corpus indexes."""
    return [category.id for category in _outline().in_section("BB")]


def concepts_for(topic_id: str, count: int) -> list[str]:
    """`count` target concepts for a category, spread across AAMC's own list.

    Keep the Outline lines that read as concepts rather than headings, then take
    `count` of them at evenly spaced positions — (2i+1)/2n through the list — so
    two attempts on one category land in two different corners of it.
    """
    category = _outline().get(topic_id)
    lines = [line.strip() for line in category.all_topic_text() if _is_concept(line)]
    if not lines:
        return [category.title] * count
    return [
        lines[min(len(lines) - 1, (2 * i + 1) * len(lines) // (2 * count))]
        for i in range(count)
    ]


@dataclass(frozen=True)
class Query:
    """One request in the fixed query set. Every arm runs all of them."""

    topic_id: str
    index: int
    concept: str
    question_type: str

    @property
    def label(self) -> str:
        return f"{self.topic_id}#{self.index}"


def query_set(per_category: int = REQUESTS_PER_CATEGORY) -> list[Query]:
    queries: list[Query] = []
    position = 0
    for topic_id in bio_categories():
        for index, concept in enumerate(concepts_for(topic_id, per_category)):
            queries.append(
                Query(
                    topic_id=topic_id,
                    index=index,
                    concept=concept,
                    question_type=QUESTION_TYPES[position % len(QUESTION_TYPES)],
                )
            )
            position += 1
    return queries


# --------------------------------------------------------------------------
# The prompt addendum: identical across arms, so it cannot be the finding
# --------------------------------------------------------------------------

#: Added to `generators.PROMPT` verbatim for every attempt in every arm. It says
#: what to ask about, and nothing about how to ground it — the grounding
#: instruction is the service's own and is left untouched, because an addendum
#: that pushed harder on copying verbatim would raise every arm's yield and
#: change what the comparison measured.
#: The service's own prompt, captured once at import. Each arm installs its own
#: per-thread wrapper over `generators.PROMPT`, so without this the second arm
#: would wrap the first arm's wrapper and every arm after the first would be
#: running a different prompt from the one before it.
BASE_PROMPT = generators.PROMPT

ADDENDUM = """\
Target concept: {concept}
Ask about that concept specifically. Ignore the parts of the passages that are \
about something else, and if the passages do not support a question about it, \
set "skip" to true rather than asking about whatever they do support.

Question type: {question_type}.
"""


class _PerThreadPrompt:
    """Stands in for `generators.PROMPT` so each attempt carries its own.

    The generator reads the module-level `PROMPT` at call time and formats it
    with `topic_id` and `passages`. Installing an object with the same `.format`
    contract lets one attempt's addendum reach its own model call and no other
    thread's, without editing `speedrun/agent/` — which this ticket does not own.
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


class ConceptSteeredCorpus:
    """Any arm's retriever, queried with the concept in front of the query.

    Wrapping rather than editing: the concept is prepended to the string all
    four arms share, so the steering is identical everywhere and the difference
    between arms stays the ranking function. The concept is AAMC's own words and
    never the candidate answer — a query derived from the answer would hand the
    gate the string it is about to look for.
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


def open_arm(arm: str) -> Any:
    if arm == "bm25":
        return Bm25Corpus.open()
    if arm == "embedding":
        return EmbeddingCorpus.open()
    if arm == "hybrid":
        return HybridCorpus.open()
    raise ValueError(f"unknown arm {arm!r}")


# --------------------------------------------------------------------------
# Running one arm
# --------------------------------------------------------------------------


class UsageMeter:
    """Token counts for the cost line, taken off the responses as they land.

    `speedrun/agent/` does not log usage — it has no reason to — and this ticket
    has to report what the sweep cost. Rather than reimplement the call (and
    risk the prompt or the schema drifting away from the service's), the SDK's
    `responses.create` is wrapped in place for the duration of the run. It is a
    reach into a private attribute and it is the only one here; the alternative
    was a second copy of the generator.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self._lock = threading.Lock()

    def attach(self, generator: OpenAIGenerator) -> None:
        resource = generator._client.responses  # noqa: SLF001
        original = resource.create

        def recording(**kwargs: Any) -> Any:
            response = original(**kwargs)
            usage = getattr(response, "usage", None)
            with self._lock:
                self.calls += 1
                if usage is not None:
                    self.input_tokens += getattr(usage, "input_tokens", 0) or 0
                    self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            return response

        resource.create = recording  # type: ignore[method-assign]

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(
                self.input_tokens / 1e6 * USD_PER_MTOK_IN
                + self.output_tokens / 1e6 * USD_PER_MTOK_OUT,
                4,
            ),
        }


def run_arm(
    arm: str, queries: list[Query], workers: int, *, remembered: bool = False
) -> dict[str, Any]:
    """One arm, end to end. Returns its rows and its tally.

    `remembered` swaps the model for `RememberedAnswerGenerator`, the shipped
    stub that answers from a fixed table and never reads the retrieved text. It
    costs nothing and it is the only way this sweep can observe the gate firing:
    see `remembered_controls` below.
    """
    label = f"stub-{arm}" if remembered else arm
    arm_out = OUT_DIR / label
    arm_out.mkdir(parents=True, exist_ok=True)

    prompt = _PerThreadPrompt(BASE_PROMPT)
    generators.PROMPT = prompt  # type: ignore[assignment]

    corpus = ConceptSteeredCorpus(open_arm(arm))
    # 8000 rather than the constructor's 4000, matching what the P-set sweep
    # found: an attempt can spend 2000+ tokens reasoning before writing a
    # 60-token item, and a truncated response is counted `generator_empty` — a
    # budget artefact masquerading as a generator declining. Identical in every
    # arm, so it cannot be the difference between them.
    generator: Any = (
        generators.RememberedAnswerGenerator()
        if remembered
        else OpenAIGenerator(max_output_tokens=8000)
    )
    meter = UsageMeter()
    if not remembered:
        meter.attach(generator)
    log = AttemptLog(arm_out / "attempts.jsonl")
    tracer = LocalTracer(arm_out / "trace.jsonl")
    graph = build_graph(corpus=corpus, generator=generator, log=log, tracer=tracer)

    def one(query: Query) -> dict[str, Any]:
        started = time.time()
        corpus.steer(query.concept)
        prompt.use(
            ADDENDUM.format(concept=query.concept, question_type=query.question_type)
        )
        request = Request(topic_id=query.topic_id, seed=query.index)
        row: dict[str, Any] = {
            "arm": label,
            "topic": query.topic_id,
            "attempt_index": query.index,
            "target_concept": query.concept,
            "question_type": query.question_type,
            "attempt_id": request.attempt_id,
        }
        try:
            state = graph.invoke({"request": request, "trail": []})
        except Exception as exc:  # noqa: BLE001 - one failed call is not the run
            row |= {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"}
            row["seconds"] = round(time.time() - started, 1)
            return row
        row["seconds"] = round(time.time() - started, 1)

        trail = state.get("trail", [])
        retrieved = [
            carried.output for carried in trail if carried.node == RETRIEVE
        ]
        row["retrieved"] = [chunk.chunk_id for chunk in retrieved]
        row["retrieved_pages"] = sorted({chunk.source_id for chunk in retrieved})

        # The proposal is read whether or not the gate liked it. This is what
        # makes the ungated control possible without a second sweep.
        proposal = latest(trail, GENERATE)
        if proposal is not None:
            candidate = proposal.output
            row["candidate"] = {
                "stem": candidate.stem,
                "answer": candidate.answer,
                "distractors": list(candidate.distractors),
                "model": candidate.model,
            }

        shipped = latest(trail, GATE)
        ruling = state.get("rejection")
        if shipped is not None and ruling is None:
            row |= {
                "outcome": "shipped",
                "citation": shipped.span.citation if shipped.span else "",
                "source_id": shipped.source_id,
            }
        else:
            row |= {
                "outcome": "dropped",
                "reason": str(ruling.reason) if ruling else "unattributed_output",
                "detail": (ruling.detail if ruling else "")[:300],
            }
        return row

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, queries):
            rows.append(row)
            print(
                f"  [{label}] {row['topic']}#{row['attempt_index']} "
                f"{row['outcome']:<8} {row.get('reason', ''):<28} "
                f"{(row.get('candidate') or {}).get('answer', '')[:52]}",
                flush=True,
            )

    (arm_out / "rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    corpus.close()
    return {"arm": label, "rows": rows, "tally": log.tally(), "usage": meter.as_dict()}


# --------------------------------------------------------------------------
# Yield, its decomposition, and the control
# --------------------------------------------------------------------------


def wilson(successes: int, total: int) -> tuple[float, float] | None:
    """95% Wilson interval, in units of items per hundred attempts.

    Printed beside every yield because eighteen attempts per arm cannot separate
    arms that differ by a few points, and a table without intervals invites a
    reader to believe it can.
    """
    if total == 0:
        return None
    z = 1.96
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = (
        z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return (round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1))


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    rows = result["rows"]
    shipped = [row for row in rows if row["outcome"] == "shipped"]
    answers = {
        (row["topic"], row["candidate"]["answer"].casefold().strip())
        for row in shipped
        if row.get("candidate")
    }
    by_reason: dict[str, int] = {}
    for row in rows:
        if row["outcome"] != "shipped":
            by_reason[row.get("reason", "error")] = (
                by_reason.get(row.get("reason", "error"), 0) + 1
            )
    return {
        "arm": result["arm"],
        "attempts": len(rows),
        "shipped": len(shipped),
        "distinct_shipped": len(answers),
        "yield_per_hundred": round(100.0 * len(shipped) / len(rows), 1) if rows else None,
        "yield_ci95": wilson(len(shipped), len(rows)),
        "by_reason": by_reason,
        "usage": result["usage"],
        "models": sorted(
            {
                row["candidate"]["model"]
                for row in rows
                if row.get("candidate") and row["candidate"].get("model")
            }
        ),
    }


def control_from(
    result: dict[str, Any] | list[dict[str, Any]],
    check: CorpusWideCheck,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    """The fourth arm: the same proposals, with the gate's ruling ignored.

    "Gate off" means the span assertion is off. The generator-side checks that
    live in the `generate` node — a proposal with no stem, or one that contains
    its own answer — are not the gate and stay on, because an ungated pipeline
    would still have them. So the ungated arm ships every proposal that reached
    the gate, and the question this arm exists to answer is what fraction of
    those have no real source behind them.

    Two levels, because they are different failures:

    - `unsupported_in_retrieved` — the gate's own question. The answer's
      characters are in none of the eight passages the model was shown.
    - `absent_from_corpus` — the stronger one. The answer's characters are on
      none of the 350 indexed pages. This is the number that says an ungated
      pipeline ships items whose supporting text is in no real source.

    ADR-0006 names hybrid as the control's retriever, and that is the figure the
    report leads with. Passing a list pools every arm's proposals instead, which
    buys a denominator three times the size for the same zero generation calls —
    reported beside it, never in place of it.
    """
    results = result if isinstance(result, list) else [result]
    rows = [row for one in results for row in one["rows"]]
    reached_gate = [row for row in rows if row.get("candidate")]
    unsupported: list[dict[str, Any]] = []
    absent: list[dict[str, Any]] = []
    for row in reached_gate:
        answer = row["candidate"]["answer"]
        if row["outcome"] == "shipped":
            continue
        record = {
            "arm": row["arm"],
            "topic": row["topic"],
            "attempt_index": row["attempt_index"],
            "concept": row["target_concept"],
            "stem": row["candidate"]["stem"],
            "answer": answer,
            "gate_reason": row.get("reason"),
        }
        unsupported.append(record)
        source = check.source_for(answer)
        record["elsewhere_in_corpus"] = source
        if source is None:
            absent.append(record)
    return {
        "arm": label or f"{results[0]['arm']}-gate-off (control)",
        "derived_from": [one["arm"] for one in results],
        "attempts": len(rows),
        "ungated_shipped": len(reached_gate),
        "ungated_yield_per_hundred": (
            round(100.0 * len(reached_gate) / len(rows), 1) if rows else None
        ),
        "unsupported_in_retrieved": len(unsupported),
        "unsupported_rate_of_shipped": (
            round(100.0 * len(unsupported) / len(reached_gate), 1)
            if reached_gate
            else None
        ),
        "absent_from_corpus": len(absent),
        "absent_rate_of_shipped": (
            round(100.0 * len(absent) / len(reached_gate), 1) if reached_gate else None
        ),
        "absent_rate_ci95": wilson(len(absent), len(reached_gate)),
        "cases": unsupported,
    }


# --------------------------------------------------------------------------
# The second control: a generator that answers from memory
# --------------------------------------------------------------------------


def remembered_controls(arms: list[str], check: CorpusWideCheck) -> dict[str, Any]:
    """The same three retrievers, driving the stub that never reads a passage.

    The first sweep of this ticket found the gate rejecting nothing at all: a
    model handed the passages and told to copy verbatim did copy verbatim, 39
    times out of 39. That is a real result and it is reported as one, but on its
    own it cannot tell a working gate from an idle one — a gate that never fires
    and a gate that is not there produce the same table.

    `RememberedAnswerGenerator` is the shipped stub that answers from a fixed
    table without consulting retrieval, which is precisely the failure mode the
    gate exists for. Running it costs no API calls, and it does two things at
    once: it shows what the ungated pipeline ships when the generator is *not*
    copying (the control's number under an adversarial generator), and it turns
    the retrieval comparison into a clean one, because the claim is now
    byte-identical across arms and the only question left is whether retrieval
    surfaced the page that supports it.

    These arms run **three** requests per category, not two: the stub's table
    holds three claims per category and the third is where the deliberately
    false ones live — a Krebs cycle in the peroxisome, a phosphodiester linkage
    between amino acids. A control for "would an ungated pipeline ship something
    that is in no source" that never reaches the claims which are in no source
    would be a control in name only. The extra nine attempts per arm cost
    nothing, because no model is called.
    """
    queries = query_set(3)
    results = [run_arm(arm, queries, workers=1, remembered=True) for arm in arms]
    return {
        "note": "generator answers from a fixed table and never reads retrieval",
        "requests_per_category": 3,
        "arms": [summarise(result) for result in results],
        "control": control_from(
            [r for r in results if r["arm"] == f"stub-{CONTROL_SOURCE}"],
            check,
            label="stub + hybrid, gate off",
        ),
        "control_pooled": control_from(
            results, check, label="stub + all arms, gate off (pooled)"
        ),
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="run the sweep")
    parser.add_argument(
        "--plan", action="store_true", help="print the query set; no model call"
    )
    parser.add_argument(
        "--arms", default=",".join(GENERATING_ARMS), help="comma-separated arm names"
    )
    parser.add_argument("--per-category", type=int, default=REQUESTS_PER_CATEGORY)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--remembered-only",
        action="store_true",
        help="run only the free stub controls and merge them into results.json",
    )
    args = parser.parse_args(argv)

    queries = query_set(args.per_category)
    if args.plan or not args.run:
        for query in queries:
            print(f"{query.label:<6} {query.concept}\n       {query.question_type}")
        print(
            f"\n{len(queries)} queries x {len(args.arms.split(','))} generating arms "
            f"= {len(queries) * len(args.arms.split(','))} generation calls"
        )
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]
    started = time.time()

    if args.remembered_only:
        # Merge the free controls into an existing results.json rather than
        # re-running 54 paid calls to recompute numbers that did not change.
        report = json.loads(RESULTS.read_text(encoding="utf-8"))
        report["remembered"] = remembered_controls(arm_names, CorpusWideCheck())
        RESULTS.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        block = report["remembered"]["control_pooled"]
        print(
            f"\n{block['arm']}: ships {block['ungated_shipped']}/{block['attempts']}; "
            f"{block['unsupported_in_retrieved']} "
            f"({block['unsupported_rate_of_shipped']}%) unsupported in the retrieved "
            f"passages, {block['absent_from_corpus']} "
            f"({block['absent_rate_of_shipped']}%) absent from the corpus entirely."
        )
        print(f"\nwrote {RESULTS}")
        return 0

    results: list[dict[str, Any]] = []
    for arm in arm_names:
        print(f"\n=== arm: {arm} ===", flush=True)
        results.append(run_arm(arm, queries, workers=args.workers))

    summaries = [summarise(result) for result in results]
    check = CorpusWideCheck()
    control = next(
        (
            control_from(result, check, label="hybrid, gate off (control)")
            for result in results
            if result["arm"] == CONTROL_SOURCE
        ),
        None,
    )
    pooled = (
        control_from(results, check, label="all arms, gate off (pooled)")
        if len(results) > 1
        else None
    )
    report = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - started, 1),
        "query_set": {
            "categories": bio_categories(),
            "requests_per_category": args.per_category,
            "queries": len(queries),
            "queries_detail": [
                {
                    "topic": q.topic_id,
                    "index": q.index,
                    "concept": q.concept,
                    "question_type": q.question_type,
                }
                for q in queries
            ],
        },
        "fixed": {
            "gate": "speedrun_agent.gate.rule (unmodified)",
            "generator_model": generators.OPENAI_MODEL,
            "max_output_tokens": 8000,
            "chunks_retrieved": 8,
            "chunks_shown_to_model": 4,
            "embedding_model": EMBEDDING_MODEL,
            "fusion": f"RRF k={RRF_K}, depth={FUSION_DEPTH} per ranking",
        },
        "arms": summaries,
        "control": control,
        "control_pooled": pooled,
        "remembered": remembered_controls(arm_names, check),
    }
    RESULTS.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 68)
    for summary in summaries:
        ci = summary["yield_ci95"]
        print(
            f"{summary['arm']:<12} yield {summary['yield_per_hundred']:>5}/100 "
            f"(95% CI {ci[0]}-{ci[1]})  shipped {summary['shipped']}/"
            f"{summary['attempts']}  distinct {summary['distinct_shipped']}  "
            f"${summary['usage']['usd']}"
        )
    for block in (control, pooled):
        if block:
            print(
                f"\n{block['arm']}: ships {block['ungated_shipped']}/"
                f"{block['attempts']} attempts; of those, "
                f"{block['unsupported_in_retrieved']} "
                f"({block['unsupported_rate_of_shipped']}%) have an answer that is "
                f"in none of the passages the model was shown, and "
                f"{block['absent_from_corpus']} ({block['absent_rate_of_shipped']}%) "
                f"have one that appears on no indexed page at all."
            )
    print(f"\nwrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

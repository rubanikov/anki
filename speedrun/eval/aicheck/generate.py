#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two arms over the same 50 requests: the gate on, and the gate off.

The manifest's third cutoff condition compares "the gated arm's wrong rate" with
"the ungated arm's wrong rate **on the same source and the same 50 generation
requests**". So exactly one thing differs between the two runs here, and it is
the gate:

|  | gated | ungated |
|---|---|---|
| target list | `plan.targets()` | the same 50 |
| retrieval | BM25, concept query, category filter | identical, and deterministic |
| prompt | the service's, plus the P-set addendum | byte-identical |
| model | `gpt-5` via the service's `OpenAIGenerator` | the same |
| the gate | `speedrun_agent.gate.rule` | replaced |

**What "the gate off" means, precisely.** ADR-0006 says the ungated control
"measures how often an ungated pipeline would have shipped an item whose answer
is in no real source". An ungated pipeline still cites something — it cites the
passage it retrieved, and simply never checks that the answer is in it. So the
ungated arm here ships every well-formed proposal with the top retrieved chunk
as its citation, unverified. That is the naive RAG behaviour the gate replaces,
not a strawman that cites nothing.

Everything upstream of the gate is untouched, including the two checks the
*generate* node makes (a malformed proposal, and a stem containing its own
answer). Those belong to the generator node, not to the gate, so moving them
would make the comparison about something other than the gate.

**A paired number is recorded as well as the two arms.** Two separate runs of a
non-deterministic model produce two different sets of items, so a difference in
their wrong rates carries call-to-call noise as well as the gate's effect. Every
item in both arms therefore also records `answer_in_retrieved` — whether the
real gate's span matcher can find the answer in that item's own retrieved
chunks. Applying that to the ungated arm's own proposals is the gate's filtering
effect with the noise removed, and it costs no extra call.

Usage (from the repo root, with the agent's own interpreter):

    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/generate.py --arm gated
    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/generate.py --arm ungated
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

AICHECK_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = AICHECK_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
OUT_DIR = AICHECK_DIR / "out"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(CORPUS_DIR))
sys.path.insert(0, str(AICHECK_DIR))

import plan  # noqa: E402
from speedrun_agent import generators  # noqa: E402
from speedrun_agent.attribution import SpanRef, all_from, latest, payload  # noqa: E402
from speedrun_agent.corpus_gateway import Bm25Corpus, RetrievedChunk, spans_module  # noqa: E402
from speedrun_agent.gate import Ruling  # noqa: E402
from speedrun_agent.generators import OpenAIGenerator  # noqa: E402
from speedrun_agent.graph import GATE, RETRIEVE, Request, build_graph  # noqa: E402
from speedrun_agent.rejections import AttemptLog, Reason  # noqa: E402
from speedrun_agent.tracing import LocalTracer  # noqa: E402

ARMS = ("gated", "ungated")

#: The P-set's addendum, unchanged. Kept identical so the two arms differ only in
#: the gate, and so these items are drafted under the same instructions the last
#: hand-read batch was — the failure modes `pset/QUALITY.md` found are the ones
#: this run is expecting to see again.
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
    """Stands in for `generators.PROMPT` so each attempt carries its own.

    The same device the P-set driver uses, and for the same reason: the addendum
    has to reach one attempt's model call and no other thread's, without editing
    `speedrun/agent/`, which this ticket does not own.
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


class ConceptQueryCorpus:
    """The real corpus, asked for the target's concept instead of the Topic query.

    See `plan.query_for` for why the Outline query is not prepended. Retrieval,
    matching and page text all remain the corpus package's; only the query
    string is this ticket's.
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
        return self._inner.retrieve(concept or query, limit=limit, categories=categories)

    def page_text(self, source_id: str) -> str:
        return self._inner.page_text(source_id)

    def stats(self) -> dict[str, Any]:
        return self._inner.stats()

    def close(self) -> None:
        self._inner.close()


def ungated_rule(
    retrieved: Any, answer: str, page_text: Any
) -> Ruling:
    """Ship whatever was proposed, citing the top retrieved chunk. No assertion.

    This is the control arm. It does not check that `answer` occurs in
    `retrieved`; it hands back the chunk retrieval ranked first, which is what a
    pipeline without a gate cites. `NO_RETRIEVAL` is still a drop, because an
    arm that cites nothing at all is not an ungated arm, it is a broken one.
    """
    if not retrieved:
        return Ruling.drop(Reason.NO_RETRIEVAL, "retrieval returned no chunks")
    top = retrieved[0]
    return Ruling.ship(
        SpanRef(
            source_id=top.source_id,
            chunk_id=top.chunk_id,
            start=top.char_start,
            end=top.char_end,
            # The chunk's own text, truncated: this is the passage the pipeline
            # points at, not evidence that the answer is inside it.
            quote=top.text[:200],
            block_id=None,
            url=top.url,
        )
    )


def answer_in_retrieved(chunks: list[RetrievedChunk], answer: str) -> bool:
    """Would the real gate have found this answer? Asked of both arms.

    For the gated arm this is true by construction and is recorded anyway, so
    the column means the same thing in both files.
    """
    spans = spans_module()
    return spans.support_for([chunk.chunk for chunk in chunks], answer) is not None


def _sha256(text: str) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_record(
    *,
    arm: str,
    target: plan.Target,
    shipped: dict[str, Any],
    attempt_id: str,
    prompt: str,
    grounded: bool,
    chunks: list[RetrievedChunk],
) -> dict[str, Any]:
    body = shipped["item"]
    span = dict(shipped["span"])
    return {
        "id": f"{arm[0]}{target.index:02d}",
        "arm": arm,
        "target_index": target.index,
        "gold_id": target.gold_id,
        "topic": target.topic_id,
        "target_concept": target.concept,
        "question_type": target.question_type,
        "stem": body["stem"],
        "answer": body["answer"],
        "distractors": list(body["distractors"]),
        "source_id": shipped["source_id"],
        "citation": shipped["citation"],
        "span": span,
        # The gate's own question, asked of every item in both arms. In the
        # ungated arm nothing acted on the answer; the column is the paired
        # measurement of what the gate would have done.
        "answer_in_retrieved": grounded,
        "citation_verified": arm == "gated",
        "retrieved": [chunk.chunk_id for chunk in chunks],
        "generator": body["generator"],
        "model": body["model"],
        "attempt_id": attempt_id,
        "prompt_sha256": _sha256(prompt),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def run(arm: str, targets: list[plan.Target], workers: int) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items_path = OUT_DIR / f"{arm}.jsonl"
    log_path = OUT_DIR / f"{arm}_run_log.jsonl"

    prompt = _PerThreadPrompt(generators.PROMPT)
    generators.PROMPT = prompt  # type: ignore[assignment]

    corpus = ConceptQueryCorpus(Bm25Corpus.open())
    # 8000 rather than the constructor's 4000, for the reason the P-set driver
    # records: a truncated response is counted as `generator_empty`, which would
    # be a token-budget artefact masquerading as a generator declining.
    generator = OpenAIGenerator(max_output_tokens=8000)
    log = AttemptLog(OUT_DIR / f"{arm}_attempts.jsonl")
    tracer = LocalTracer(OUT_DIR / f"{arm}_trace.jsonl")
    graph = build_graph(
        corpus=corpus,
        generator=generator,
        log=log,
        tracer=tracer,
        gate_rule=None if arm == "gated" else ungated_rule,
    )

    lock = threading.Lock()

    def one(target: plan.Target) -> dict[str, Any]:
        started = time.time()
        corpus.steer(target.concept)
        prompt.use(
            ADDENDUM.format(
                concept=target.concept, question_type=target.question_type
            )
        )
        used = prompt.current
        request = Request(topic_id=target.topic_id, seed=target.index)
        row: dict[str, Any] = {
            "arm": arm,
            "target_index": target.index,
            "gold_id": target.gold_id,
            "topic": target.topic_id,
            "target_concept": target.concept,
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
        chunks = [c.output for c in all_from(state.get("trail", []), RETRIEVE)]
        shipped = payload(latest(state.get("trail", []), GATE))
        if shipped is None:
            ruling = state.get("rejection")
            row |= {
                "outcome": "dropped",
                "reason": str(ruling.reason) if ruling else "unattributed_output",
                "detail": (ruling.detail if ruling else "")[:300],
            }
            return row

        record = item_record(
            arm=arm,
            target=target,
            shipped=shipped,
            attempt_id=request.attempt_id,
            prompt=used,
            grounded=answer_in_retrieved(chunks, shipped["item"]["answer"]),
            chunks=chunks,
        )
        with lock:
            with items_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        row |= {
            "outcome": "shipped",
            "item_id": record["id"],
            "answer": record["answer"],
            "answer_in_retrieved": record["answer_in_retrieved"],
        }
        return row

    shipped_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(one, targets):
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            shipped_count += row["outcome"] == "shipped"
            print(
                f"  {row['gold_id']:<10} {row['outcome']:<9} "
                f"{str(row.get('reason', '')):<30} {str(row.get('answer', ''))[:52]}"
            )

    print(f"\narm={arm}  attempts {len(targets)}  shipped {shipped_count}")
    print(f"gate tally: {json.dumps(log.tally(), ensure_ascii=False)}")
    corpus.close()
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    return run(args.arm, plan.targets(), workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The 50 targets for T-18, and the passages behind them. One rule, no hand-picking.

H3's manifest fixes what the gold set is — 50 question/answer pairs drawn by hand
from **one** source — and the cutoff compares gated and ungated generation on
"the same 50 generation requests". So one target list serves three jobs:

  1. the 50 gold pairs are authored against target *i*'s passages,
  2. the gated arm's request *i* asks for a card about target *i*,
  3. the ungated arm's request *i* asks the same thing.

A target is `(topic_id, concept)`. The concepts come from the AAMC Outline's own
itemised topic list (`corpus/outline.json`), picked by the same evenly-spaced
rule the P-set driver uses, so the plan is reproducible and was not chosen to
flatter anything: `--plan` prints it without touching a model or a key.

**Why 50 splits the way it does.** Five per Bio/Biochem category is 45; the
remaining five go to the five categories with the most indexed chunks
(`corpus/out/build_report.json`), because a category with 31 chunks cannot
support six distinct questions and one with 440 can. The counts are read from
the build report rather than typed in, so the split follows the corpus.

Usage (from the repo root, with the agent's own interpreter):

    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/plan.py --plan
    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/plan.py --passages
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AICHECK_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = AICHECK_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
BUILD_REPORT = CORPUS_DIR / "out" / "build_report.json"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(CORPUS_DIR))

#: Total targets. Fixed by the manifest: H3 is 50 pairs and the cutoff is stated
#: out of 50.
TARGETS = 50

#: Four question forms, rotated across a category's targets. Same four the P-set
#: driver uses — copied rather than imported, because `speedrun/eval/pset/` is
#: another ticket's directory and a shared import would couple two artifacts.
QUESTION_TYPES: tuple[str, ...] = (
    "an identification question - name the structure, molecule or term the "
    "passage describes",
    "a function question - what the named thing does, or what it is for",
    "a mechanism question - what happens at a specific step, or what causes what",
    "a discrimination question - which of two similar things the described case is",
)

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


def demo_section_topics() -> list[str]:
    """The nine Bio/Biochem categories — the only section this corpus indexes."""
    return [category.id for category in _outline().in_section("BB")]


def per_topic_counts() -> dict[str, int]:
    """How many of the 50 each category gets, derived from the corpus's own report.

    Base share to everyone, remainder to the categories with the most indexed
    chunks. Stated as a rule so nobody has to take a hand-typed table's word for
    it, and so the split moves if the corpus does.
    """
    topics = demo_section_topics()
    chunks = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))["chunks_per_category"]
    base, remainder = divmod(TARGETS, len(topics))
    counts = {topic: base for topic in topics}
    ranked = sorted(topics, key=lambda t: (-chunks.get(t, 0), t))
    for topic in ranked[:remainder]:
        counts[topic] += 1
    return counts


def concepts_for(topic_id: str, count: int) -> list[str]:
    """`count` target concepts for a category, spread across the Outline's list.

    Keep the lines that read as concepts rather than headings, then take `count`
    of them at evenly spaced positions — (2i+1)/2n through the list — so the
    targets for one category land in different corners of it instead of six times
    in its first paragraph.
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
class Target:
    index: int
    topic_id: str
    within_topic: int
    concept: str
    question_type: str

    @property
    def gold_id(self) -> str:
        return f"h3-{self.topic_id}-{self.within_topic + 1:02d}"


def targets() -> list[Target]:
    counts = per_topic_counts()
    out: list[Target] = []
    for topic_id in demo_section_topics():
        for within, concept in enumerate(concepts_for(topic_id, counts[topic_id])):
            out.append(
                Target(
                    index=len(out),
                    topic_id=topic_id,
                    within_topic=within,
                    concept=concept,
                    question_type=QUESTION_TYPES[within % len(QUESTION_TYPES)],
                )
            )
    return out


# --------------------------------------------------------------------------
# Retrieval, so the same passages back the gold pair and the generated card
# --------------------------------------------------------------------------


def query_for(target: Target) -> str:
    """The concept, alone, with the category filter doing the rest.

    Identical to what the generation arms send, so the passages a gold pair was
    written from are the passages the model is handed. That is the whole point of
    "the same source": if the two saw different text, a disagreement between them
    would be a retrieval finding wearing a grading finding's clothes.

    **Why the Outline query is not prepended, unlike the P-set driver.** It was,
    first, and it collapsed the plan: `"<concept> <Outline query>"` returned the
    same top chunk for 50 targets down to **14 distinct chunks**, because the
    Outline query is dozens of the category's own terms and outweighs a
    three-word concept in BM25's scoring. The concept alone returns **49 distinct
    top chunks out of 50**. Fifty targets that read the same two passages are not
    fifty targets, and a gold set built that way could not tell a good generator
    from a repetitive one. Both numbers are from `--distinctness`, so the choice
    is checkable rather than asserted.
    """
    return target.concept.strip()


def passages(limit: int = 2, chars: int = 1400) -> list[dict[str, Any]]:
    from speedrun_agent.corpus_gateway import Bm25Corpus  # noqa: PLC0415

    corpus = Bm25Corpus.open()
    try:
        out = []
        for target in targets():
            hits = corpus.retrieve(
                query_for(target), limit=limit, categories=(target.topic_id,)
            )
            out.append(
                asdict(target)
                | {
                    "gold_id": target.gold_id,
                    "passages": [
                        {
                            "chunk_id": hit.chunk_id,
                            "source_id": hit.source_id,
                            "page_title": hit.page_title,
                            "text": hit.text[:chars],
                        }
                        for hit in hits
                    ],
                }
            )
        return out
    finally:
        corpus.close()


def _distinctness(limit: int) -> int:
    """The number behind `query_for`'s docstring, re-runnable by anyone."""
    from speedrun_agent import topics  # noqa: PLC0415
    from speedrun_agent.corpus_gateway import Bm25Corpus  # noqa: PLC0415

    corpus = Bm25Corpus.open()
    try:
        for label, build in (
            ("concept alone (used)", lambda t: t.concept),
            (
                "concept + Outline query (rejected)",
                lambda t: f"{t.concept} {topics.query_for(t.topic_id)}",
            ),
        ):
            tops, alls = set(), set()
            for target in targets():
                hits = corpus.retrieve(
                    build(target), limit=limit, categories=(target.topic_id,)
                )
                if hits:
                    tops.add(hits[0].chunk_id)
                alls.update(hit.chunk_id for hit in hits)
            print(
                f"{label:<36} distinct top chunk: {len(tops):>2}/{len(targets())}   "
                f"distinct in top {limit}: {len(alls)}"
            )
    finally:
        corpus.close()
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", action="store_true", help="print the 50 targets")
    parser.add_argument(
        "--passages", action="store_true", help="print the targets with their passages"
    )
    parser.add_argument(
        "--distinctness",
        action="store_true",
        help="how many distinct chunks the plan reaches, per query form",
    )
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--chars", type=int, default=1400)
    args = parser.parse_args(argv)

    if args.distinctness:
        return _distinctness(args.limit)
    if args.passages:
        for row in passages(limit=args.limit, chars=args.chars):
            print(json.dumps(row, ensure_ascii=False))
        return 0

    counts = per_topic_counts()
    for target in targets():
        print(f"{target.index:2d}  {target.gold_id}  {target.concept}")
        print(f"     {target.question_type}")
    print(f"\n{len(targets())} targets; per category {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

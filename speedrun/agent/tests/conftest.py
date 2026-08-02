# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two hand-written corpora, and nothing that reaches past the HTTP boundary.

The corpora are built from short pages through the real chunker, sanitizer and
index, so the gate is matching against the same machinery it will use in
production — but no download and no built index file are needed, and the suite
runs on a checkout with an empty `corpus/out/`.

`SUPPORTING` states the answer in the corpus's own words. `SILENT` is the same
page with that one sentence replaced by prose that says something else about the
same topic — the corpus a generator would be tempted by and the gate must refuse.
The only difference between the two fixtures is whether a real source contains
the claim, which is precisely the difference the gate is supposed to notice.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = AGENT_DIR.parent / "corpus"
sys.path.insert(0, str(CORPUS_DIR))

from speedrun_agent.corpus_gateway import Bm25Corpus, ThreadConfinedCorpus  # noqa: E402
from speedrun_agent.generators import Candidate, FixedClaimGenerator  # noqa: E402

TOPIC = "1D"

#: Contains the answer, verbatim, in the source's own characters.
SUPPORTING = """
<html><body><div data-type="page">
  <h2 id="t">7.2 Glycolysis</h2>
  <p id="p1">Glycolysis is the first pathway used in the breakdown of glucose to
     extract energy. It takes place in the cytoplasm of both prokaryotic and
     eukaryotic cells.</p>
  <p id="p2">If oxygen is present, pyruvate enters the mitochondrion, where the
     citric acid cycle oxidizes it completely to carbon dioxide.</p>
</div></body></html>
"""

#: The same topic, retrievable by the same query, with the claim absent. Not an
#: empty corpus — an empty corpus would be caught by retrieval, and retrieval is
#: not the thing under test.
SILENT = """
<html><body><div data-type="page">
  <h2 id="t">7.2 Glycolysis</h2>
  <p id="p1">Glycolysis is the first pathway used in the breakdown of glucose to
     extract energy. It takes place in the cytoplasm of both prokaryotic and
     eukaryotic cells.</p>
  <p id="p2">The pathway is regulated at several steps, and its intermediates
     feed other routes of metabolism in ways this section does not enumerate.</p>
</div></body></html>
"""

ANSWER = "citric acid cycle"
STEM = "Which pathway oxidizes pyruvate completely to carbon dioxide?"


def _build(markup: str) -> Bm25Corpus:
    import chunker
    import sanitize
    from attribution import Attribution
    from index import CorpusIndex

    page = chunker.chunk_page("page-7-2", sanitize.parse_page(markup))
    index = CorpusIndex.in_memory()
    index.add_page(
        page,
        book_id="fixture",
        slug="7-2-glycolysis",
        title="Glycolysis",
        url="https://example.invalid/7-2",
        attribution={
            chunk.chunk_id: Attribution(
                categories=(TOPIC,), confidence="high", rule="fixture"
            )
            for chunk in page.chunks
        },
    )
    index.commit()
    return Bm25Corpus(index)


def _corpus(markup: str) -> ThreadConfinedCorpus:
    # Built through the same confinement the service uses, so the fixture is
    # not quietly exercising a different threading story than production.
    return ThreadConfinedCorpus(lambda: _build(markup))


@pytest.fixture
def supporting_corpus() -> Any:
    return _corpus(SUPPORTING)


@pytest.fixture
def silent_corpus() -> Any:
    return _corpus(SILENT)


@pytest.fixture
def claiming_generator() -> FixedClaimGenerator:
    """Proposes the same claim regardless of what retrieval returned.

    This is what a model does — it answers from what it absorbed, not from the
    passage in front of it — and it is what makes the two corpora a fair test:
    the generator is held constant and only the source varies.
    """
    return FixedClaimGenerator(
        Candidate(
            stem=STEM,
            answer=ANSWER,
            distractors=("the Calvin cycle", "the urea cycle", "beta oxidation"),
            topic_id=TOPIC,
            generator="fixed-claim",
        )
    )

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Retrieval has to hand back a citation, not a paragraph.

The gate's whole claim rests on being able to point at where an answer's support
lives and have someone else check it. So these tests care about two things: that
a hit carries offsets which still address the right characters after a round
trip through SQLite, and that `support` says nothing at all when the corpus does
not contain the answer.

Built on a small hand-written page rather than the real book, so the suite runs
without a download and without the ignored index file.
"""

from __future__ import annotations

import pytest

import chunker
import sanitize
import spans
from attribution import Attribution
from index import CorpusIndex

PAGE = """
<html><body><div data-type="page">
  <h2 id="t">7.2 Glycolysis</h2>
  <p id="p1">Glycolysis is the first pathway used in the breakdown of glucose to
     extract energy. It takes place in the cytoplasm of both prokaryotic and
     eukaryotic cells, and it was probably one of the earliest metabolic
     pathways to evolve. Glycolysis consists of two parts: the first part
     prepares the six-carbon ring of glucose for cleavage into two three-carbon
     sugars, and the second part extracts energy from those sugars.</p>
  <p id="p2">The net yield of glycolysis is two molecules of ATP and two
     molecules of NADH per molecule of glucose. Because two ATP were invested in
     the first half of the pathway, the gross yield of four ATP becomes a net
     yield of two.</p>
  <h3 id="t2">Anaerobic respiration</h3>
  <p id="p3">If oxygen is not available, pyruvate is reduced rather than
     entering the citric acid cycle, and the cell relies on fermentation to
     regenerate NAD+ so that glycolysis can continue.</p>
</div></body></html>
"""


@pytest.fixture(scope="module")
def page():
    return chunker.chunk_page("page-7-2", sanitize.parse_page(PAGE))


@pytest.fixture(scope="module")
def corpus(page):
    index = CorpusIndex.in_memory()
    index.add_page(
        page,
        book_id="openstax-biology-1e",
        slug="7-2-glycolysis",
        title="Glycolysis",
        chapter="7",
        section="7.2",
        url="https://openstax.org/books/biology/pages/7-2-glycolysis",
        attribution={
            chunk.chunk_id: Attribution(("1D",), "high", "7.2", "1D: glycolysis")
            for chunk in page.chunks
        },
    )
    index.commit()
    return index


def test_the_index_is_queryable(corpus):
    hits = corpus.search("glycolysis net yield ATP")
    assert hits
    assert "net yield" in hits[0].text


def test_a_hit_carries_its_category_attribution(corpus):
    hit = corpus.search("glycolysis")[0]
    assert hit.categories == ("1D",)
    assert hit.confidence == "high"


def test_a_category_filter_narrows_rather_than_reinterprets(corpus):
    assert corpus.search("glycolysis", categories=("1D",))
    assert corpus.search("glycolysis", categories=("3B",)) == []


def test_offsets_survive_the_round_trip_through_sqlite(corpus, page):
    for hit in corpus.search("glycolysis pyruvate ATP", limit=10):
        stored = corpus.page_text(hit.source_id)
        assert stored[hit.chunk.char_start : hit.chunk.char_end] == hit.text


def test_support_returns_a_span_that_verifies(corpus, page):
    span = corpus.support("two molecules of ATP and two molecules of NADH")
    assert span is not None
    assert spans.verify(span, corpus.page_text(span.source_id))
    assert span.block_id == "p2"


def test_support_is_whitespace_and_case_insensitive(corpus):
    assert corpus.support("TWO   MOLECULES   of atp") is not None


def test_support_is_none_when_the_corpus_does_not_say_it(corpus):
    assert corpus.support("Glycolysis takes place inside the mitochondrial matrix") is None


def test_support_does_not_settle_for_a_near_match(corpus):
    """The words are all present in the page; the sentence is not."""
    assert corpus.support("Glycolysis yields four molecules of NADH per glucose") is None


def test_an_empty_query_retrieves_nothing(corpus):
    assert corpus.search("   ") == []


def test_a_span_does_not_verify_against_another_page(corpus, page):
    span = corpus.support("pyruvate is reduced")
    assert span is not None
    assert not spans.verify(span, "some other page entirely")


def test_stats_report_what_is_in_there(corpus):
    stats = corpus.stats()
    assert stats["pages"] == 1
    assert stats["chunks"] >= 1
    assert stats["chunks_by_category"]["1D"] == stats["chunks"]


def test_every_chunk_is_a_whole_number_of_blocks(page):
    for chunk in page.chunks:
        assert chunk.blocks
        assert chunk.blocks[0].start == chunk.char_start
        assert chunk.blocks[-1].end == chunk.char_end


def test_heading_path_follows_the_document(page):
    last = page.chunks[-1]
    assert "Anaerobic respiration" in last.heading_path[-1]

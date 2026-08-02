# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Reaching the corpus without owning it.

`speedrun/corpus/` is a stdlib-only set of scripts run from a checkout, with no
importable dotted name — the same arrangement its own tests use. This module is
the single place that puts it on `sys.path`, so exactly one file knows where the
corpus lives and nothing else in the service imports by relative path.

Nothing here re-implements retrieval or matching. The corpus decides what a
supporting span is; this service decides what to do when there isn't one. Those
are different jobs and they stay in different repositories' worth of code.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any, Protocol

#: speedrun/agent/speedrun_agent/ -> speedrun/corpus/
CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
DEFAULT_INDEX = CORPUS_DIR / "out" / "index.sqlite3"


def ensure_on_path() -> None:
    directory = str(CORPUS_DIR)
    if directory not in sys.path:
        sys.path.insert(0, directory)


def spans_module() -> Any:
    """`corpus.spans` — the module that locates a supporting span, or None."""
    ensure_on_path()
    import spans  # noqa: PLC0415

    return spans


def index_module() -> Any:
    ensure_on_path()
    import index  # noqa: PLC0415

    return index


@dataclasses.dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved chunk, decoupled from the corpus's own `Hit` type.

    The chunk itself is kept because the gate matches against it, but the
    service's own code paths only ever read the named fields — so a change to
    the corpus's `Hit` shape breaks here, once, instead of everywhere.
    """

    chunk: Any
    chunk_id: str
    source_id: str
    text: str
    char_start: int
    char_end: int
    page_title: str
    url: str
    categories: tuple[str, ...]
    score: float

    @classmethod
    def of(cls, hit: Any) -> RetrievedChunk:
        return cls(
            chunk=hit.chunk,
            chunk_id=hit.chunk.chunk_id,
            source_id=hit.chunk.source_id,
            text=hit.chunk.text,
            char_start=hit.chunk.char_start,
            char_end=hit.chunk.char_end,
            page_title=hit.page_title,
            url=hit.url,
            categories=tuple(hit.categories),
            score=hit.score,
        )


class Corpus(Protocol):
    """What the graph needs from a corpus, and nothing more.

    Narrow on purpose: a test corpus is three methods, and the retrieval arms of
    ADR-0006 can be swapped in behind the same three without the gate noticing.
    """

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]: ...

    def page_text(self, source_id: str) -> str: ...

    def stats(self) -> dict[str, Any]: ...


class ThreadConfinedCorpus:
    """Runs one corpus on one thread, because SQLite connections belong to one.

    Uvicorn dispatches synchronous handlers onto a threadpool, so a connection
    opened at startup would be used from whichever worker took the request —
    which `sqlite3` refuses, correctly. Rather than reach into `CorpusIndex` and
    relax `check_same_thread`, the connection is *built* on a dedicated thread
    and every call is marshalled onto it. The confinement is real instead of
    disabled, and the corpus package keeps its own safety check.

    A single worker also serialises reads, which is what an FTS5 index over one
    file wants anyway. The service is a local single-user process; contention is
    not the constraint.
    """

    def __init__(self, factory: Any) -> None:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="corpus")
        self._inner = self._on_thread(factory)

    def _on_thread(self, call: Any, *args: Any, **kwargs: Any) -> Any:
        return self._pool.submit(call, *args, **kwargs).result()

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "unknown")

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]:
        return self._on_thread(
            self._inner.retrieve, query, limit=limit, categories=categories
        )

    def page_text(self, source_id: str) -> str:
        return self._on_thread(self._inner.page_text, source_id)

    def stats(self) -> dict[str, Any]:
        return self._on_thread(self._inner.stats)

    def close(self) -> None:
        self._on_thread(self._inner.close)
        self._pool.shutdown(wait=True)


class Bm25Corpus:
    """The incumbent: BM25 over SQLite FTS5, exactly as `corpus/index.py` built it.

    Deliberately the baseline rather than an aspiration. ADR-0006 judges
    retrieval by Yield at a fixed gate, and a comparison needs an incumbent that
    might win — dense prose full of exact technical terms is the case where BM25
    often does.
    """

    name = "bm25-fts5"

    def __init__(self, index: Any) -> None:
        self._index = index

    @classmethod
    def open(cls, path: Path | str | None = None) -> ThreadConfinedCorpus:
        target = Path(path) if path else DEFAULT_INDEX
        return ThreadConfinedCorpus(
            lambda: cls(index_module().CorpusIndex.open(target))
        )

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]:
        hits = self._index.search(query, limit=limit, categories=categories)
        return [RetrievedChunk.of(hit) for hit in hits]

    def page_text(self, source_id: str) -> str:
        return self._index.page_text(source_id)

    def stats(self) -> dict[str, Any]:
        raw = self._index.stats()
        return {
            "retriever": self.name,
            "pages": raw["pages"],
            "chunks": raw["chunks"],
            "chunks_attributed": raw["chunks_attributed"],
        }

    def close(self) -> None:
        self._index.close()

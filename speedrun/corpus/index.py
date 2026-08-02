# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The queryable index: SQLite with FTS5, and nothing else.

Retrieval here is BM25 over full text. That is a deliberate floor, not an
aspiration: ADR-0006 says retrieval is judged by Yield at a fixed gate, and a
comparison needs something to beat. An embedding retriever can be added later
and measured against this on the same gate; until it is measured, this is the
one that ships.

The store is a single file, rebuilt by `build.py` and never committed. It holds
the page text as well as the chunks, because a span that cannot be re-checked
against its page is a claim rather than evidence, and the checker should not
have to go back to the network to do it.

Every hit carries its page offsets, so callers get a citation rather than a
paragraph of unknown provenance. `support` is the whole retrieval-to-gate path
in one call, and it returns None rather than a best guess.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from pathlib import Path

import spans
from chunker import BlockSpan, Chunk, ChunkedPage

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS page (
    source_id  TEXT PRIMARY KEY,
    book_id    TEXT NOT NULL,
    slug       TEXT,
    title      TEXT,
    chapter    TEXT,
    section    TEXT,
    url        TEXT,
    text       TEXT NOT NULL,
    sha256     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk (
    chunk_id      TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES page(source_id),
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    text          TEXT NOT NULL,
    blocks_json   TEXT NOT NULL,
    heading_path  TEXT NOT NULL,
    categories    TEXT NOT NULL,
    confidence    TEXT NOT NULL,
    rule          TEXT
);
CREATE INDEX IF NOT EXISTS chunk_by_page ON chunk(source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    text,
    content='chunk',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS quarantine (
    source_id TEXT NOT NULL,
    block_id  TEXT,
    kind      TEXT NOT NULL,
    finding   TEXT NOT NULL,
    excerpt   TEXT NOT NULL
);
"""

_TOKEN = re.compile(r"[0-9A-Za-z]+")


@dataclasses.dataclass(frozen=True)
class Hit:
    """One retrieved chunk, with everything needed to locate a span in it."""

    chunk: Chunk
    score: float
    page_title: str
    url: str
    categories: tuple[str, ...]
    confidence: str

    @property
    def text(self) -> str:
        return self.chunk.text

    @property
    def source_id(self) -> str:
        return self.chunk.source_id


class CorpusIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        self._db.row_factory = sqlite3.Row

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, path: Path | str) -> CorpusIndex:
        path = Path(path)
        if path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path))
        db.executescript(_SCHEMA)
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        return cls(db)

    @classmethod
    def in_memory(cls) -> CorpusIndex:
        db = sqlite3.connect(":memory:")
        db.executescript(_SCHEMA)
        return cls(db)

    @classmethod
    def open(cls, path: Path | str) -> CorpusIndex:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"no corpus index at {path}. Build it with "
                f"`python speedrun/corpus/build.py --all`."
            )
        return cls(sqlite3.connect(f"file:{path}?mode=ro", uri=True))

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> CorpusIndex:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- writing -----------------------------------------------------------

    def set_meta(self, **values: object) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in values.items()],
        )

    def add_page(
        self,
        page: ChunkedPage,
        *,
        book_id: str,
        slug: str = "",
        title: str = "",
        chapter: str = "",
        section: str = "",
        url: str = "",
        attribution=None,
    ) -> None:
        """Store one chunked page. `attribution` maps chunk_id -> Attribution."""
        self._db.execute(
            "INSERT OR REPLACE INTO page"
            " (source_id, book_id, slug, title, chapter, section, url, text, sha256)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                page.source_id,
                book_id,
                slug,
                title,
                chapter,
                section,
                url,
                page.page_text,
                page.page_sha256,
            ),
        )
        for chunk in page.chunks:
            attributed = (attribution or {}).get(chunk.chunk_id)
            categories = list(getattr(attributed, "categories", ()) or ())
            cursor = self._db.execute(
                "INSERT OR REPLACE INTO chunk"
                " (chunk_id, source_id, char_start, char_end, text, blocks_json,"
                "  heading_path, categories, confidence, rule)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.text,
                    json.dumps([dataclasses.asdict(b) for b in chunk.blocks]),
                    json.dumps(list(chunk.heading_path)),
                    json.dumps(categories),
                    getattr(attributed, "confidence", "unattributed"),
                    getattr(attributed, "rule", None),
                ),
            )
            self._db.execute(
                "INSERT INTO chunk_fts(rowid, text) VALUES (?, ?)",
                (cursor.lastrowid, chunk.text),
            )
        for refused in page.quarantined:
            self._db.execute(
                "INSERT INTO quarantine(source_id, block_id, kind, finding, excerpt)"
                " VALUES (?,?,?,?,?)",
                (
                    refused.source_id,
                    refused.block_id,
                    refused.kind,
                    refused.finding,
                    refused.excerpt,
                ),
            )

    def commit(self) -> None:
        self._db.commit()

    # -- reading -----------------------------------------------------------

    @staticmethod
    def _match_expression(query: str) -> str:
        tokens = _TOKEN.findall(query)
        if not tokens:
            return ""
        return " OR ".join(f'"{token}"' for token in tokens)

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        categories: tuple[str, ...] | None = None,
    ) -> list[Hit]:
        """Best `limit` chunks for `query`, optionally restricted to Topics.

        Restricting by category only ever narrows to chunks that carry an
        attribution; a chunk we could not attribute honestly is not silently
        swept into whichever Topic was asked for.
        """
        match = self._match_expression(query)
        if not match:
            return []
        sql = [
            "SELECT c.*, p.title AS page_title, p.url AS url,",
            "       bm25(chunk_fts) AS score",
            "  FROM chunk_fts",
            "  JOIN chunk c ON c.rowid = chunk_fts.rowid",
            "  JOIN page  p ON p.source_id = c.source_id",
            " WHERE chunk_fts MATCH ?",
        ]
        params: list[object] = [match]
        if categories:
            clauses = " OR ".join(["c.categories LIKE ?"] * len(categories))
            sql.append(f"   AND ({clauses})")
            params.extend(f'%"{category}"%' for category in categories)
        sql.append(" ORDER BY score LIMIT ?")
        params.append(limit)
        rows = self._db.execute("\n".join(sql), params).fetchall()
        return [self._hit(row) for row in rows]

    @staticmethod
    def _hit(row: sqlite3.Row) -> Hit:
        chunk = Chunk(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            text=row["text"],
            blocks=tuple(BlockSpan(**b) for b in json.loads(row["blocks_json"])),
            heading_path=tuple(json.loads(row["heading_path"])),
        )
        return Hit(
            chunk=chunk,
            score=row["score"],
            page_title=row["page_title"] or "",
            url=row["url"] or "",
            categories=tuple(json.loads(row["categories"])),
            confidence=row["confidence"],
        )

    def page_text(self, source_id: str) -> str:
        row = self._db.execute(
            "SELECT text FROM page WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return row["text"]

    def support(
        self,
        answer: str,
        *,
        query: str | None = None,
        limit: int = 8,
        categories: tuple[str, ...] | None = None,
    ) -> spans.Span | None:
        """The span supporting `answer`, or None. This is the gate's question.

        None is a complete answer: the item is dropped. Nothing here degrades to
        a nearest match, because a nearest match is how an unsupported claim
        acquires a citation.
        """
        hits = self.search(query or answer, limit=limit, categories=categories)
        span = spans.support_for([hit.chunk for hit in hits], answer)
        if span is None:
            return None
        if not spans.verify(span, self.page_text(span.source_id)):
            return None
        return span

    def quarantined(self) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM quarantine").fetchall()

    def stats(self) -> dict[str, object]:
        one = lambda sql: self._db.execute(sql).fetchone()[0]  # noqa: E731
        by_category: dict[str, int] = {}
        for (raw,) in self._db.execute("SELECT categories FROM chunk"):
            for category in json.loads(raw):
                by_category[category] = by_category.get(category, 0) + 1
        return {
            "pages": one("SELECT count(*) FROM page"),
            "chunks": one("SELECT count(*) FROM chunk"),
            "chunks_attributed": one(
                "SELECT count(*) FROM chunk WHERE categories != '[]'"
            ),
            "chunks_unattributed": one(
                "SELECT count(*) FROM chunk WHERE categories = '[]'"
            ),
            "quarantined_blocks": one("SELECT count(*) FROM quarantine"),
            "chunks_by_category": dict(sorted(by_category.items())),
            "meta": {
                row["key"]: row["value"]
                for row in self._db.execute("SELECT key, value FROM meta")
            },
        }

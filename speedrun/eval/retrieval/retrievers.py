# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The retrievers ADR-0006 varies, behind the one interface the gate sees.

ADR-0006 holds the Generation gate constant and varies only the retriever. That
is only a real experiment if the arms are interchangeable *at the same seam*, so
each of these implements `speedrun_agent.corpus_gateway.Corpus` — `retrieve`,
`page_text`, `stats` — and nothing downstream is told which one it got. The
graph, the prompt, the model, the chunk budget and the gate are byte-identical
across arms; the only thing that differs is which eight chunks come back.

Three arms live here. The fourth (the ungated control) is not a retriever at
all — it is the hybrid arm read with the gate's ruling ignored, which is why it
costs no extra generation calls and is measured on exactly the same proposals.

**Nothing here is tuned.** The embedding model is OpenAI's small one at its
native dimensionality, the fusion is Reciprocal Rank Fusion at the k=60 the
method was published with, and the fusion depth is 20 per arm. Those constants
were written down before the first run. A knob turned after seeing a yield is a
knob that has to be reported alongside it, and the cheapest way to keep that
claim honest is to turn none.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import sys
from array import array
from math import sqrt
from pathlib import Path
from typing import Any, Sequence

RETRIEVAL_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = RETRIEVAL_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
DEFAULT_INDEX = CORPUS_DIR / "out" / "index.sqlite3"
OUT_DIR = RETRIEVAL_DIR / "out"

for _directory in (str(AGENT_DIR), str(CORPUS_DIR)):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

from speedrun_agent.corpus_gateway import (  # noqa: E402
    RetrievedChunk,
    ThreadConfinedCorpus,
    index_module,
)
from speedrun_agent.environment import key  # noqa: E402

#: The embedding model, named as an alias here and recorded as whatever the API
#: resolves it to in the cache manifest.
EMBEDDING_MODEL = "text-embedding-3-small"
#: How many chunks each ranking contributes to a fusion. Fixed before the run.
FUSION_DEPTH = 20
#: RRF's published constant. Not swept.
RRF_K = 60


# --------------------------------------------------------------------------
# Reading chunks back out of the corpus index
# --------------------------------------------------------------------------


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path) if path else DEFAULT_INDEX
    if not target.exists():
        raise FileNotFoundError(
            f"no corpus index at {target}. Build it with "
            f"`python speedrun/corpus/build.py --all`."
        )
    db = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


_CHUNK_SELECT = (
    "SELECT c.*, p.title AS page_title, p.url AS url"
    "  FROM chunk c JOIN page p ON p.source_id = c.source_id"
)


def _hit(row: sqlite3.Row, score: float) -> Any:
    """A corpus `Hit` built from a chunk row, so the gate sees its own types.

    The gate matches against `hit.chunk`, and a chunk it cannot address is not a
    citation. Rebuilding the corpus's own dataclasses — rather than inventing a
    lookalike — is what keeps a dense retrieval hit re-checkable on exactly the
    same terms as a BM25 one.
    """
    import chunker  # noqa: PLC0415

    chunk = chunker.Chunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        text=row["text"],
        blocks=tuple(chunker.BlockSpan(**b) for b in json.loads(row["blocks_json"])),
        heading_path=tuple(json.loads(row["heading_path"])),
    )
    return index_module().Hit(
        chunk=chunk,
        score=score,
        page_title=row["page_title"] or "",
        url=row["url"] or "",
        categories=tuple(json.loads(row["categories"])),
        confidence=row["confidence"],
    )


def _category_clause(categories: Sequence[str] | None) -> tuple[str, list[object]]:
    if not categories:
        return "", []
    clauses = " OR ".join(["c.categories LIKE ?"] * len(categories))
    return f" WHERE ({clauses})", [f'%"{c}"%' for c in categories]


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------


def _pack(vector: Sequence[float]) -> str:
    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def _unpack(blob: str) -> array:
    out = array("f")
    out.frombytes(base64.b64decode(blob))
    return out


def _normalised(vector: Sequence[float]) -> array:
    norm = sqrt(sum(v * v for v in vector)) or 1.0
    return array("f", [v / norm for v in vector])


class EmbeddingStore:
    """Chunk vectors on disk, built once and reused by two arms.

    Only *attributed* chunks are embedded, because retrieval in this pipeline is
    always category-restricted and an unattributed chunk can never be returned
    for a Topic. Embedding the other 1,370 would cost money to build an index of
    text no arm can reach.

    The file is JSONL — one chunk id and one base64 float32 vector per line —
    with a manifest recording the resolved model and the dimensionality. It is
    a cache, not evidence: deleting it costs a rebuild and nothing else, and it
    is gitignored for the same reason the corpus index is.
    """

    def __init__(self, path: Path, vectors: dict[str, array], meta: dict[str, Any]):
        self.path = path
        self.vectors = vectors
        self.meta = meta

    @classmethod
    def default_path(cls) -> Path:
        return OUT_DIR / "embeddings.jsonl"

    @classmethod
    def load(cls, path: Path | None = None) -> EmbeddingStore:
        target = path or cls.default_path()
        if not target.exists():
            raise FileNotFoundError(
                f"no embedding cache at {target}. Build it with "
                f"`python speedrun/eval/retrieval/retrievers.py --build-embeddings`."
            )
        meta: dict[str, Any] = {}
        vectors: dict[str, array] = {}
        with target.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("kind") == "manifest":
                    meta = row
                    continue
                vectors[row["chunk_id"]] = _unpack(row["vector"])
        return cls(target, vectors, meta)

    @classmethod
    def build(
        cls,
        *,
        path: Path | None = None,
        index_path: Path | None = None,
        batch: int = 96,
    ) -> EmbeddingStore:
        from openai import OpenAI  # noqa: PLC0415

        target = path or cls.default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        db = _connect(index_path)
        rows = db.execute(
            "SELECT chunk_id, text FROM chunk WHERE categories != '[]' ORDER BY chunk_id"
        ).fetchall()
        db.close()

        client = OpenAI(api_key=key("OPENAI_API_KEY"))
        vectors: dict[str, array] = {}
        resolved = ""
        tokens = 0
        with target.open("w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"kind": "manifest", "model": EMBEDDING_MODEL, "chunks": len(rows)}
                )
                + "\n"
            )
            for start in range(0, len(rows), batch):
                window = rows[start : start + batch]
                response = client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=[row["text"] for row in window],
                )
                resolved = response.model
                tokens += response.usage.total_tokens
                for row, item in zip(window, response.data):
                    unit = _normalised(item.embedding)
                    vectors[row["chunk_id"]] = unit
                    handle.write(
                        json.dumps({"chunk_id": row["chunk_id"], "vector": _pack(unit)})
                        + "\n"
                    )
                print(
                    f"  embedded {min(start + batch, len(rows))}/{len(rows)}",
                    flush=True,
                )
        meta = {
            "kind": "manifest",
            "model": EMBEDDING_MODEL,
            "resolved_model": resolved,
            "chunks": len(rows),
            "dimensions": len(next(iter(vectors.values()))) if vectors else 0,
            "prompt_tokens": tokens,
        }
        # Rewrite with the manifest now that the resolved id and token count are
        # known. The vectors are already in memory; nothing is re-requested.
        lines = [json.dumps(meta)]
        lines += [
            json.dumps({"chunk_id": chunk_id, "vector": _pack(vector)})
            for chunk_id, vector in vectors.items()
        ]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return cls(target, vectors, meta)


def embed_query(text: str) -> array:
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=key("OPENAI_API_KEY"))
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    return _normalised(response.data[0].embedding)


def _dot(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------
# The arms
# --------------------------------------------------------------------------


class _Backed:
    """Shared plumbing: one read-only connection, page text, chunk rows."""

    name = "unnamed"

    def __init__(self, index_path: Path | None = None) -> None:
        self._db = _connect(index_path)
        self._rows: dict[tuple[str, ...] | None, list[sqlite3.Row]] = {}

    def rows_for(self, categories: Sequence[str] | None) -> list[sqlite3.Row]:
        cache_key = tuple(categories) if categories else None
        if cache_key not in self._rows:
            where, params = _category_clause(categories)
            self._rows[cache_key] = self._db.execute(
                _CHUNK_SELECT + where, params
            ).fetchall()
        return self._rows[cache_key]

    def page_text(self, source_id: str) -> str:
        row = self._db.execute(
            "SELECT text FROM page WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return row["text"]

    def stats(self) -> dict[str, Any]:
        one = lambda sql: self._db.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "retriever": self.name,
            "pages": one("SELECT count(*) FROM page"),
            "chunks": one("SELECT count(*) FROM chunk"),
            "chunks_attributed": one(
                "SELECT count(*) FROM chunk WHERE categories != '[]'"
            ),
        }

    def close(self) -> None:
        self._db.close()


class EmbeddingCorpus(_Backed):
    """Arm 2: cosine similarity over OpenAI embeddings, same gate, same prompt.

    The query is the one `speedrun_agent.topics` fixed for every arm — the
    category's Outline title plus its itemised topic list. That string was
    chosen for BM25 (the title alone retrieved a chapter's throat-clearing) and
    it is 150-360 words long, which is not what a dense retriever is usually fed.
    Shortening it *for this arm* would make the comparison a prompt-engineering
    finding rather than a retrieval one, so it is left alone and the effect is
    reported instead.
    """

    name = "embedding-openai"

    def __init__(
        self, store: EmbeddingStore | None = None, index_path: Path | None = None
    ) -> None:
        super().__init__(index_path)
        self._store = store or EmbeddingStore.load()
        self._query_cache: dict[str, array] = {}

    def ranked(
        self, query: str, *, depth: int, categories: Sequence[str] | None
    ) -> list[tuple[sqlite3.Row, float]]:
        if query not in self._query_cache:
            self._query_cache[query] = embed_query(query)
        vector = self._query_cache[query]
        scored: list[tuple[sqlite3.Row, float]] = []
        for row in self.rows_for(categories):
            chunk_vector = self._store.vectors.get(row["chunk_id"])
            if chunk_vector is None:
                continue
            scored.append((row, _dot(vector, chunk_vector)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:depth]

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]:
        return [
            RetrievedChunk.of(_hit(row, score))
            for row, score in self.ranked(query, depth=limit, categories=categories)
        ]

    @classmethod
    def open(cls, index_path: Path | None = None) -> ThreadConfinedCorpus:
        return ThreadConfinedCorpus(lambda: cls(index_path=index_path))


class HybridCorpus(_Backed):
    """Arm 3: BM25 and embeddings fused by Reciprocal Rank Fusion.

    RRF rather than a weighted score blend, because the two scores are not on a
    common scale — FTS5's bm25() is a negative log-odds-ish quantity and cosine
    is bounded — and any weighting between them is a knob this evaluation has
    promised not to turn. RRF needs only the ranks, and its one constant is used
    at the published value.
    """

    name = "hybrid-rrf"

    def __init__(
        self, store: EmbeddingStore | None = None, index_path: Path | None = None
    ) -> None:
        super().__init__(index_path)
        self._dense = EmbeddingCorpus(store=store, index_path=index_path)
        self._sparse = index_module().CorpusIndex.open(
            index_path or DEFAULT_INDEX
        )

    def retrieve(
        self, query: str, *, limit: int = 8, categories: tuple[str, ...] | None = None
    ) -> list[RetrievedChunk]:
        sparse = self._sparse.search(query, limit=FUSION_DEPTH, categories=categories)
        dense = self._dense.ranked(query, depth=FUSION_DEPTH, categories=categories)

        fused: dict[str, float] = {}
        keep: dict[str, Any] = {}
        for rank, hit in enumerate(sparse):
            fused[hit.chunk.chunk_id] = fused.get(hit.chunk.chunk_id, 0.0) + 1.0 / (
                RRF_K + rank + 1
            )
            keep.setdefault(hit.chunk.chunk_id, RetrievedChunk.of(hit))
        for rank, (row, score) in enumerate(dense):
            chunk_id = row["chunk_id"]
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            keep.setdefault(chunk_id, RetrievedChunk.of(_hit(row, score)))

        order = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)
        return [keep[chunk_id] for chunk_id, _ in order[:limit]]

    def close(self) -> None:
        self._sparse.close()
        self._dense.close()
        super().close()

    @classmethod
    def open(cls, index_path: Path | None = None) -> ThreadConfinedCorpus:
        return ThreadConfinedCorpus(lambda: cls(index_path=index_path))


# --------------------------------------------------------------------------
# Is an answer's supporting text anywhere in the corpus at all?
# --------------------------------------------------------------------------


class CorpusWideCheck:
    """Does any indexed page contain this string, under the gate's own folding?

    The gate asks a narrower question — is the support in what *retrieval*
    returned — and the difference between the two is the whole point of the
    control arm. An answer the gate rejects might still be in the book on a page
    retrieval missed; an answer that is in no page at all is one the ungated
    pipeline would have shipped with no real source behind it.

    Matching reuses `corpus.spans`' normalisation so this check is exactly as
    forgiving as the gate: whitespace, case and typography are folded, and
    nothing else is. It therefore *over*-reports ungroundedness, because a true
    claim stated in the book's own different words reads as absent. Every hit is
    written out with its answer so a reader can sort those two apart by hand,
    and RETRIEVAL.md does exactly that.
    """

    def __init__(self, index_path: Path | None = None) -> None:
        import spans  # noqa: PLC0415

        self._spans = spans
        db = _connect(index_path)
        self._pages = {
            row["source_id"]: spans._normalize(row["text"])[0]  # noqa: SLF001
            for row in db.execute("SELECT source_id, text FROM page")
        }
        db.close()

    def source_for(self, answer: str) -> str | None:
        needle, _ = self._spans._normalize(answer)  # noqa: SLF001
        if not needle:
            return None
        for source_id, text in self._pages.items():
            if needle in text:
                return source_id
        return None

    def grounded(self, answer: str) -> bool:
        return self.source_for(answer) is not None


def main(argv: list[str]) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--build-embeddings",
        action="store_true",
        help="embed every attributed chunk and cache the vectors",
    )
    args = parser.parse_args(argv)
    if args.build_embeddings:
        store = EmbeddingStore.build()
        print(json.dumps(store.meta, indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

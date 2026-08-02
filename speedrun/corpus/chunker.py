# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pages into chunks, with the offsets that let a span be found again.

The generation gate has to assert that the supporting text for an item's answer
is present in a real source. "Present in chapter 3" cannot support that claim -
chapter 3 says a great many things, several of them the opposite of each other.
So a chunk is not just text: it is a byte range in a named page, and every chunk
this module produces satisfies

    page_text[chunk.char_start:chunk.char_end] == chunk.text

which is asserted on construction rather than hoped for. Given that, a match
found inside a chunk can be reported as an offset into the page, and re-checked
against the page later by anyone who doubts it.

Two rules keep spans honest:

  * A chunk is a whole number of blocks. Boundaries never land mid-sentence, so
    a span is never truncated by the chunker's arithmetic.
  * A block that trips the injection scan is dropped before the page text is
    assembled. Quarantined text is therefore not addressable at all: there is no
    offset that points at it, which is a stronger guarantee than filtering it
    out of results later.
"""

from __future__ import annotations

import dataclasses
import hashlib

import sanitize
from sanitize import Block, Finding

#: Aim for a chunk that holds a whole idea and still fits several into a prompt.
TARGET_CHARS = 1100
#: A single block longer than this is still emitted alone rather than split.
MAX_CHARS = 2200
#: Blocks shorter than this are never left as a chunk of their own.
MIN_CHARS = 120

BLOCK_SEPARATOR = "\n\n"


@dataclasses.dataclass(frozen=True)
class BlockSpan:
    """Where one source block sits in the page text."""

    id: str | None
    kind: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    char_start: int
    char_end: int
    text: str
    blocks: tuple[BlockSpan, ...]
    heading_path: tuple[str, ...]

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class Quarantined:
    """A block that was refused entry, and why."""

    source_id: str
    block_id: str | None
    kind: str
    finding: str
    excerpt: str


@dataclasses.dataclass(frozen=True)
class ChunkedPage:
    source_id: str
    page_text: str
    chunks: tuple[Chunk, ...]
    quarantined: tuple[Quarantined, ...]
    removed: dict[str, int]

    @property
    def page_sha256(self) -> str:
        return hashlib.sha256(self.page_text.encode("utf-8")).hexdigest()


class SpanInvariantError(RuntimeError):
    """A chunk's offsets do not address its own text. Never expected."""


def _screen(
    blocks: tuple[Block, ...], source_id: str
) -> tuple[list[Block], list[Quarantined]]:
    kept: list[Block] = []
    refused: list[Quarantined] = []
    for block in blocks:
        findings: list[Finding] = sanitize.scan_for_injection(block.text)
        if findings:
            refused.append(
                Quarantined(
                    source_id=source_id,
                    block_id=block.id,
                    kind=block.kind,
                    finding=findings[0].name,
                    excerpt=findings[0].excerpt,
                )
            )
            continue
        kept.append(block)
    return kept, refused


def _lay_out(blocks: list[Block]) -> tuple[str, list[BlockSpan]]:
    """Join blocks into one page text, recording where each one landed."""
    parts: list[str] = []
    spans: list[BlockSpan] = []
    cursor = 0
    for block in blocks:
        if parts:
            cursor += len(BLOCK_SEPARATOR)
        spans.append(
            BlockSpan(
                id=block.id, kind=block.kind, start=cursor, end=cursor + len(block.text)
            )
        )
        cursor += len(block.text)
        parts.append(block.text)
    return BLOCK_SEPARATOR.join(parts), spans


def _heading_path_at(blocks: list[Block], upto: int) -> tuple[str, ...]:
    """The headings in force at block index `upto`, outermost first."""
    path: dict[int, str] = {}
    for block in blocks[: upto + 1]:
        if block.kind == "heading":
            path = {d: t for d, t in path.items() if d < block.depth}
            path[block.depth] = block.text
    return tuple(path[d] for d in sorted(path))


def _join(chunks: list[Chunk], page_text: str, source_id: str) -> Chunk:
    first, last = chunks[0], chunks[-1]
    return Chunk(
        chunk_id=f"{source_id}#{first.char_start}-{last.char_end}",
        source_id=source_id,
        char_start=first.char_start,
        char_end=last.char_end,
        text=page_text[first.char_start : last.char_end],
        blocks=tuple(b for c in chunks for b in c.blocks),
        heading_path=first.heading_path,
    )


def _absorb_orphans(
    chunks: list[Chunk], page_text: str, source_id: str
) -> list[Chunk]:
    """Fold headings with nothing under them into the chunk that follows.

    A heading immediately followed by another heading would otherwise become a
    chunk of two or three words: retrievable, entirely uninformative, and a way
    for a hit to carry a citation that supports nothing. The last chunk has no
    successor, so a short one folds backwards instead.
    """
    merged: list[Chunk] = []
    pending: list[Chunk] = []
    for chunk in chunks:
        has_prose = any(block.kind != "heading" for block in chunk.blocks)
        if not has_prose:
            pending.append(chunk)
            continue
        merged.append(_join([*pending, chunk], page_text, source_id) if pending else chunk)
        pending = []
    if pending:
        if merged:
            merged[-1] = _join([merged[-1], *pending], page_text, source_id)
        else:
            merged.extend(pending)
    if len(merged) > 1 and len(merged[-1].text) < MIN_CHARS:
        tail = merged.pop()
        merged[-1] = _join([merged[-1], tail], page_text, source_id)
    return merged


def chunk_page(
    source_id: str,
    parsed: sanitize.ParsedPage,
    *,
    target_chars: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
) -> ChunkedPage:
    """Screen, lay out and chunk one page."""
    kept, refused = _screen(parsed.blocks, source_id)
    page_text, spans = _lay_out(kept)

    chunks: list[Chunk] = []
    start_index = 0

    def flush(end_index: int) -> None:
        nonlocal start_index
        if end_index <= start_index:
            return
        first, last = spans[start_index], spans[end_index - 1]
        text = page_text[first.start : last.end]
        if not text.strip():
            start_index = end_index
            return
        chunk = Chunk(
            chunk_id=f"{source_id}#{first.start}-{last.end}",
            source_id=source_id,
            char_start=first.start,
            char_end=last.end,
            text=text,
            blocks=tuple(spans[start_index:end_index]),
            heading_path=_heading_path_at(kept, start_index),
        )
        if page_text[chunk.char_start : chunk.char_end] != chunk.text:
            raise SpanInvariantError(chunk.chunk_id)
        chunks.append(chunk)
        start_index = end_index

    for i, block in enumerate(kept):
        # A heading opens a new chunk: the text under it is what it names.
        if block.kind == "heading" and i > start_index:
            flush(i)
        running = spans[i].end - spans[start_index].start
        if running >= target_chars or running >= max_chars:
            flush(i + 1)

    flush(len(kept))

    chunks = _absorb_orphans(chunks, page_text, source_id)

    return ChunkedPage(
        source_id=source_id,
        page_text=page_text,
        chunks=tuple(chunks),
        quarantined=tuple(refused),
        removed=dict(parsed.removed),
    )

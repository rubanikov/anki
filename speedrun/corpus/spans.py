# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Finding the exact supporting span, and proving it is still there.

The generation gate's assertion is "the supporting text for this answer appears
in the retrieved source". Retrieval alone cannot make that assertion: a chunk
about enzyme inhibition is not evidence that any particular sentence about
enzyme inhibition was written by anyone. This module is the part that turns a
hit into a citation - a byte range in a named page, and the exact characters
that live there.

Matching is deliberately forgiving about whitespace, case and typography, and
deliberately unforgiving about everything else. A model that paraphrases has not
found supporting text; it has written some. The quote returned is always the
source's own characters, never the caller's, so the citation cannot drift toward
what the generator wanted the source to say.

`verify` exists because a span that cannot be re-checked is a claim, not
evidence. The gate asserts; anyone reading the log can re-assert.
"""

from __future__ import annotations

import dataclasses
import re

_WHITESPACE = re.compile(r"\s+")

#: Typographic variants folded together before matching. A textbook writes
#: "Michaelis–Menten" with an en dash; a model writes it with a hyphen. That is
#: not a difference of fact and should not fail the gate.
_FOLD = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    " ": " ",
    "­": "",
}


@dataclasses.dataclass(frozen=True)
class Span:
    """Where a claim's support sits, precisely enough to re-check it."""

    source_id: str
    chunk_id: str
    start: int
    end: int
    quote: str
    block_id: str | None

    def as_citation(self, url: str | None = None) -> str:
        where = f"{self.source_id}[{self.start}:{self.end}]"
        if url and self.block_id:
            return f"{where} {url}#{self.block_id}"
        if url:
            return f"{where} {url}"
        return where


def _normalize(text: str) -> tuple[str, list[int]]:
    """Fold text for matching, keeping a map back to original offsets.

    `offsets[i]` is the index in `text` of the character that produced
    `normalized[i]`, so a match in the normalized string can be reported as a
    range in the source.
    """
    out: list[str] = []
    offsets: list[int] = []
    previous_was_space = True  # so leading whitespace is dropped
    for index, char in enumerate(text):
        folded = _FOLD.get(char, char)
        if folded == "":
            continue
        if _WHITESPACE.fullmatch(folded):
            if previous_was_space:
                continue
            out.append(" ")
            offsets.append(index)
            previous_was_space = True
            continue
        out.append(folded.casefold())
        offsets.append(index)
        previous_was_space = False
    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets


def find_span(chunk, needle: str) -> Span | None:
    """The span of `needle` inside `chunk`, in page coordinates, or None.

    `chunk` is a `chunker.Chunk`; the page offsets it carries are what make the
    returned span addressable outside the chunk that happened to be retrieved.
    """
    normalized_needle, _ = _normalize(needle)
    if not normalized_needle:
        return None
    normalized_text, offsets = _normalize(chunk.text)
    at = normalized_text.find(normalized_needle)
    if at < 0:
        return None

    start_local = offsets[at]
    end_local = offsets[at + len(normalized_needle) - 1] + 1
    start = chunk.char_start + start_local
    end = chunk.char_start + end_local
    return Span(
        source_id=chunk.source_id,
        chunk_id=chunk.chunk_id,
        start=start,
        end=end,
        quote=chunk.text[start_local:end_local],
        block_id=_enclosing_block(chunk, start),
    )


def _enclosing_block(chunk, page_offset: int) -> str | None:
    for block in chunk.blocks:
        if block.start <= page_offset < block.end:
            return block.id
    return None


def verify(span: Span, page_text: str) -> bool:
    """Re-check a span against the page it claims to come from."""
    if span.start < 0 or span.end > len(page_text) or span.start >= span.end:
        return False
    return page_text[span.start : span.end] == span.quote


def support_for(chunks, needle: str) -> Span | None:
    """The first span supporting `needle` across an ordered list of chunks.

    This is the shape the gate wants: hand it what retrieval returned and the
    answer text, get back a citation or nothing. Nothing means drop the item.
    """
    for chunk in chunks:
        span = find_span(chunk, needle)
        if span is not None:
            return span
    return None

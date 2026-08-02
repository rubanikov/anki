# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Turning a downloaded page into text that is safe to put in front of a model.

The threat is not malformed HTML. It is an author - or anyone who can serve or
mirror the source - writing instructions aimed at whatever reads the page next.
Retrieval hands those instructions to a generator with no marker saying they
came from the corpus rather than from us, so the corpus is a privilege-escalation
path unless something upstream refuses to carry them.

Two mechanisms, deliberately different, because the vectors are different in
kind:

**Structural removal.** Script, style, comments, attribute values, hidden
elements and invisible characters are dropped before any text exists. There is
no reading under which a `<script>` body or an `alt` attribute is prose a
student should study, so nothing is lost by never extracting them, and a
detector is not needed for a channel that is closed.

**Quarantine.** Visible prose that reads as an instruction to a model is
refused, recorded with the pattern that caught it, and never indexed. This is a
judgement call and it can be wrong, so it is never silent: `build.py` prints the
count and `index.quarantine` keeps the evidence. It refuses rather than redacts,
because a page that half-argues with the reader is not a page whose remaining
half can be trusted.

Detection is a floor, not a wall. A sufficiently subtle instruction phrased as
biology will pass, and the honest mitigation for that is downstream: the
generation gate checks answers against retrieved spans, so a chunk that talks a
generator into inventing an answer still cannot produce a supported item. The
sanitizer's job is to close the cheap channels, not to promise there are none.
"""

from __future__ import annotations

import dataclasses
import html
import re
import unicodedata
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# What is never extracted
# ---------------------------------------------------------------------------

#: Elements whose text content is never prose. Everything between the open and
#: close tag is discarded, including nested markup.
OPAQUE_ELEMENTS = frozenset(
    {"script", "style", "noscript", "template", "iframe", "object", "embed", "svg"}
)

#: Elements that open a new addressable block of text.
BLOCK_ELEMENTS = frozenset(
    {
        "p",
        "li",
        "dd",
        "dt",
        "td",
        "th",
        "caption",
        "figcaption",
        "blockquote",
        "pre",
    }
)

HEADING_ELEMENTS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

#: Zero-width, bidi-override and other characters that render as nothing. They
#: exist in a corpus for exactly one reason: to hide text from a human reviewer
#: while leaving it legible to a tokenizer.
INVISIBLE_CHARACTERS = frozenset(
    "​‌‍‎‏"  # zero width space/non-joiner/joiner, LRM, RLM
    "‪‫‬‭‮"  # bidi embedding and override
    "⁠⁡⁢⁣⁤"  # word joiner, invisible operators
    "⁦⁧⁨⁩"  # bidi isolates
    "﻿­᠎"  # BOM, soft hyphen, Mongolian vowel separator
)

#: The Unicode tag block: a full ASCII alphabet that renders as nothing at all.
TAG_BLOCK = range(0xE0000, 0xE0080)

_WHITESPACE_RUN = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{2,}")

_HIDDEN_STYLE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0"
    r"|opacity\s*:\s*0(?![.\d])|(?:width|height)\s*:\s*0(?:px)?\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# What is quarantined
# ---------------------------------------------------------------------------

#: Visible prose matching any of these is refused. Each pattern is here because
#: it is an instruction aimed at a model, not a statement about the world; a
#: biology textbook has no reason to contain one.
INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "override-instructions",
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b"
        r"(previous|prior|above|earlier|preceding|all)\b[^.\n]{0,20}\b"
        r"(instruction|prompt|direction|rule|context|text|passage)",
    ),
    (
        "addresses-the-model",
        r"\byou are (now )?(an?|the)\b[^.\n]{0,40}\b"
        r"(ai|assistant|model|language model|answer key|grader|tutor|chatbot)\b",
    ),
    (
        "system-prompt",
        r"\b(system|developer)\s*(prompt|message|instruction)s?\b",
    ),
    (
        "chat-template-delimiter",
        r"(<\|[a-z_]+\|>|\[/?INST\]|<<SYS>>|###\s*(system|assistant|human)\b)",
    ),
    (
        "new-instructions",
        r"\bnew (instruction|rule|task|objective)s?\b[^.\n]{0,20}(for|to)\b"
        r"[^.\n]{0,30}\b(you|the (assistant|model|ai|generator))\b",
    ),
    (
        "instructs-about-output",
        r"\b(always|never|do not|don't|must)\b[^.\n]{0,40}\b"
        r"(respond|reply|answer|output|report|state|mention|say)\b"
        r"[^.\n]{0,60}\b(instead|as follows|the following|this paragraph)\b",
    ),
    (
        "claims-verification",
        r"\b(mark|treat|report|consider)\b[^.\n]{0,40}\b"
        r"(as (verified|supported|correct|valid)|the span as present"
        r"|passes the generation gate)\b",
    ),
    (
        "leak-request",
        r"\b(reveal|disclose|print|output|show)\b[^.\n]{0,40}\b"
        r"(answer key|correct answer|held-out item|the answer)\b",
    ),
    (
        "follow-these-instead",
        r"\bfollow (these|the following)\b[^.\n]{0,30}\binstead\b",
    ),
)

_COMPILED = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in INJECTION_PATTERNS
)


@dataclasses.dataclass(frozen=True)
class Finding:
    name: str
    excerpt: str


@dataclasses.dataclass(frozen=True)
class Block:
    """One addressable unit of a page - a paragraph, heading or caption."""

    id: str | None
    kind: str
    text: str
    depth: int = 0


@dataclasses.dataclass(frozen=True)
class ParsedPage:
    blocks: tuple[Block, ...]
    #: Counts of what was removed structurally, for the build report.
    removed: dict[str, int]


# ---------------------------------------------------------------------------
# Character-level cleaning
# ---------------------------------------------------------------------------


def strip_invisible(text: str) -> tuple[str, int]:
    """Remove characters that render as nothing. Returns the count removed."""
    out: list[str] = []
    removed = 0
    for char in text:
        code = ord(char)
        if char in INVISIBLE_CHARACTERS or code in TAG_BLOCK:
            removed += 1
            continue
        if unicodedata.category(char) in ("Cc", "Cf") and char not in "\n\t":
            removed += 1
            continue
        out.append(char)
    return "".join(out), removed


def sanitize_text(text: str) -> tuple[str, int]:
    """Normalize, strip invisibles and collapse whitespace."""
    cleaned, removed = strip_invisible(unicodedata.normalize("NFC", text))
    cleaned = _WHITESPACE_RUN.sub(" ", cleaned.replace("\t", " "))
    cleaned = _BLANK_LINES.sub("\n", cleaned)
    return cleaned.strip(), removed


def scan_for_injection(text: str) -> list[Finding]:
    """Every injection pattern this text trips, in declaration order."""
    findings: list[Finding] = []
    for name, pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 20)
            findings.append(
                Finding(name=name, excerpt=text[start : match.end() + 40].strip())
            )
    return findings


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class _PageParser(HTMLParser):
    """Extract addressable blocks of prose, and nothing else.

    The parser never reads an attribute for its text. Attribute values are
    consulted for exactly two things - the element id, which is what makes a
    span citable, and a style that hides the element, which is what makes it
    suspicious - and neither is ever emitted as content.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.removed: dict[str, int] = {
            "opaque_elements": 0,
            "comments": 0,
            "hidden_elements": 0,
            "invisible_characters": 0,
        }
        self._opaque_depth = 0
        self._hidden_depth = 0
        self._stack: list[tuple[str, str | None, int, list[str]]] = []

    # -- element tracking --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._opaque_depth:
            self._opaque_depth += 1
            return
        if tag in OPAQUE_ELEMENTS:
            self._opaque_depth = 1
            self.removed["opaque_elements"] += 1
            return

        attributes = dict(attrs)
        style = attributes.get("style") or ""
        hidden = bool(_HIDDEN_STYLE.search(style)) or "hidden" in attributes
        if hidden:
            self._hidden_depth += 1
            self.removed["hidden_elements"] += 1
            return
        if self._hidden_depth:
            self._hidden_depth += 1
            return

        if tag in HEADING_ELEMENTS:
            self._open("heading", attributes.get("id"), HEADING_ELEMENTS[tag])
        elif tag in BLOCK_ELEMENTS:
            self._open("para", attributes.get("id"), 0)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Void elements carry no text. `alt`, `title` and `content` are
        # attacker-controlled and are never harvested.
        return

    def handle_endtag(self, tag: str) -> None:
        if self._opaque_depth:
            self._opaque_depth -= 1
            return
        if self._hidden_depth:
            self._hidden_depth -= 1
            return
        if tag in HEADING_ELEMENTS or tag in BLOCK_ELEMENTS:
            self._close()

    def _open(self, kind: str, element_id: str | None, depth: int) -> None:
        if self._stack:
            self._close()
        self._stack.append((kind, element_id, depth, []))

    def _close(self) -> None:
        if not self._stack:
            return
        kind, element_id, depth, parts = self._stack.pop()
        text, invisible = sanitize_text("".join(parts))
        self.removed["invisible_characters"] += invisible
        # A block is one logical unit, so line breaks inside it are layout, not
        # meaning. Collapsing them keeps a span from straddling a stray newline
        # that only existed because the source was pretty-printed.
        text = " ".join(text.split())
        if text:
            self.blocks.append(
                Block(id=element_id, kind=kind, text=text, depth=depth)
            )

    # -- content -----------------------------------------------------------

    def handle_data(self, data: str) -> None:
        if self._opaque_depth or self._hidden_depth or not self._stack:
            return
        self._stack[-1][3].append(data)

    def handle_comment(self, data: str) -> None:
        self.removed["comments"] += 1

    def handle_decl(self, decl: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        # `<![CDATA[...]]>` inside a script we are already skipping.
        return

    def close(self) -> None:  # type: ignore[override]
        super().close()
        while self._stack:
            self._close()


def parse_page(xhtml: str) -> ParsedPage:
    """Parse a downloaded page into safe, addressable blocks."""
    parser = _PageParser()
    parser.feed(xhtml)
    parser.close()
    return ParsedPage(blocks=tuple(parser.blocks), removed=dict(parser.removed))


def sanitize_plain_text(text: str) -> tuple[str, int]:
    """For sources that are already plain text rather than markup."""
    return sanitize_text(html.unescape(text))

#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Did a Held-out item, or the licensed corpus, reach somewhere it must not?

A Performance number computed on items the model or the student had already
seen is void. This script is the evidence that did not happen. It is a check,
not a claim: it reads the actual prompts, the actual corpus index, the actual
coaching code and the actual git history, and it prints the denominators so a
reader can see how much was looked at before believing the word "clean".

Four checks, all of which must pass for exit 0:

1. **No Held-out item, or near-copy, in a generation prompt, a corpus chunk, or
   coaching material.** H2 (the P-set) and H3 (the AI-card gold set).
2. **The licensed calibration corpus is absent from git history**, not merely
   from the working tree. `freeze.py --verify` already asserts the working
   tree and says in so many words that the git-tracked assertion belongs here.
   A file added in one commit and deleted in the next is still in the history,
   so `git log --all --diff-filter=A` is read as well as `git ls-files`.
3. **No API key** — no `sk-`-prefixed secret — in any tracked file, and none
   ever added on any branch under `speedrun/`.
4. **No deck or collection binary tracked.**

What counts as a leak, and what does not
----------------------------------------

**A hit is an item's stem, or the whole item, appearing in a surface.** The
stem is what identifies an item: it is the question the student has never seen.
Two detectors, both taken from the test plan (§5) rather than invented here:

* **normalised exact match** — the item's normalised text appears as a
  substring of the surface's normalised text;
* **near-copy** — 5-gram Jaccard >= 0.6 against the best-matching window of the
  surface text, the window sized to the item so the measure is not diluted by
  document length. Whole-document Jaccard would be unfalsifiable: a 30-word
  stem copied verbatim into a 1000-word chunk scores about 0.03 against the
  whole chunk, so a check using it could never fail. The windowed form is
  strictly stronger, and the self-test proves it fires.

**A bare answer string is not a leak.** `apoptosis`, `glycolysis` and
`S phase` are ordinary biology terms. `speedrun/eval/pset/check_no_leak.py`
already reports 12 of them present in the MileDown deck, and a biology deck is
*supposed* to contain those words; counting them would make the check fail on a
correct system, and a check that fails on a correct system gets deleted rather
than fixed. Stronger still for the corpus: the Generation gate *requires* each
answer to be a span copied verbatim out of a corpus chunk, so "the answer is in
the corpus" is the gate working, not the gate leaking. Bare-answer overlap is
counted and printed as a separate, expected number, never as a finding. The
line is: **a stem, or a whole item, is leakage; a single answer term is
vocabulary.**

**An item id is not content either.** The manifest publishes every item id and
hash in its ledger on purpose, so that a defect can be cited without quoting
the item — `speedrun/eval/aicheck/grade.py` does exactly that in a comment
explaining a rule change. Id matches are counted and printed, and graded only
inside the corpus, where an id in third-party textbook prose would mean
Speedrun's own data had been written into the source.

**An item is not compared to its own source, and that exclusion is exactly one
chunk wide.** Every Held-out item declares where it came from: H2 items carry a
`source_span.chunk_id` the Generation gate matched their answer against, and H3
gold pairs were drawn by hand from a named chunk. Comparing an item to the
chunk it was made from does not ask "did this item leak?" — it asks "is this
item too close to its source?", which is a gold-set quality question and
belongs to the AI card check's third bucket, not here. So that one pair is
**measured and printed, never graded**, and the exclusion is taken from the
item's own declared provenance rather than a hand-written allowlist: an item
matching any chunk it did *not* declare is still a finding, and the self-test
proves it. The highest own-source overlap in the run is printed by name, so an
item that restates its source almost word for word is visible rather than
excused. `--strict-provenance` grades those pairs too.

**Direction matters for run logs, and is split mechanically.** A trace file
holds both what was sent to a model and what came back. The two halves are
separated by key and reported as two numbers — see `SPLIT_JSONL` below.

Usage
-----

    python speedrun/eval/leakage/leakage_check.py
    python speedrun/eval/leakage/leakage_check.py --self-test-only
    python speedrun/eval/leakage/leakage_check.py --log run.log --json report.json

Exit codes: 0 = clean, 1 = a finding (or the self-test failed), 2 = nothing was
checked, which is never reported as clean.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

HOLDOUT_DIR = REPO_ROOT / "speedrun" / "eval" / "holdout"
CORPUS_INDEX = REPO_ROOT / "speedrun" / "corpus" / "out" / "index.sqlite3"
CORPUS_RAW_PAGES = REPO_ROOT / "speedrun" / "corpus" / "raw" / "pages"

#: Where the Held-out items live. H2's ledgered copy is the authority; the
#: generator's own copy is loaded too, and a disagreement between them is
#: itself reported — two versions of an item is a hash the manifest cannot fix.
ITEM_SOURCES: tuple[tuple[str, Path], ...] = (
    ("H2", HOLDOUT_DIR / "h2_pset.jsonl"),
    ("H2", REPO_ROOT / "speedrun" / "eval" / "pset" / "h2_pset.jsonl"),
    ("H3", HOLDOUT_DIR / "h3_gold.jsonl"),
    ("H3", REPO_ROOT / "speedrun" / "eval" / "aicheck" / "gold_pairs.json"),
    ("H4", HOLDOUT_DIR / "h4_rset.jsonl"),
    ("H4", REPO_ROOT / "speedrun" / "eval" / "paraphrase" / "h4_rset.jsonl"),
)

N_GRAM = 5
JACCARD_THRESHOLD = 0.6

# --------------------------------------------------------------------------
# Surfaces — what gets searched, and why that is the right list
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Surface:
    name: str
    why: str
    globs: tuple[str, ...]
    graded: bool = True


#: Named because two places refer to it.
RUN_EVIDENCE = "generation run evidence (output side)"


#: Globs are POSIX, relative to the repo root, and resolved against the working
#: tree rather than a hand-written file list, so a new prompt file added next
#: week is searched without anyone remembering to add it here.
SURFACES: tuple[Surface, ...] = (
    # Ordered: the first surface to claim a file keeps it, so coaching material
    # is listed before the broader code glob that would otherwise swallow it.
    Surface(
        "coaching material",
        "the spoken loop's own text: its prompts, its contrast pairs, and the "
        "add-on surface that speaks them",
        (
            "speedrun/agent/speedrun_agent/coach*.py",
            "speedrun/addon/coach/*.py",
            "speedrun/addon/reviewer.py",
            "speedrun/addon/render.py",
        ),
    ),
    Surface(
        "grading material",
        "the blind grader is *given* the gold pair — that is what grading is. "
        "Gold text is required here and is not leakage. It is named as its own "
        "surface rather than left in the catch-all so that the exemption is "
        "visible: the generator's prompt is a different surface and is graded",
        (
            "speedrun/eval/*/out/cards.json",
            "speedrun/eval/*/out/grades*.jsonl",
            "speedrun/eval/*/out/buckets*.jsonl",
        ),
        graded=False,
    ),
    Surface(
        "generation prompts",
        "every Speedrun source file that can put text in front of a model — "
        "all of the agent, corpus, eval and add-on code that is not coaching "
        "material — plus the input side of every recorded run log and trace",
        (
            "speedrun/agent/**/*.py",
            "speedrun/corpus/**/*.py",
            "speedrun/eval/**/*.py",
            "speedrun/addon/**/*.py",
            "speedrun/evidence/**/*.py",
            "speedrun/crosswalk/**/*.py",
            "speedrun/corpus/outline.json",
            "speedrun/eval/*/run_log.jsonl",
            "speedrun/eval/*/out/*.jsonl",
            "speedrun/agent/out/*.jsonl",
        ),
    ),
    Surface(
        "corpus chunks",
        "the retrieval unit the generator is handed, its parent pages, and the "
        "pre-sanitisation downloads those pages were built from",
        ("speedrun/corpus/raw/pages/*.json",),
    ),
    Surface(
        RUN_EVIDENCE,
        "the output side of the generation run: what the model returned and "
        "what shipped. Searched and reported, never graded — see below",
        (),
        graded=False,
    ),
    Surface(
        "other tracked Speedrun text",
        "everything else under speedrun/ — write-ups, specs, tests. Searched "
        "and reported, but not graded: an item quoted in an evidence document "
        "after its Attempt is publication, not Leakage",
        ("speedrun/**",),
        graded=False,
    ),
)

#: JSONL evidence files whose records are split by *direction* before grading.
#: A trace record holds both what was sent to a model and what came back, in
#: the same file. Grading the file whole would flag every item as leaked into
#: its own generation record, which is provenance, not Leakage — an item has to
#: come from somewhere, and the run log is where it came from. Grading the file
#: not at all would be worse: it would exempt the one artifact that would show
#: a real leak, an item fed back in as input to a later generation.
#:
#: So the record is split. Everything the model or retriever was *given* is
#: graded exactly as a prompt file is. Everything they *returned* is counted and
#: printed but not graded. The split is mechanical, by key, and the resulting
#: two numbers — how many items appear on each side — are the honest form of
#: the claim.
SPLIT_JSONL: tuple[str, ...] = (
    "speedrun/eval/*/run_log.jsonl",
    "speedrun/eval/*/out/*.jsonl",
    "speedrun/agent/out/*.jsonl",
)

#: Top-level keys whose contents were put in front of a model or a retriever.
INPUT_KEYS: frozenset[str] = frozenset(
    {
        "inputs",
        "query",
        "prompt",
        "prompts",
        "passages",
        "messages",
        "system",
        "target_concept",
        "question_type",
        "topic",
        "topic_id",
        "seed",
    }
)

#: A retriever's output *is* the generator's input: the passages the prompt is
#: formatted with. So for these nodes the `outputs` field is graded as prompt
#: content rather than as a returned result.
PROMPT_SIDE_OUTPUT_NODES: frozenset[str] = frozenset({"retrieve", "retriever"})

#: Never searched, because they *are* the item store or this check's own
#: output. Searching them would guarantee a hit and prove nothing.
#: Derived from ITEM_SOURCES rather than written twice: a file is exempt from
#: being a haystack precisely when it is a needle store. A second copy of a set
#: is therefore never quietly ignored — it is loaded, its items are checked
#: against everything else, and any disagreement with the ledgered copy is
#: reported as a finding of its own.
NOT_A_SURFACE: tuple[str, ...] = (
    *(path.relative_to(REPO_ROOT).as_posix() for _, path in ITEM_SOURCES),
    "speedrun/eval/holdout/h1_reviews.jsonl",
    "speedrun/eval/leakage/*",
)

# --------------------------------------------------------------------------
# git patterns
# --------------------------------------------------------------------------

#: fnmatch's `*` crosses `/`, which is what is wanted here: the corpus must be
#: absent from every directory, not just the one it was downloaded into.
LICENSED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("*anki-revlogs-10k*", "the licensed corpus itself, under any path"),
    ("*revlogs*.7z", "the raw corpus archive"),
    ("*revlogs*.zst", "the raw corpus archive"),
    ("speedrun/eval/holdout/h1_reviews.jsonl", "H1 — a derivative of the corpus"),
    ("speedrun/eval/holdout/raw/*", "raw corpus files staged for the split"),
    ("speedrun/eval/corpus/*", "the corpus staging directory"),
    ("speedrun/eval/.hf_cache/*", "the Hugging Face download cache"),
    ("speedrun/*.parquet", "the corpus's parquet distribution, anywhere under speedrun/"),
)

#: These must be in .gitignore for the patterns above to stay absent. freeze.py
#: checks the same list against the working tree; this check confirms the rules
#: still exist, because a deleted ignore rule is how the next file gets added.
REQUIRED_GITIGNORE: tuple[str, ...] = (
    "speedrun/**/anki-revlogs-10k/",
    "speedrun/eval/corpus/",
    "speedrun/eval/holdout/raw/",
    "speedrun/eval/holdout/h1_reviews.jsonl",
    "speedrun/eval/holdout/*.parquet",
    "speedrun/eval/.hf_cache/",
)

DECK_PATTERNS: tuple[str, ...] = (
    "*.apkg",
    "*.colpkg",
    "*.anki2",
    "*.anki21",
    "*.anki2-wal",
    "*.anki2-journal",
    "*.media.db2",
)

#: Anki's own test fixtures, in the fork before this project began (the oldest
#: dates to 2020). They are not student data and not Speedrun's to remove, so
#: they are allowed *and named*, rather than quietly excluded by a broad rule.
UPSTREAM_FIXTURE_PREFIXES: tuple[str, ...] = (
    "pylib/tests/support/",
    "rslib/tests/support/",
)

#: An OpenAI/Anthropic-style secret. Written as a pattern rather than an
#: example so this file cannot itself trip the check it defines.
API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")

# --------------------------------------------------------------------------
# Text machinery
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Lowercase, punctuation to spaces, whitespace collapsed.

    The same normalisation `check_no_leak.py` uses, so "normalised exact match"
    means the same thing in both checks: a leak that dropped a comma or changed
    a dash still matches.
    """
    keep = [ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text]
    return " ".join("".join(keep).split())


def shingles(words_: Sequence[str], n: int = N_GRAM) -> set[tuple[str, ...]]:
    if len(words_) < n:
        return set()
    return {tuple(words_[i : i + n]) for i in range(len(words_) - n + 1)}


def containment(needle: set[Any], hay: set[Any]) -> float:
    """|needle ∩ hay| / |needle| — the share of the item present at all.

    This is a *sound* prefilter for the windowed Jaccard below. For any window
    W of the haystack, |N ∩ W| <= |N ∩ H|, and Jaccard(N, W) = |N ∩ W| /
    (|N| + |W| - |N ∩ W|) <= |N ∩ W| / |N| <= containment. So containment below
    the threshold proves no window can reach it, and the expensive scan is only
    run where it could still fire. Nothing is skipped that could have matched.
    """
    if not needle:
        return 0.0
    return len(needle & hay) / len(needle)


def best_window_jaccard(
    needle_words: Sequence[str], hay_words: Sequence[str], n: int = N_GRAM
) -> float:
    """Highest 5-gram Jaccard over windows of the haystack sized to the item."""
    needle = shingles(needle_words, n)
    if not needle:
        return 0.0
    width = len(needle_words)
    if len(hay_words) <= width:
        hay = shingles(hay_words, n)
        union = len(needle | hay)
        return len(needle & hay) / union if union else 0.0
    best = 0.0
    for start in range(0, len(hay_words) - width + 1):
        hay = shingles(hay_words[start : start + width], n)
        union = len(needle | hay)
        if union:
            best = max(best, len(needle & hay) / union)
    return best


def word_positions(hay_words: Sequence[str]) -> dict[str, list[int]]:
    """Built once per document; reused by every item. Without this the run
    diagnostic is O(words x items) and dominates the whole run."""
    positions: dict[str, list[int]] = {}
    for index, word in enumerate(hay_words):
        positions.setdefault(word, []).append(index)
    return positions


def longest_common_run(
    needle_words: Sequence[str],
    hay_words: Sequence[str],
    positions: dict[str, list[int]] | None = None,
) -> int:
    """Longest run of words the two share verbatim. A diagnostic, not a rule."""
    if not needle_words or not hay_words:
        return 0
    if positions is None:
        positions = word_positions(hay_words)
    best = 0
    previous: dict[int, int] = {}
    for word in needle_words:
        current: dict[int, int] = {}
        for index in positions.get(word, ()):
            run = previous.get(index - 1, 0) + 1
            current[index] = run
            best = max(best, run)
        previous = current
    return best


# --------------------------------------------------------------------------
# The things being compared
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Item:
    """One Held-out item, reduced to the strings that identify it."""

    item_id: str
    set_name: str
    stem: str
    answer: str
    whole: str
    origin: str
    #: What the item itself says it was drawn from. Used only to exclude the
    #: single (item, own source) pair from grading — never widened.
    source_chunk_id: str = ""
    source_page_id: str = ""

    def is_own_source(self, provenance: str) -> bool:
        return bool(provenance) and provenance in (
            self.source_chunk_id,
            self.source_page_id,
        )

    def needles(self) -> tuple[tuple[str, str], ...]:
        """(kind, text) pairs that must not appear. The answer is not among them."""
        return (("stem", self.stem), ("whole item", self.whole))


@dataclasses.dataclass(frozen=True)
class Document:
    surface: str
    label: str
    text: str
    #: Chunk id or page id, for corpus documents. Empty for everything else,
    #: which is why the ancestry exclusion cannot apply outside the corpus.
    provenance: str = ""


@dataclasses.dataclass(frozen=True)
class Finding:
    check: str
    detail: str


@dataclasses.dataclass
class SurfaceStats:
    documents: int = 0
    words: int = 0
    comparisons: int = 0
    answer_only_items: set[str] = dataclasses.field(default_factory=set)
    matched_items: set[str] = dataclasses.field(default_factory=set)
    id_only_items: set[str] = dataclasses.field(default_factory=set)
    max_containment: float = 0.0
    max_containment_where: str = ""
    max_jaccard: float = 0.0
    max_jaccard_where: str = ""
    longest_run: int = 0
    longest_run_where: str = ""
    #: (item, its own declared source) pairs — measured, not graded.
    ancestral_pairs: int = 0
    ancestral_scores: list[tuple[float, str]] = dataclasses.field(default_factory=list)


def _rows_from(path: Path) -> list[dict[str, Any]]:
    """JSONL, a JSON array, or a JSON object with one list of records in it."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    blob = json.loads(text)
    if isinstance(blob, list):
        return [row for row in blob if isinstance(row, dict)]
    for value in blob.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def load_items(sources: Sequence[tuple[str, Path]]) -> tuple[list[Item], list[str]]:
    """Read the Held-out sets. Missing files are reported, never assumed empty."""
    items: dict[tuple[str, str], Item] = {}
    notes: list[str] = []
    for set_name, path in sources:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if not path.exists():
            notes.append(f"{set_name}: {rel} does not exist — 0 items from it")
            continue
        rows = _rows_from(path)
        added = 0
        for row in rows:
            stem = str(row.get("stem") or row.get("question") or row.get("prompt") or "")
            answer = str(row.get("answer") or "")
            options = [str(o) for o in row.get("options") or ()]
            whole = " ".join([stem, *options, answer]).strip()
            span = row.get("source_span") or {}
            item = Item(
                item_id=str(row.get("id", "")),
                set_name=set_name,
                stem=stem,
                answer=answer,
                whole=whole,
                origin=rel,
                source_chunk_id=str(
                    (span.get("chunk_id") if isinstance(span, dict) else "")
                    or row.get("chunk_id")
                    or ""
                ),
                source_page_id=str(row.get("source_id") or ""),
            )
            key = (item.set_name, item.item_id)
            existing = items.get(key)
            if existing is None:
                items[key] = item
                added += 1
            elif existing.whole != item.whole:
                notes.append(
                    f"{set_name} {item.item_id}: text differs between "
                    f"{existing.origin} and {rel} — two versions of one item"
                )
        notes.append(f"{set_name}: {len(rows)} row(s) in {rel}, {added} new")
    return sorted(items.values(), key=lambda i: (i.set_name, i.item_id)), notes


def _is_excluded(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in NOT_A_SURFACE)


def _readable(path: Path) -> str | None:
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    if b"\0" in blob[:8192]:
        return None
    return blob.decode("utf-8", "replace")


def split_jsonl_by_direction(
    rel: str, text: str, surface: str
) -> list[Document]:
    """One JSONL evidence file becomes two document streams: given, and returned.

    A line that is not JSON is graded whole, so a malformed record cannot hide
    in the ungraded half.
    """
    documents: list[Document] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            documents.append(Document(surface, f"{rel}:{number} (unparsed)", line))
            continue
        if not isinstance(record, dict):
            documents.append(Document(surface, f"{rel}:{number} (unparsed)", line))
            continue
        name = str(record.get("name") or record.get("run_type") or "")
        given: dict[str, Any] = {}
        returned: dict[str, Any] = {}
        for key, value in record.items():
            prompt_side = key in INPUT_KEYS or (
                key == "outputs" and name in PROMPT_SIDE_OUTPUT_NODES
            )
            (given if prompt_side else returned)[key] = value
        if given:
            documents.append(
                Document(surface, f"{rel}:{number} [given to a model]",
                         json.dumps(given, ensure_ascii=False))
            )
        if returned:
            documents.append(
                Document(RUN_EVIDENCE, f"{rel}:{number} [returned by a model]",
                         json.dumps(returned, ensure_ascii=False))
            )
    return documents


def collect_file_documents(root: Path) -> tuple[list[Document], list[str]]:
    """Resolve every surface's globs against the working tree.

    Files are assigned to the first surface that claims them, so the catch-all
    `speedrun/**` picks up only what the named surfaces did not — which is what
    makes the "other" count meaningful rather than a duplicate of the rest.
    """
    documents: list[Document] = []
    claimed: set[str] = set()
    skipped: list[str] = []
    for surface in SURFACES:
        for glob in surface.globs:
            for path in sorted(root.glob(glob)):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if rel in claimed or _is_excluded(rel):
                    continue
                text = _readable(path)
                if text is None:
                    skipped.append(rel)
                    claimed.add(rel)
                    continue
                claimed.add(rel)
                if any(fnmatch.fnmatchcase(rel, g) for g in SPLIT_JSONL):
                    documents += split_jsonl_by_direction(rel, text, surface.name)
                else:
                    # A raw page file is named for its source_id, which is the
                    # provenance an item records.
                    provenance = (
                        path.stem if "corpus/raw/pages/" in rel else ""
                    )
                    documents.append(
                        Document(surface.name, rel, text, provenance)
                    )
    return documents, skipped


def collect_corpus_documents(index: Path) -> tuple[list[Document], list[str]]:
    """Chunks and pages out of the built index, read-only."""
    notes: list[str] = []
    if not index.exists():
        notes.append(f"corpus index absent: {index.relative_to(REPO_ROOT).as_posix()}")
        return [], notes
    uri = f"file:{index.as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    documents: list[Document] = []
    try:
        for chunk_id, text in con.execute("select chunk_id, text from chunk"):
            documents.append(
                Document("corpus chunks", f"chunk {chunk_id}", text, chunk_id)
            )
        chunks = len(documents)
        for source_id, title, text in con.execute(
            "select source_id, title, text from page"
        ):
            documents.append(
                Document(
                    "corpus chunks", f"page {source_id} ({title})", text, source_id
                )
            )
        notes.append(
            f"corpus index: {chunks} chunk(s) and {len(documents) - chunks} page(s)"
        )
    finally:
        con.close()
    return documents, notes


# --------------------------------------------------------------------------
# Check 1 — items against surfaces (pure: takes documents, returns findings)
# --------------------------------------------------------------------------


def scan_documents(
    items: Sequence[Item],
    documents: Iterable[Document],
    *,
    threshold: float = JACCARD_THRESHOLD,
    graded_surfaces: Sequence[str] | None = None,
    grade_own_source: bool = False,
) -> tuple[list[Finding], dict[str, SurfaceStats], list[tuple[str, str]]]:
    """Compare every item against every document. No sampling, no early exit."""
    prepared = [
        (
            item,
            kind,
            normalise(text),
            normalise(text).split(),
            shingles(normalise(text).split()),
        )
        for item in items
        for kind, text in item.needles()
    ]
    answers = [(item, normalise(item.answer)) for item in items]
    ids = [(item, normalise(item.item_id)) for item in items]

    findings: list[Finding] = []
    ungraded: list[tuple[str, str]] = []
    stats: dict[str, SurfaceStats] = {}

    for document in documents:
        stat = stats.setdefault(document.surface, SurfaceStats())
        hay_norm = normalise(document.text)
        hay_words = hay_norm.split()
        hay_shingles = shingles(hay_words)
        hay_positions = word_positions(hay_words)
        stat.documents += 1
        stat.words += len(hay_words)
        stat.comparisons += len(prepared)
        is_graded = graded_surfaces is None or document.surface in graded_surfaces

        for item, needle_norm in answers:
            if needle_norm and f" {needle_norm} " in f" {hay_norm} ":
                stat.answer_only_items.add(item.item_id)

        for item, id_norm in ids:
            if not id_norm or id_norm not in hay_norm:
                continue
            stat.id_only_items.add(item.item_id)
            message = (
                f"{item.set_name} {item.item_id}: item id appears in "
                f"{document.surface} / {document.label}"
            )
            # An id is not content. The manifest's ledger publishes every item
            # id and hash on purpose, precisely so a defect can be cited
            # without quoting the item — see `speedrun/eval/aicheck/grade.py`,
            # which names an item id in a comment explaining a rule change.
            # Grading that would punish the honest thing. The exception is the
            # corpus: an id in third-party textbook text would mean Speedrun's
            # own data had been written into the corpus, which no legitimate
            # process does, so there it is graded.
            if is_graded and document.surface == "corpus chunks":
                findings.append(Finding("held-out item in a surface", message))
            else:
                ungraded.append((document.surface, message))

        for item, kind, needle_norm, needle_words, needle_shingles in prepared:
            if not needle_norm:
                continue
            where = f"{document.label} vs {item.item_id} ({kind})"
            ancestral = not grade_own_source and item.is_own_source(document.provenance)
            if ancestral:
                # The item was made from this document. Measured and named, so
                # a gold pair that restates its source word for word shows up;
                # not graded, because "too close to its source" is the AI card
                # check's third bucket, not a leak.
                stat.ancestral_pairs += 1
                score = (
                    1.0
                    if needle_norm in hay_norm
                    else best_window_jaccard(needle_words, hay_words)
                )
                stat.ancestral_scores.append((score, where))
                continue
            if needle_norm in hay_norm:
                message = (
                    f"{item.set_name} {item.item_id}: {kind} appears verbatim "
                    f"(normalised exact match) in {document.surface} / "
                    f"{document.label}"
                )
                stat.matched_items.add(item.item_id)
                if is_graded:
                    findings.append(Finding("held-out item in a surface", message))
                else:
                    ungraded.append((document.surface, message))
                stat.max_containment = 1.0
                stat.max_containment_where = where
                stat.max_jaccard = 1.0
                stat.max_jaccard_where = where
                continue
            share = containment(needle_shingles, hay_shingles)
            if share > stat.max_containment:
                stat.max_containment = share
                stat.max_containment_where = where
            if share >= 0.05:
                # Diagnostic only, and skipped where nothing is shared: with
                # under 5% of an item's 5-grams present there is no run worth
                # reporting, and computing it for every pair dominates the run.
                run = longest_common_run(needle_words, hay_words, hay_positions)
                if run > stat.longest_run:
                    stat.longest_run = run
                    stat.longest_run_where = where
            if share < threshold:
                continue  # sound: no window can beat the whole document
            jaccard = best_window_jaccard(needle_words, hay_words)
            if jaccard > stat.max_jaccard:
                stat.max_jaccard = jaccard
                stat.max_jaccard_where = where
            if jaccard >= threshold:
                message = (
                    f"{item.set_name} {item.item_id}: {kind} is a near-copy "
                    f"(5-gram Jaccard {jaccard:.2f} >= {threshold}) of "
                    f"{document.surface} / {document.label}"
                )
                stat.matched_items.add(item.item_id)
                if is_graded:
                    findings.append(Finding("held-out item in a surface", message))
                else:
                    ungraded.append((document.surface, message))
    return findings, stats, ungraded


# --------------------------------------------------------------------------
# Checks 2-4 — pure functions over paths and contents, so the self-test can
# drive them with fabricated inputs and prove each arm fires.
# --------------------------------------------------------------------------


def check_licensed_absent(
    tracked: Iterable[str], ever_added: Iterable[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for label, paths in (("tracked now", tracked), ("added at any point", ever_added)):
        for path in sorted(set(paths)):
            for pattern, why in LICENSED_PATTERNS:
                if fnmatch.fnmatchcase(path, pattern):
                    findings.append(
                        Finding(
                            "licensed corpus in git",
                            f"{path} ({label}) matches {pattern} — {why}",
                        )
                    )
                    break
    return findings


def check_gitignore(lines: Iterable[str]) -> list[Finding]:
    present = {line.strip() for line in lines}
    return [
        Finding("gitignore rule removed", f".gitignore no longer contains {pattern}")
        for pattern in REQUIRED_GITIGNORE
        if pattern not in present
    ]


def check_no_api_keys(files: Iterable[tuple[str, str]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, text in files:
        for match in API_KEY_RE.finditer(text):
            secret = match.group(0)
            findings.append(
                Finding(
                    "API key in a tracked file",
                    f"{path}: {secret[:6]}… ({len(secret)} chars)",
                )
            )
    return findings


def check_no_deck_binaries(tracked: Iterable[str]) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    allowed: list[str] = []
    for path in sorted(set(tracked)):
        if not any(fnmatch.fnmatchcase(path, p) for p in DECK_PATTERNS):
            continue
        if path.startswith(tuple(UPSTREAM_FIXTURE_PREFIXES)):
            allowed.append(path)
            continue
        findings.append(
            Finding("deck or collection binary tracked", f"{path} is tracked by git")
        )
    return findings, allowed


# --------------------------------------------------------------------------
# git collectors
# --------------------------------------------------------------------------


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def git_tracked() -> list[str]:
    return [p for p in git("ls-files").splitlines() if p.strip()]


def git_ever_added() -> list[str]:
    """Every path added on any ref, including ones deleted again afterwards.

    `--no-renames` matters: with rename detection on, moving a file records an
    R and the destination path never appears as an addition, so a corpus file
    renamed into the tree would slip past. Turning it off records a rename as
    delete + add, which is the conservative reading for this question.
    """
    out = git(
        "log",
        "--all",
        "--no-renames",
        "--diff-filter=A",
        "--name-only",
        "--pretty=format:",
    )
    return [p for p in out.splitlines() if p.strip()]


def git_added_lines_under(prefix: str) -> list[tuple[str, str]]:
    """Every line ever *added* under a path prefix, for the secret scan.

    Scoped to speedrun/ so the history scan stays bounded; the tracked-file
    scan below covers the whole repository at HEAD. Both scopes are printed.
    """
    out = git(
        "log", "--all", "--no-renames", "-p", "--pretty=format:%H", "--", prefix
    )
    commit = ""
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line):
            commit = line[:9]
        elif line.startswith("+") and not line.startswith("+++"):
            rows.append((f"{prefix} history @{commit}", line[1:]))
    return rows


# --------------------------------------------------------------------------
# Self-test — a leakage check that has never failed is indistinguishable from
# one that cannot fail.
# --------------------------------------------------------------------------


def _one_word_changed(text: str) -> str:
    """Change exactly one word. A near-copy, not an exact copy.

    One word is the honest demonstration: changing a word kills the (at most)
    five 5-grams that contain it, so a ~30-word stem keeps about 21 of 26 and
    scores Jaccard ~0.68 — over the 0.6 line, and demonstrably not an exact
    match. Two scattered changes would fall under the line, which is the real
    sensitivity of the rule the test plan fixed, and is stated rather than
    engineered around.
    """
    words_ = text.split()
    for index in range(len(words_) - 1, -1, -1):
        if words_[index].isalpha() and len(words_[index]) > 3:
            words_[index] = "notwithstanding"
            break
    return " ".join(words_)


def run_self_test(items: Sequence[Item], out: io.TextIOBase) -> bool:
    """Inject known leaks and assert the checker fails on each."""
    results: list[tuple[bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append((passed, f"{name}{(' — ' + detail) if detail else ''}"))

    if not items:
        check("self-test can run", False, "no Held-out items loaded")
        _print_self_test(results, out)
        return False

    victim = max(items, key=lambda i: len(i.stem.split()))
    prompt_file = REPO_ROOT / "speedrun" / "agent" / "speedrun_agent" / "generators.py"
    if not prompt_file.exists():
        check("prompt file to copy exists", False, str(prompt_file))
        _print_self_test(results, out)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        target = temp_root / "generators.py"
        shutil.copy2(prompt_file, target)
        clean_text = target.read_text(encoding="utf-8")

        # 1. Negative control. Without it, "it failed" proves nothing.
        control = [Document("generation prompts", "generators.py (copy)", clean_text)]
        findings, _, _ = scan_documents(items, control)
        check(
            "negative control: unmodified prompt copy is clean",
            not findings,
            f"{len(findings)} finding(s)" if findings else "",
        )

        # 2. Verbatim injection into a real prompt file on disk.
        target.write_text(
            clean_text + f'\n\nLEAKED_PROMPT = """{victim.stem}"""\n', encoding="utf-8"
        )
        injected = [
            Document(
                "generation prompts",
                "generators.py (copy, item injected)",
                target.read_text(encoding="utf-8"),
            )
        ]
        findings, _, _ = scan_documents(items, injected)
        hit = any(victim.item_id in f.detail for f in findings)
        check(
            "verbatim item injected into a prompt file is caught",
            hit,
            f"{len(findings)} finding(s), {victim.item_id} flagged" if hit else "MISSED",
        )

        # 3. Near-copy injection — the Jaccard arm, with the exact arm ruled out.
        near = _one_word_changed(victim.stem)
        near_doc = [
            Document("generation prompts", "generators.py (copy, near-copy)",
                     clean_text + f'\n\nLEAKED_PROMPT = """{near}"""\n')
        ]
        findings, stats, _ = scan_documents(items, near_doc)
        hit = any(victim.item_id in f.detail for f in findings)
        exact = any("verbatim" in f.detail for f in findings)
        jaccard = stats["generation prompts"].max_jaccard
        check(
            "one-word-changed near-copy is caught by the Jaccard arm",
            hit and not exact,
            f"Jaccard {jaccard:.2f} >= {JACCARD_THRESHOLD}, exact-match arm silent"
            if hit and not exact
            else "MISSED",
        )

        # 4. Injection into a corpus chunk, not just a file.
        chunk_doc = [
            Document("corpus chunks", "chunk fake-0000 (item injected)", victim.stem)
        ]
        findings, _, _ = scan_documents(items, chunk_doc)
        check(
            "item injected into a corpus chunk is caught",
            any(victim.item_id in f.detail for f in findings),
        )

        # 5. Bare answer alone is *not* a finding — the line this check draws.
        answer_doc = [
            Document(
                "corpus chunks",
                "chunk fake-0001 (bare answers only)",
                " ".join(sorted({i.answer for i in items})),
            )
        ]
        findings, stats, _ = scan_documents(items, answer_doc)
        seen = len(stats["corpus chunks"].answer_only_items)
        check(
            "bare answer strings alone are not a finding",
            not findings and seen > 0,
            f"{seen} answer(s) present, {len(findings)} finding(s)",
        )

        # 6. The direction split — the most contestable choice in this file, so
        #    it is tested in both directions rather than argued for in prose.
        stem_json = json.dumps(victim.stem)[1:-1]
        as_input = (
            '{"name": "generate", "run_type": "llm", '
            f'"inputs": {{"passages": "{stem_json}"}}, "outputs": {{"proposed": true}}}}'
        )
        as_output = (
            '{"name": "generate", "run_type": "llm", '
            f'"inputs": {{"seed": 0}}, "outputs": {{"stem": "{stem_json}"}}}}'
        )
        as_retrieved = (
            '{"name": "retrieve", "run_type": "retriever", "inputs": {"topic_id": "1A"},'
            f' "outputs": {{"chunk": "{stem_json}"}}}}'
        )
        docs = split_jsonl_by_direction("trace.jsonl", as_input, "generation prompts")
        findings, _, _ = scan_documents(items, docs, graded_surfaces=("generation prompts",))
        check(
            "an item fed back in as prompt input is caught",
            any(victim.item_id in f.detail for f in findings),
        )
        docs = split_jsonl_by_direction("trace.jsonl", as_output, "generation prompts")
        findings, _, ungraded_ = scan_documents(
            items, docs, graded_surfaces=("generation prompts",)
        )
        check(
            "the same item on the output side is reported, not graded",
            not findings and any(victim.item_id in m for _, m in ungraded_),
            f"{len(ungraded_)} reported match(es), 0 findings",
        )
        docs = split_jsonl_by_direction("trace.jsonl", as_retrieved, "generation prompts")
        findings, _, _ = scan_documents(
            items, docs, graded_surfaces=("generation prompts",)
        )
        check(
            "a retriever's output is graded as prompt input",
            any(victim.item_id in f.detail for f in findings),
            "retrieved passages are what the prompt is formatted with",
        )

        # 7. The own-source exclusion is exactly one chunk wide. An item
        #    injected into a chunk it did NOT declare is still a finding; the
        #    same text in the chunk it did declare is measured, not graded.
        sourced = next((i for i in items if i.source_chunk_id), None)
        if sourced is None:
            check("an item declares a source chunk", False, "none do")
        else:
            own = [
                Document(
                    "corpus chunks",
                    f"chunk {sourced.source_chunk_id}",
                    sourced.stem,
                    sourced.source_chunk_id,
                )
            ]
            findings, own_stats, _ = scan_documents(items, own)
            check(
                "an item inside its own declared source chunk is not graded",
                not findings and own_stats["corpus chunks"].ancestral_pairs > 0,
                f"{own_stats['corpus chunks'].ancestral_pairs} pair(s) measured",
            )
            findings, _, _ = scan_documents(items, own, grade_own_source=True)
            check(
                "--strict-provenance grades that same pair",
                any(sourced.item_id in f.detail for f in findings),
            )
            foreign = [
                Document(
                    "corpus chunks",
                    "chunk some-other-chunk#0-100",
                    sourced.stem,
                    "some-other-chunk#0-100",
                )
            ]
            findings, _, _ = scan_documents(items, foreign)
            check(
                "the same item in a chunk it did not declare is still caught",
                any(sourced.item_id in f.detail for f in findings),
                "the exclusion cannot be widened by moving the text",
            )

    # 8-10. The licensed-corpus arms, including the deleted-again case.
    findings = check_licensed_absent(["speedrun/eval/holdout/h1_reviews.jsonl"], [])
    check("licensed corpus tracked now is caught", len(findings) == 1)
    findings = check_licensed_absent([], ["speedrun/eval/corpus/revlogs-000.parquet"])
    check(
        "licensed corpus added then deleted is still caught",
        len(findings) == 1,
        "history arm fires on a path absent from the working tree",
    )
    check("clean input produces no licensed finding",
          not check_licensed_absent(["speedrun/eval/holdout/MANIFEST.md"], ["README.md"]))

    # 8. The .gitignore arm.
    check("a removed .gitignore rule is caught",
          len(check_gitignore([REQUIRED_GITIGNORE[0]])) == len(REQUIRED_GITIGNORE) - 1)

    # 9. The secret arm. The key is built at runtime so this file contains no
    #    string that would match the pattern it defines.
    fake_key = "sk-" + "Ab3" * 11
    findings = check_no_api_keys([("fake_config.py", f'API_KEY = "{fake_key}"')])
    check("an API key in a tracked file is caught", len(findings) == 1)
    check(
        "hyphenated words are not mistaken for keys",
        not check_no_api_keys([("notes.md", "task-oriented risk-adjusted sk-2")]),
    )

    # 10. The deck-binary arm, and the upstream allowlist it deliberately keeps.
    findings, allowed = check_no_deck_binaries(
        ["speedrun/eval/deck/miledown.apkg", "pylib/tests/support/media.apkg"]
    )
    check(
        "a Speedrun deck binary is caught, upstream fixtures are allowed",
        len(findings) == 1 and allowed == ["pylib/tests/support/media.apkg"],
    )

    return _print_self_test(results, out)


def _print_self_test(results: Sequence[tuple[bool, str]], out: io.TextIOBase) -> bool:
    print("\nSELF-TEST — can this check fail?", file=out)
    for passed, name in results:
        print(f"  {'pass' if passed else 'FAIL'}  {name}", file=out)
    ok = all(passed for passed, _ in results)
    passed_n = sum(1 for p, _ in results if p)
    print(
        f"  {passed_n}/{len(results)} self-test assertions passed"
        + ("" if ok else "  <-- the check itself is broken"),
        file=out,
    )
    return ok


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", help="also write everything printed to this file")
    parser.add_argument("--json", dest="json_path", help="write the report as JSON")
    parser.add_argument(
        "--no-self-test",
        action="store_true",
        help="skip the injection self-test (a clean run without it proves less)",
    )
    parser.add_argument(
        "--self-test-only", action="store_true", help="run only the self-test"
    )
    parser.add_argument(
        "--strict-provenance",
        action="store_true",
        help="also grade each item against the source chunk it declares it was "
        "drawn from (measured and printed either way)",
    )
    parser.add_argument(
        "--require-h3",
        action="store_true",
        help="fail if the H3 gold set does not exist yet (it is PENDING at T-07)",
    )
    args = parser.parse_args(argv)

    buffer = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, text: str) -> int:  # type: ignore[override]
            sys.stdout.write(text)
            buffer.write(text)
            return len(text)

    out = Tee()
    report: dict[str, Any] = {"checks": {}}

    print("Speedrun leakage check", file=out)
    print(f"repo: {REPO_ROOT}", file=out)
    print(f"rule: normalised exact match, or {N_GRAM}-gram Jaccard >= "
          f"{JACCARD_THRESHOLD} against a window sized to the item", file=out)

    items, notes = load_items(ITEM_SOURCES)
    print("\nHeld-out items loaded", file=out)
    for note in notes:
        print(f"  {note}", file=out)
    by_set: dict[str, int] = {}
    for item in items:
        by_set[item.set_name] = by_set.get(item.set_name, 0) + 1
    print(f"  total: {len(items)} item(s) — "
          + ", ".join(f"{k} {v}" for k, v in sorted(by_set.items())), file=out)
    report["items"] = {"total": len(items), "by_set": by_set, "notes": notes}

    findings: list[Finding] = []

    if args.self_test_only:
        return 0 if run_self_test(items, out) else 1

    self_test_ok = True
    if not args.no_self_test:
        self_test_ok = run_self_test(items, out)
        report["self_test_passed"] = self_test_ok
    else:
        report["self_test_passed"] = None
        print("\nSELF-TEST skipped (--no-self-test)", file=out)

    if not items:
        print("\nNOTHING CHECKED — no Held-out items exist. Not 'clean'.", file=out)
        _flush(args, buffer, report)
        return 2

    if by_set.get("H3", 0) == 0:
        message = (
            "H3 (AI-card gold set) does not exist yet — the manifest records it "
            "as PENDING until T-07 lands the source. The H3 arm of check 1 is "
            "vacuous: 0 items checked. Re-run with --require-h3 once it exists."
        )
        print(f"\n  NOTE: {message}", file=out)
        report["h3_pending"] = message
        if args.require_h3:
            findings.append(Finding("H3 missing", message))

    # --- check 1 ---------------------------------------------------------
    print("\n[1/4] Held-out items in prompts, corpus chunks, coaching material",
          file=out)
    file_docs, skipped = collect_file_documents(REPO_ROOT)
    corpus_docs, corpus_notes = collect_corpus_documents(CORPUS_INDEX)
    documents = file_docs + corpus_docs
    for note in corpus_notes:
        print(f"  {note}", file=out)
    if skipped:
        print(f"  {len(skipped)} binary file(s) under speedrun/ skipped: "
              f"{', '.join(skipped[:4])}{' …' if len(skipped) > 4 else ''}", file=out)
    graded = tuple(s.name for s in SURFACES if s.graded)
    scan_findings, stats, ungraded = scan_documents(
        items,
        documents,
        graded_surfaces=graded,
        grade_own_source=args.strict_provenance,
    )
    findings += scan_findings

    print(f"\n  {'surface':<38}{'docs':>7}{'words':>10}{'compares':>10}"
          f"{'items hit':>11}{'max cont':>10}{'max Jac':>9}{'run':>6}", file=out)
    surface_report: dict[str, Any] = {}
    for surface in SURFACES:
        stat = stats.get(surface.name)
        if stat is None:
            print(f"  {surface.name:<38}{'0':>7}   (nothing found to search)", file=out)
            surface_report[surface.name] = {"documents": 0}
            continue
        print(
            f"  {surface.name:<38}{stat.documents:>7}{stat.words:>10}"
            f"{stat.comparisons:>10}"
            f"{f'{len(stat.matched_items)}/{len(items)}':>11}"
            f"{stat.max_containment:>10.3f}"
            f"{stat.max_jaccard:>9.3f}{stat.longest_run:>6}"
            + ("" if surface.graded else "   (reported, not graded)"),
            file=out,
        )
        surface_report[surface.name] = {
            "graded": surface.graded,
            "why": surface.why,
            "documents": stat.documents,
            "words": stat.words,
            "item_document_comparisons": stat.comparisons,
            "items_matched": sorted(stat.matched_items),
            "items_whose_id_appears": len(stat.id_only_items),
            "max_5gram_containment": round(stat.max_containment, 4),
            "max_containment_at": stat.max_containment_where,
            "max_window_jaccard": round(stat.max_jaccard, 4),
            "longest_verbatim_word_run": stat.longest_run,
            "longest_run_at": stat.longest_run_where,
            "items_whose_bare_answer_appears": len(stat.answer_only_items),
            "own_source_pairs_excluded": stat.ancestral_pairs,
        }
    report["checks"]["items_in_surfaces"] = surface_report

    corpus = stats.get("corpus chunks", SurfaceStats())
    top = sorted(corpus.ancestral_scores, reverse=True)[:5]
    print(f"\n  own-source overlap — {corpus.ancestral_pairs} (item, declared "
          "source) pair(s) measured, not graded:", file=out)
    for score, where in top:
        print(f"    {score:>5.2f}  {where}", file=out)
    if top and top[0][0] >= JACCARD_THRESHOLD:
        print("    the top pair(s) are at or above the near-copy line against "
              "their OWN source. That is not Leakage — nothing reached anywhere "
              "it should not — but an item that restates its source almost word "
              "for word makes the AI card check easier than it should be, and "
              "belongs in that check's 'correct but bad teaching' bucket. Named "
              "here so it is not lost. Re-run with --strict-provenance to grade "
              "these too.", file=out)
    report["checks"]["own_source_overlap"] = {
        "pairs_measured": corpus.ancestral_pairs,
        "graded": args.strict_provenance,
        "top": [{"jaccard": round(s, 4), "pair": w} for s, w in top],
    }

    print("\n  bare answer strings (expected, never a finding):", file=out)
    for surface in SURFACES:
        stat = stats.get(surface.name)
        if stat and stat.answer_only_items:
            print(f"    {surface.name}: {len(stat.answer_only_items)}/{len(items)} "
                  "item answers present as ordinary terminology", file=out)
    print("    the Generation gate requires each answer to be a span copied "
          "verbatim from a chunk, so corpus overlap here is the gate working", file=out)

    given = stats.get("generation prompts", SurfaceStats())
    returned = stats.get(RUN_EVIDENCE, SurfaceStats())
    print("\n  the two numbers this check exists to separate:", file=out)
    print(f"    given to a model   : {len(given.matched_items)}/{len(items)} items "
          f"appear in the input side of a prompt, prompt template or trace record",
          file=out)
    print(f"    returned by a model: {len(returned.matched_items)}/{len(items)} items "
          f"appear in the output side of the run that produced them", file=out)
    print("    the second number is provenance and is expected to be high — an "
          "item has to come from somewhere, and this is where. The first is the "
          "one that must be zero.", file=out)
    report["checks"]["direction"] = {
        "items_on_prompt_input_side": sorted(given.matched_items),
        "items_on_model_output_side": sorted(returned.matched_items),
        "total_items": len(items),
    }

    if ungraded:
        by_surface: dict[str, int] = {}
        for surface_name, _ in ungraded:
            by_surface[surface_name] = by_surface.get(surface_name, 0) + 1
        print(f"\n  {len(ungraded)} match(es) in ungraded surfaces "
              "(run evidence and write-ups — provenance and publication, "
              "not Leakage):", file=out)
        for key, count in sorted(by_surface.items()):
            print(f"    {count:>5}  {key}", file=out)
        for _, message in ungraded[:5]:
            print(f"    e.g. {message}", file=out)
    report["checks"]["ungraded_matches"] = [
        {"surface": s_, "match": m} for s_, m in ungraded
    ]

    total_docs = sum(s.documents for s in stats.values())
    total_cmp = sum(s.comparisons for s in stats.values())
    print(f"\n  {len(items)} item(s) x {total_docs} document(s) = "
          f"{total_cmp} item-document comparisons, "
          f"{len(scan_findings)} finding(s)", file=out)

    # --- check 2 ---------------------------------------------------------
    print("\n[2/4] Licensed calibration corpus absent from git history", file=out)
    tracked = git_tracked()
    ever_added = git_ever_added()
    licensed = check_licensed_absent(tracked, ever_added)
    findings += licensed
    gitignore_lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ignore_findings = check_gitignore(gitignore_lines)
    findings += ignore_findings
    print(f"  {len(tracked)} path(s) tracked at HEAD", file=out)
    print(f"  {len(set(ever_added))} distinct path(s) ever added on any ref "
          "(git log --all --no-renames --diff-filter=A)", file=out)
    print(f"  {len(LICENSED_PATTERNS)} forbidden pattern(s) checked against both",
          file=out)
    print(f"  {len(REQUIRED_GITIGNORE)} required .gitignore rule(s): "
          f"{len(REQUIRED_GITIGNORE) - len(ignore_findings)} present", file=out)
    print(f"  {len(licensed) + len(ignore_findings)} finding(s)", file=out)
    report["checks"]["licensed_corpus"] = {
        "tracked_paths": len(tracked),
        "paths_ever_added": len(set(ever_added)),
        "patterns": [p for p, _ in LICENSED_PATTERNS],
        "gitignore_rules_present": len(REQUIRED_GITIGNORE) - len(ignore_findings),
        "findings": [f.detail for f in licensed + ignore_findings],
    }

    # --- check 3 ---------------------------------------------------------
    print("\n[3/4] No API key in any tracked file", file=out)
    pairs: list[tuple[str, str]] = []
    binary = 0
    for rel in tracked:
        text = _readable(REPO_ROOT / rel)
        if text is None:
            binary += 1
            continue
        pairs.append((rel, text))
    history_lines = git_added_lines_under("speedrun")
    key_findings = check_no_api_keys(pairs) + check_no_api_keys(history_lines)
    findings += key_findings
    print(f"  {len(pairs)} tracked text file(s) read in full "
          f"({binary} binary/unreadable skipped)", file=out)
    print(f"  {len(history_lines)} line(s) ever added under speedrun/ on any ref, "
          "also scanned", file=out)
    print(f"  pattern: {API_KEY_RE.pattern}", file=out)
    print(f"  {len(key_findings)} finding(s)", file=out)
    report["checks"]["api_keys"] = {
        "tracked_text_files_scanned": len(pairs),
        "binary_files_skipped": binary,
        "history_lines_scanned": len(history_lines),
        "findings": [f.detail for f in key_findings],
    }

    # --- check 4 ---------------------------------------------------------
    print("\n[4/4] No deck or collection binary tracked", file=out)
    deck_findings, allowed = check_no_deck_binaries(tracked)
    findings += deck_findings
    print(f"  {len(tracked)} tracked path(s) matched against "
          f"{len(DECK_PATTERNS)} extension(s)", file=out)
    print(f"  0 under speedrun/" if not deck_findings else
          f"  {len(deck_findings)} outside the upstream allowlist", file=out)
    print(f"  {len(allowed)} upstream Anki test fixture(s) allowed and named:", file=out)
    for path in allowed:
        print(f"    {path}", file=out)
    print(f"  {len(deck_findings)} finding(s)", file=out)
    report["checks"]["deck_binaries"] = {
        "tracked_paths": len(tracked),
        "extensions": list(DECK_PATTERNS),
        "upstream_fixtures_allowed": allowed,
        "findings": [f.detail for f in deck_findings],
    }

    # --- verdict ---------------------------------------------------------
    print("\n" + "-" * 72, file=out)
    if findings:
        print(f"LEAKED — {len(findings)} finding(s):", file=out)
        for finding in findings:
            print(f"  [{finding.check}] {finding.detail}", file=out)
        code = 1
    elif not self_test_ok:
        print("BROKEN — no findings, but the self-test failed, so a clean result "
              "here means nothing.", file=out)
        code = 1
    else:
        print(
            f"CLEAN — {len(items)} Held-out item(s) checked against {total_docs} "
            f"document(s) ({total_cmp} comparisons) and {len(tracked)} tracked "
            f"path(s); {len(set(ever_added))} path(s) ever added on any ref "
            "checked for the licensed corpus. Self-test proved the check fails "
            "when a leak is injected.",
            file=out,
        )
        code = 0
    report["exit_code"] = code
    report["findings"] = [dataclasses.asdict(f) for f in findings]
    _flush(args, buffer, report)
    return code


def _flush(args: argparse.Namespace, buffer: io.StringIO, report: dict[str, Any]) -> None:
    if args.log:
        Path(args.log).write_text(buffer.getvalue(), encoding="utf-8")
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

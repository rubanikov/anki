# Corpus

What the **generation gate** checks answers against.

A generated **held-out item** ships only if the supporting text for its correct
answer was retrieved from a real source and matched against it. That assertion
is only worth making at span level: "chapter 3 covers enzyme inhibition" is not
evidence that any particular sentence about enzyme inhibition was ever written
down. So everything here is built around one question — *where exactly does this
claim come from, and can someone else check?*

Two things are ingested:

1. **The AAMC content outline** — all 31 content categories, structured
   (`outline.json`). This is the **Outline** every **Topic** refers to.
2. **One OpenStax textbook for the demo section (Bio/Biochem)** — chunked,
   sanitized, indexed, and attributed to content categories where that can be
   done honestly.

---

## What was ingested

### The Outline — `outline.json`

| Section | Content categories | Topic lists captured |
| --- | --- | --- |
| BB — Biological and Biochemical Foundations of Living Systems | 9 | yes |
| CP — Chemical and Physical Foundations of Biological Systems | 10 | titles only |
| PS — Psychological, Social, and Biological Foundations of Behavior | 12 | titles only |
| CARS | 0 by AAMC's own account | n/a |

**Provenance.** Section names, all ten foundational concept statements and all
31 content category titles were read off AAMC's own pages on
`students-residents.aamc.org` — not recalled and not taken from a prep-company
transcription. The per-category topic lists (AAMC's itemised "Amino Acids (BC,
OC) → Absolute configuration at the α position → …") were fetched for the nine
Bio/Biochem categories only, because that is the section this corpus indexes.

**Transcription risk, stated.** The pages were rendered to text before being
read. Identifiers, titles, counts and section membership are reliable and are
checked on load (`outline.py` refuses to load an Outline that is not 9 / 10 / 12).
What is *not* reliable is deep bullet nesting: AAMC's third-level bullets were
folded into their parent's `subtopics` list, so a subtopic string here sometimes
holds what AAMC printed as two levels. Nothing in this repo depends on that
nesting, and the topic lists are used for one thing only — arguing about
attribution in `attribution.json`, where a human reads them.

The Outline is AAMC's, reproduced at the level of identifiers and titles as the
external authority coverage is measured against. It is not ours and is not
relicensed by this repository.

### The book — OpenStax *Biology*, 1st edition

| | |
| --- | --- |
| Title | *Biology* (1st edition) |
| Publisher | OpenStax, Rice University |
| Book UUID | `185cbf87-c72e-48f5-b51e-f14f21b5eabd` @ `e989ec3` |
| **Licence** | **CC BY 4.0** — https://creativecommons.org/licenses/by/4.0/ |
| Source | OpenStax REX archive, `https://openstax.org/apps/archive/<version>/contents/…` |
| Attribution | *Biology*, OpenStax, Rice University. Access for free at https://openstax.org/books/biology/pages/1-introduction. Licensed CC BY 4.0. |

**What is actually verified about the licence.** The book ingested here is
OpenStax *Biology*, 1st edition, uuid `185cbf87-…`, and **OpenStax's own archive
API reported its licence as `Creative Commons Attribution License`,
`creativecommons.org/licenses/by/4.0/`, at download time**. That response is
recorded verbatim in `raw/manifest.json` under `license_reported_by_source`, and
`fetch.py` refuses to ingest anything the source does not report as CC BY 4.0.
This is the claim the corpus rests on and it is checked against the source
rather than remembered.

**Why the 1st edition and not *Biology 2e* — corrected.** An earlier draft of
this file asserted that *Biology 2e*, *Concepts of Biology*, *Microbiology*,
*Chemistry 2e* and *Anatomy and Physiology 2e* are CC BY-NC-SA 4.0. **That claim
was never verified against any of those books and appears to be wrong** —
third-party catalogues list *Biology 2e* as CC BY 4.0. It has been removed
rather than left standing, because a licence claim about five books we did not
fetch is exactly the kind of confident-but-unchecked statement this project
exists to refuse.

The honest reason for the 1st edition is narrower: it is the edition that was
fetched, and its licence was confirmed from the source. If a later ticket wants
2e, the only correct way to adopt it is to fetch it and read the licence the
archive reports, the same way this one did.

**What was fetched:** 350 content pages. **What was not:** 143 assessment and
front/back-matter pages — Review Questions, Critical Thinking Questions, Visual
Connection Questions, Preface, Index. Published exam-style questions are exactly
what a generator would produce near-copies of, which is both a leakage problem
and a plagiarism one. The corpus holds expository prose, Key Terms and Chapter
Summaries.

---

## Numbers from the last build

```
pages:        350 indexed, 143 excluded as assessment
chunks:       3021
attributed:   1651 (54%)
unattributed: 1370 (46%)
chunk length: median 1093 chars, p05 168, p95 1808, max 3016

removed structurally: 754 script/style elements, 111 HTML comments,
                      0 hidden elements, 0 invisible characters
quarantined blocks:   0
```

| Topic | Chunks | Topic | Chunks |
| --- | ---: | --- | ---: |
| 1A Proteins and amino acids | 31 | 2B Prokaryotes and viruses | 147 |
| 1B Gene to protein | 217 | 2C Cell division and differentiation | 133 |
| 1C Heritable information | 240 | 3A Nervous and endocrine systems | 213 |
| 1D Bioenergetics and metabolism | 119 | 3B Main organ systems | 440 |
| 2A Molecular and cellular assemblies | 152 | | |

All nine Bio/Biochem categories have chunks. **1A is thin at 31** — the book
covers it in two sections (3.4 Proteins, 6.5 Enzymes) and nowhere else, so
category-filtered retrieval for 1A has a much shallower pool than for 3B. That
is a property of the book, not a bug in the map, and it is the number to watch
if 1A **Yield** comes out low.

**Zero blocks were quarantined from the real book.** OpenStax is a clean source;
the injection screen earns its place against the fixture, not against Rice
University. The 754 removed script and style elements are OpenStax's own
developer tooling, which every page ships.

---

## How a span is located

Retrieval returns a citation, not a paragraph.

Each page is parsed into **blocks** — paragraphs, headings, list items, captions
— each keeping the `id` attribute OpenStax already puts on it (`fs-id1266915`).
Surviving blocks are joined into one **page text**, which is stored in the index.
A **chunk** is a whole number of consecutive blocks, and carries:

- `source_id` — the page UUID
- `char_start` / `char_end` — offsets into that page's text
- `blocks` — each block's id and its own offsets
- `heading_path` — e.g. `("3.4 Proteins", "Amino Acids")`
- the page's URL and SHA-256

The chunker asserts `page_text[char_start:char_end] == chunk.text` on
construction, so the offsets address the characters they claim to.

`spans.find_span(chunk, answer_text)` then searches inside a hit and returns a
`Span` with **page-level** offsets, the **source's own characters** as the quote,
and the id of the enclosing block. `spans.verify(span, page_text)` re-checks it.
The gate's whole question is one call:

```bash
python build.py --support "Competitive inhibition"
SHIP - supporting span found
  source  3270ba1a-e262-481e-9902-61ef811251d5[14268:14290]
  block   fs-id1596004
  quote   competitive inhibition
  verified True

python build.py --support "The Krebs cycle occurs in the peroxisome of prokaryotic cells"
DROP - no supporting span retrieved
```

Matching forgives whitespace, case and typography (an en dash in
"Michaelis–Menten" is not a difference of fact). It forgives nothing else — a
paraphrase has not *found* supporting text, it has *written* some. `support()`
returns `None` rather than a nearest match, because a nearest match is how an
unsupported claim acquires a citation.

---

## Sanitization

The threat is not malformed HTML. It is an author — or anyone able to serve or
mirror the source — writing instructions aimed at whatever reads the page next.
Retrieval hands those instructions to a generator with no marker saying they came
from the corpus rather than from us.

Two mechanisms, because the vectors differ in kind:

**Structural removal.** `<script>`, `<style>`, `<noscript>`, `<template>`,
`<iframe>`, HTML comments, *all attribute values* (an `alt` text is
attacker-controlled and is never harvested), elements hidden by
`display:none` / `visibility:hidden` / `opacity:0`, zero-width and bidi-control
characters, and the Unicode Tag block `U+E0000–E007F` — the invisible ASCII
alphabet. None of these has a reading under which it is prose a student studies,
so nothing is lost by never extracting them, and no detector is needed for a
channel that is closed.

**Quarantine.** Visible prose that reads as an instruction to a model is
*refused*, recorded with the pattern that caught it, and never indexed — nine
patterns, in `sanitize.INJECTION_PATTERNS`. It refuses rather than redacts: a
page that half-argues with its reader is not a page whose other half can be
trusted. It is never silent — `build.py` prints the count and `index.quarantine`
keeps the evidence, because a judgement call that can be wrong must be
reviewable.

A quarantined block is dropped **before the page text is assembled**, so there is
no offset that points at it. That is stronger than filtering it out of results.

Detection is a floor, not a wall. A sufficiently subtle instruction phrased as
biology will pass, and the honest mitigation is downstream: the gate matches
answers against retrieved spans, so a chunk that talks a generator into inventing
an answer still cannot produce a *supported* item.

### The poisoned-chunk test

`tests/fixtures/poisoned_page.xhtml` is a page shaped like an OpenStax section
carrying seven attack vectors: a stylesheet `content:` string, a script body, an
HTML comment, an `alt` attribute, a `display:none` paragraph, a paragraph
obfuscated with zero-width spaces, and a forged chat-template delimiter — plus
three real paragraphs of enzyme kinetics that must survive intact.

The test asserts at the **retrieval** seam, not at the sanitizer's own functions:
nothing an attacker wrote may be returned by a query against a built index, and
none of it may ever support an answer.

**Before the fix** — `sanitize.py` was first written the way most people write it,
stripping tags with a regex:

```
FAILED test_injected_text_is_not_in_any_chunk[chat_template]
FAILED test_injected_text_is_not_in_any_chunk[hidden_paragraph]
FAILED test_injected_text_is_not_in_any_chunk[script]
FAILED test_injected_text_is_not_in_any_chunk[stylesheet]
FAILED test_injected_text_is_not_in_any_chunk[visible_instruction]
FAILED test_injected_text_is_not_in_any_chunk[zero_width_obfuscated]
FAILED test_injected_text_is_not_retrievable[chat_template]
FAILED test_injected_text_is_not_retrievable[hidden_paragraph]
FAILED test_injected_text_is_not_retrievable[script]
FAILED test_injected_text_is_not_retrievable[stylesheet]
FAILED test_injected_text_is_not_retrievable[visible_instruction]
FAILED test_injected_text_is_not_retrievable[zero_width_obfuscated]
FAILED test_injected_text_can_never_support_an_answer
FAILED test_a_supporting_span_is_still_locatable
FAILED test_visible_instructions_are_quarantined_with_a_reason
FAILED test_the_three_visible_injections_are_each_quarantined
FAILED test_invisible_characters_never_reach_a_chunk
FAILED test_span_verification_rejects_a_tampered_quote
18 failed, 11 passed in 0.55s
```

**After the fix:**

```
$ python -m pytest tests/ -q
........................................................            [100%]
56 passed in 0.29s
```

---

## Rebuilding

Nothing generated is committed. Both directories are ignored and both are
reproducible from these scripts.

```bash
cd speedrun/corpus

python build.py --fetch        # download 350 pages into raw/   (~8 MB, once)
python build.py --build        # sanitize, chunk, attribute, index -> out/
python build.py --all          # both

python build.py --stats
python build.py --query "competitive inhibitor Km Vmax" --limit 3
python build.py --query "action potential" --category 3A
python build.py --support "Competitive inhibition"

python -m pytest tests/ -q     # no download needed; runs on fixtures
```

These are scripts in a checkout, not an installed package, so a caller — the
agent service in T-08 — puts this directory on the path and imports by name:

```python
sys.path.insert(0, ".../speedrun/corpus")
from index import CorpusIndex

with CorpusIndex.open(".../speedrun/corpus/out/index.sqlite3") as corpus:
    hits = corpus.search(question, categories=("1A",))       # retrieve
    span = corpus.support(answer, categories=("1A",))        # gate
    if span is None:
        drop(reason="no supporting span retrieved")
```

`{output, source_id, span}` — the triple the agent's graph state carries — comes
straight off a `Span`.

Stdlib only — no third-party dependency. Retrieval is BM25 over SQLite FTS5.
That is a deliberate floor rather than an aspiration: ADR-0006 judges retrieval
by **Yield** at a fixed gate, and a comparison needs an incumbent. An embedding
retriever can be added and measured against this on the same gate; until it is
measured, this is what ships.

| Path | Committed | What it is |
| --- | --- | --- |
| `outline.json` | yes | The 31 content categories. 36 KB. |
| `attribution.json` | yes | The hand-authored chunk→Topic map, with its reasoning. |
| `*.py`, `tests/` | yes | The build, the index, the span logic, the tests. |
| `raw/` | **no** | OpenStax downloads + `manifest.json`. ~8 MB. |
| `out/` | **no** | `index.sqlite3` (~11 MB) and `build_report.json`. |

`raw/manifest.json` pins the archive version actually used, so a later rebuild
fetches the same bytes rather than whatever OpenStax has published since.

### `.gitignore` entries this needs

```gitignore
# --- Speedrun corpus (T-07) — see speedrun/corpus/README.md ---
# OpenStax downloads. CC BY 4.0, so redistributable — but it is OpenStax's text,
# it is megabytes of it, and `python speedrun/corpus/build.py --fetch` reproduces
# it exactly from the archive version pinned in raw/manifest.json.
speedrun/corpus/raw/
# The built index (~11 MB of SQLite) and its build report. Rebuilt by
# `python speedrun/corpus/build.py --build`; a binary index in the history would
# be a second source of truth for what the gate checks against.
speedrun/corpus/out/
```

---

## Attribution, and where it stops

`attribution.json` maps the book's own structure — a section number, else a
chapter — onto content categories, first-match-wins. Every rule was written by
reading the OpenStax section title against AAMC's topic list for the candidate
category, and every rule carries a `confidence` and a `note` giving the reason.
Rules are validated on load: a rule naming a category the Outline does not have,
or naming a category outside Bio/Biochem, is an error rather than a warning.

Pages with no section number (Key Terms, Chapter Summary) inherit the chapter's
rule, except where a chunk's own heading names a section that has one — so the
chapter-6 summary paragraph on enzymes lands in 1A rather than in 1D with the
rest of chapter 6.

**Automatic attribution was considered and rejected.** Keyword scoring over the
AAMC topic lists attributes everything and is confident about all of it:
"Regulation of Body Processes" scores on *regulation* against 1D's metabolic
regulation, and photosynthesis scores on *electron transport chain* against 1D,
which the MCAT does not test. A wrong attribution is worse than none — it poisons
coverage and the retrieval filter at the same time, silently.

### Deliberately unattributed

46% of chunks carry no category. That is the design, not a shortfall:

- **Sensory reception (ch. 36).** The Outline puts *Sensing the environment* in
  **PS 6A**, outside the demo section, while BB 3A is nervous system structure.
  Filing a biology textbook's sensory chapters under a psychology category was
  judged unreliable, so nothing is claimed.
- **Lipid structure (3.3).** AAMC lists *Lipids: description; structure;
  steroids* under **3A**, next to the nervous and endocrine systems. That
  placement is real but reads as an error to anyone checking the map, so the
  section is left unattributed rather than filed somewhere indefensible.
- **General chemistry (ch. 1–2: atoms, water, carbon).** Belongs to CP 4E, 5A,
  5B. This corpus does not index Chem/Phys, and attributing a Bio book's chunks
  to CP would make a section look sourced by a book never ingested for it.
- **Photosynthesis (8), phylogenetics (20), biological diversity (23–32),
  ecology (44–47).** The Outline does not test them.
- **Genomics and proteomics (17.2, 17.4, 17.5).** 1B lists DNA sequencing and
  analysis of gene expression; these sections are mostly genome projects and
  bioinformatics, which it does not.

**Known thin spots in what *is* attributed.** The Outline's 3B lists a skin
system and a lymphatic system; *Biology* covers both only in passing inside
chapters 33 and 42, so retrieval for those topics will be shallow. Nothing was
misattributed to compensate.

---

## Deliberately absent

- **The other three sections' books.** Chem/Phys and Psych/Soc have no corpus.
  Breadth beyond the demo section is a stated cut, and the demo shows two
  sections abstaining — that contrast is the product's central behaviour, not a
  gap to be papered over with a book nobody has checked.
- **Any licensed prep material, question bank or video.** One bounded corpus,
  CC BY 4.0, or none.
- **Published exam-style questions from the book itself** — see above.
- **Embedding retrieval.** Not until it can be measured against BM25 on the same
  gate.
- **Any large binary in git.** The index is rebuilt, never committed.

#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Build the corpus index, and ask it questions.

    python build.py --fetch          download the book into raw/ (once)
    python build.py --build          parse, sanitize, chunk, attribute, index
    python build.py --all            both
    python build.py --stats          what is in the index now
    python build.py --query "..."    retrieve, with page offsets
    python build.py --support "..."  the gate's question: is this text sourced?

Nothing this writes is committed. `raw/` is the download, `out/` is the index and
the build report; both are ignored and both are reproducible from this script.
What commits is the code, `outline.json` and `attribution.json` - the parts a
reviewer has to argue with.

The build report is printed as well as written, because the two numbers worth
arguing about are how much got quarantined and how much went unattributed, and
neither should require opening a database to find.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import attribution
import chunker
import fetch
import sanitize
import spans
from index import CorpusIndex
from outline import load_outline

CORPUS_DIR = Path(__file__).resolve().parent
RAW_DIR = CORPUS_DIR / "raw"
OUT_DIR = CORPUS_DIR / "out"
INDEX_PATH = OUT_DIR / "index.sqlite3"
REPORT_PATH = OUT_DIR / "build_report.json"


def build_index(*, raw_dir: Path = RAW_DIR, index_path: Path = INDEX_PATH) -> dict:
    manifest = fetch.load_manifest(raw_dir)
    book = manifest["book"]
    corpus = CorpusIndex.create(index_path)

    removed_totals: dict[str, int] = {}
    quarantined: list[dict] = []
    chunk_count = 0
    attributed_chunks = 0
    per_category: dict[str, int] = {}
    unattributed_pages: list[str] = []

    for page in manifest["pages"]:
        content = fetch.page_content(page["page_id"], raw_dir)
        if not content:
            continue
        parsed = sanitize.parse_page(content)
        chunked = chunker.chunk_page(page["page_id"], parsed)

        for key, value in chunked.removed.items():
            removed_totals[key] = removed_totals.get(key, 0) + value
        for refused in chunked.quarantined:
            quarantined.append(
                {
                    "page": page["title"],
                    "page_id": refused.source_id,
                    "block_id": refused.block_id,
                    "finding": refused.finding,
                    "excerpt": refused.excerpt[:200],
                }
            )

        attributions = {
            chunk.chunk_id: attribution.attribute_chunk(
                page["chapter"], page["section"], chunk.heading_path
            )
            for chunk in chunked.chunks
        }
        if not any(a.is_attributed for a in attributions.values()):
            unattributed_pages.append(page["title"])
        for result in attributions.values():
            for category in result.categories:
                per_category[category] = per_category.get(category, 0) + 1
            attributed_chunks += int(result.is_attributed)
        chunk_count += len(chunked.chunks)

        corpus.add_page(
            chunked,
            book_id=book["book_id"],
            slug=page["slug"],
            title=page["title"],
            chapter=page["chapter"],
            section=page["section"],
            url=f"https://openstax.org/books/{book['rex_slug']}/pages/{page['slug']}",
            attribution=attributions,
        )

    outline = load_outline()
    missing = [
        category.id
        for category in outline.in_section("BB")
        if per_category.get(category.id, 0) == 0
    ]

    report = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "book": book,
        "archive_base": manifest["archive_base"],
        "pages_indexed": len(manifest["pages"]),
        "pages_excluded_as_assessment": manifest["excluded_count"],
        "chunks": chunk_count,
        "chunks_attributed": attributed_chunks,
        "chunks_unattributed": chunk_count - attributed_chunks,
        "chunks_per_category": dict(sorted(per_category.items())),
        "demo_section_categories_with_no_chunks": missing,
        "pages_unattributed": len(unattributed_pages),
        "removed_structurally": removed_totals,
        "quarantined_blocks": len(quarantined),
        "quarantine": quarantined,
        "known_gaps": list(attribution.load_rules().known_gaps),
    }

    corpus.set_meta(**{k: v for k, v in report.items() if k != "quarantine"})
    corpus.commit()
    corpus.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def print_report(report: dict) -> None:
    print(f"book:        {report['book']['title']} ({report['book']['edition']})")
    print(f"licence:     {report['book']['license_name']}")
    print(f"pages:       {report['pages_indexed']} indexed, "
          f"{report['pages_excluded_as_assessment']} excluded as assessment")
    print(f"chunks:      {report['chunks']}")
    print(f"attributed:  {report['chunks_attributed']} "
          f"({report['chunks_attributed'] * 100 // max(report['chunks'], 1)}%)")
    print(f"unattributed:{report['chunks_unattributed']}")
    print("per category:")
    for category, count in report["chunks_per_category"].items():
        print(f"  {category:<4} {count}")
    if report["demo_section_categories_with_no_chunks"]:
        print(f"  NO CHUNKS: {report['demo_section_categories_with_no_chunks']}")
    print(f"removed:     {report['removed_structurally']}")
    print(f"quarantined: {report['quarantined_blocks']} blocks")
    for entry in report["quarantine"][:10]:
        print(f"  [{entry['finding']}] {entry['page']} :: {entry['excerpt'][:90]}")


def show_stats(index_path: Path) -> None:
    with CorpusIndex.open(index_path) as corpus:
        stats = corpus.stats()
        for key in ("pages", "chunks", "chunks_attributed", "chunks_unattributed",
                    "quarantined_blocks"):
            print(f"{key:<22} {stats[key]}")
        print("chunks_by_category")
        for category, count in stats["chunks_by_category"].items():
            print(f"  {category:<4} {count}")


def run_query(index_path: Path, query: str, limit: int, categories) -> None:
    with CorpusIndex.open(index_path) as corpus:
        hits = corpus.search(query, limit=limit, categories=categories)
        if not hits:
            print("no hits")
            return
        for hit in hits:
            heading = " > ".join(hit.chunk.heading_path) or hit.page_title
            print(f"\n--- {hit.chunk.chunk_id}")
            print(f"    {heading}")
            print(f"    page {hit.source_id} chars "
                  f"{hit.chunk.char_start}-{hit.chunk.char_end}  "
                  f"score {hit.score:.2f}  "
                  f"categories {list(hit.categories) or 'unattributed'}")
            print(f"    {hit.url}")
            print(f"    {hit.text[:300]}...")


def run_support(index_path: Path, answer: str, categories) -> int:
    """Exactly what the generation gate asks, and what it does with the answer."""
    with CorpusIndex.open(index_path) as corpus:
        span = corpus.support(answer, categories=categories)
        if span is None:
            print("DROP - no supporting span retrieved")
            return 1
        page_text = corpus.page_text(span.source_id)
        print("SHIP - supporting span found")
        print(f"  source  {span.source_id}[{span.start}:{span.end}]")
        print(f"  block   {span.block_id}")
        print(f"  quote   {span.quote}")
        print(f"  verified {spans.verify(span, page_text)}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fetch", action="store_true", help="download the book")
    parser.add_argument("--build", action="store_true", help="build the index")
    parser.add_argument("--all", action="store_true", help="fetch then build")
    parser.add_argument("--stats", action="store_true", help="describe the index")
    parser.add_argument("--query", help="retrieve chunks for a query")
    parser.add_argument("--support", help="ask whether text is supported by a source")
    parser.add_argument("--category", action="append", help="restrict to a Topic")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args(argv)

    categories = tuple(args.category) if args.category else None

    if args.fetch or args.all:
        fetch.fetch_book(raw_dir=RAW_DIR)
    if args.build or args.all:
        print_report(build_index(index_path=args.index))
    if args.stats:
        show_stats(args.index)
    if args.query:
        run_query(args.index, args.query, args.limit, categories)
    if args.support:
        return run_support(args.index, args.support, categories)
    if not any(
        (args.fetch, args.build, args.all, args.stats, args.query, args.support)
    ):
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

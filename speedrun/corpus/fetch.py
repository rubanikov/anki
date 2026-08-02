# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Downloading the one book this corpus indexes.

Which book was a licence decision before it was a content decision. We ingest
OpenStax *Biology*, 1st edition, and the licence claim is not taken on trust:
the archive API's own `license` field is read at download time, recorded in
`raw/manifest.json`, and anything the source does not report as CC BY 4.0 is
refused. For this book it reported `creativecommons.org/licenses/by/4.0/`.

An earlier version of this docstring claimed *Biology 2e* and four other
OpenStax books are CC BY-NC-SA. That was never checked against those books and
appears to be wrong; it has been removed. Adopting 2e later means fetching it
and reading the licence the archive reports, exactly as this does.

Downloads land in `raw/`, which is ignored. Nothing here is committed: the
book is OpenStax's, it is a few tens of megabytes, and a rebuild from this
script reproduces it. `raw/manifest.json` pins the archive version actually
used, so a later rebuild fetches the same bytes rather than whatever OpenStax
has published since.

Assessment pages are not downloaded. Review questions, critical-thinking
questions and visual-connection questions are published exam-style items, and a
generator retrieving over them would produce near-copies of somebody else's
questions - which is both a leakage problem and a plagiarism one. The corpus
holds expository prose, key terms and chapter summaries.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
RAW_DIR = CORPUS_DIR / "raw"

RELEASE_URL = "https://openstax.org/rex/release.json"
USER_AGENT = "speedrun-corpus/1.0 (MCAT readiness research; contact via repo)"


@dataclasses.dataclass(frozen=True)
class Book:
    book_id: str
    title: str
    edition: str
    uuid: str
    version: str
    rex_slug: str
    license_name: str
    license_url: str
    attribution: str

    def page_url(self, slug: str) -> str:
        return f"https://openstax.org/books/{self.rex_slug}/pages/{slug}"


#: The single book in the corpus. Breadth beyond the demo section is out of
#: scope for this ticket, and adding a second book means repeating the licence
#: check above, not just adding a uuid.
BIOLOGY_1E = Book(
    book_id="openstax-biology-1e",
    title="Biology",
    edition="1st edition",
    uuid="185cbf87-c72e-48f5-b51e-f14f21b5eabd",
    version="e989ec3",
    rex_slug="biology",
    license_name="Creative Commons Attribution 4.0 International (CC BY 4.0)",
    license_url="https://creativecommons.org/licenses/by/4.0/",
    attribution=(
        "Biology, OpenStax, Rice University. Access for free at "
        "https://openstax.org/books/biology/pages/1-introduction. "
        "Licensed CC BY 4.0."
    ),
)

#: Page titles that are assessment or front/back matter rather than content.
EXCLUDED_TITLE_PATTERNS = (
    r"^review questions$",
    r"^critical thinking questions$",
    r"^visual connection questions$",
    r"^test prep",
    r"^science practice",
    r"^preface$",
    r"^index$",
    r"^answer key$",
    r"^references$",
    r"^the periodic table of elements$",
    r"^measurements and the metric system$",
    r"^geological time$",
)
_EXCLUDED = tuple(re.compile(p, re.IGNORECASE) for p in EXCLUDED_TITLE_PATTERNS)

_TAGS = re.compile(r"<[^>]+>")


@dataclasses.dataclass(frozen=True)
class PageRef:
    """One page of the book, as the table of contents describes it."""

    page_id: str  # bare uuid, no version suffix
    title: str
    slug: str
    chapter: str  # "3", or "" for unnumbered pages
    section: str  # "3.4", or "" for Key Terms and the like
    unit_title: str
    chapter_title: str

    @property
    def is_excluded(self) -> bool:
        return any(pattern.match(self.title) for pattern in _EXCLUDED)


def _plain(title: str) -> str:
    return " ".join(_TAGS.sub(" ", title).split())


def _get(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def _get_json(url: str) -> dict:
    return json.loads(_get(url))


def archive_base() -> str:
    """The archive path OpenStax is currently serving book JSON from."""
    release = _get_json(RELEASE_URL)
    return f"https://openstax.org{release['archiveUrl']}"


def walk_tree(node: dict, book: Book) -> list[PageRef]:
    """Flatten the table of contents into pages, keeping their place in it."""
    pages: list[PageRef] = []

    def visit(current: dict, unit: str, chapter_title: str, chapter: str) -> None:
        title = _plain(current.get("title", ""))
        children = current.get("contents")
        if children:
            kind = current.get("toc_type")
            if kind == "unit":
                unit = title
            elif kind == "chapter" or re.match(r"^Chapter\s+\d+", title):
                chapter_title = title
                match = re.search(r"(\d+)", title)
                chapter = match.group(1) if match else ""
            for child in children:
                visit(child, unit, chapter_title, chapter)
            return

        page_id = current["id"].split("@")[0]
        section_match = re.match(r"^(\d+)\.(\d+)\b", title)
        pages.append(
            PageRef(
                page_id=page_id,
                title=title,
                slug=current.get("slug", ""),
                chapter=section_match.group(1) if section_match else chapter,
                section=section_match.group(0) if section_match else "",
                unit_title=unit,
                chapter_title=chapter_title,
            )
        )

    visit(node, "", "", "")
    return pages


def fetch_book(book: Book = BIOLOGY_1E, *, raw_dir: Path = RAW_DIR) -> dict:
    """Download the table of contents and every content page. Returns a manifest."""
    base = archive_base()
    book_url = f"{base}/contents/{book.uuid}@{book.version}.json"
    print(f"archive: {base}")
    print(f"book:    {book.title} ({book.edition}) @ {book.version}")

    payload = _get_json(book_url)
    declared = payload.get("license", {})
    if "by/4.0" not in declared.get("url", ""):
        raise SystemExit(
            f"refusing to ingest: {book.title} now reports licence "
            f"{declared.get('name')} ({declared.get('url')}), not CC BY 4.0"
        )

    pages = walk_tree(payload["tree"], book)
    wanted = [page for page in pages if not page.is_excluded]
    skipped = [page for page in pages if page.is_excluded]
    print(f"pages:   {len(wanted)} to fetch, {len(skipped)} excluded as assessment")

    pages_dir = raw_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    def download(page: PageRef) -> tuple[str, bool]:
        destination = pages_dir / f"{page.page_id}.json"
        if destination.exists() and destination.stat().st_size > 0:
            return page.page_id, False
        url = f"{base}/contents/{book.uuid}@{book.version}:{page.page_id}.json"
        destination.write_bytes(_get(url))
        return page.page_id, True

    fetched = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, (_, is_new) in enumerate(pool.map(download, wanted), start=1):
            fetched += int(is_new)
            if index % 50 == 0:
                print(f"  {index}/{len(wanted)}")

    manifest = {
        "book": dataclasses.asdict(book),
        "archive_base": base,
        "book_url": book_url,
        "license_reported_by_source": declared,
        "page_count": len(wanted),
        "excluded_count": len(skipped),
        "excluded_titles": sorted({p.title for p in skipped}),
        "pages": [dataclasses.asdict(p) for p in wanted],
    }
    (raw_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"done:    {fetched} newly downloaded, manifest at {raw_dir / 'manifest.json'}")
    return manifest


def load_manifest(raw_dir: Path = RAW_DIR) -> dict:
    path = raw_dir / "manifest.json"
    if not path.exists():
        raise SystemExit(
            f"no download manifest at {path}. Run `python fetch.py` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def page_content(page_id: str, raw_dir: Path = RAW_DIR) -> str:
    payload = json.loads(
        (raw_dir / "pages" / f"{page_id}.json").read_text(encoding="utf-8")
    )
    return payload.get("content", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--raw-dir", type=Path, default=RAW_DIR, help="where downloads land"
    )
    args = parser.parse_args(argv)
    fetch_book(raw_dir=args.raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Is any P-set item text in the Collection? Checked, not assumed.

T-10's acceptance criterion is that no Held-out item's text is anywhere in the
Collection. That is an assertion about someone else's SQLite file, so it is
answered by reading the file rather than by promising the writer never wrote it.

**What is searched.** Every note's fields, every deck and notetype name, and the
collection's config blob — everything in a collection that can hold text a
student could read in the card browser. Reviews hold no text and are skipped;
that absence is reported rather than silently assumed.

**What counts as a hit.** An item's *stem* — the question — is what identifies
the item, so a hit is the normalised stem appearing in collection text, or any
eight-word window of it appearing. Eight words rather than the whole stem
because a leak that dropped a comma would otherwise pass.

**What does not count, and why.** A bare answer string is not evidence of
leakage: `apoptosis`, `glycolysis` and `S phase` are ordinary biology cards, and
a deck about the demo section is *supposed* to contain them. Counting those
would make this check fail on a correct system, which is a check nobody would
keep. Answer-only matches are reported as a separate, expected number.

The collection is opened read-only and immutable; this script cannot write to it.

    python speedrun/eval/pset/check_no_leak.py
    python speedrun/eval/pset/check_no_leak.py --collection <path.anki2> ...

Exit codes: 0 = no item text found, 1 = a hit, 2 = nothing to check.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

PSET_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = PSET_DIR.parents[1]
PSET_FILE = PSET_DIR / "h2_pset.jsonl"
DECK_APKG = SPEEDRUN_DIR / "eval" / "deck" / "miledown.apkg"

WINDOW = 8  # words


def normalise(text: str) -> str:
    keep = [ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text]
    return " ".join("".join(keep).split())


def windows(text: str, size: int = WINDOW) -> list[str]:
    words = normalise(text).split()
    if len(words) <= size:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + size]) for i in range(len(words) - size + 1)]


def collection_text(path: Path) -> tuple[str, dict[str, int]]:
    """All human-readable text in a collection, plus what it was read from."""
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    parts: list[str] = []
    counts: dict[str, int] = {}
    try:
        rows = con.execute("select flds, tags from notes").fetchall()
        counts["notes"] = len(rows)
        parts += [f"{flds} {tags}" for flds, tags in rows]
        for table, column in (("decks", "name"), ("notetypes", "name")):
            try:
                named = con.execute(f"select {column} from {table}").fetchall()
                counts[table] = len(named)
                parts += [str(r[0]) for r in named]
            except sqlite3.OperationalError:
                # Schema 11 (what an .apkg carries) keeps both as JSON in `col`.
                pass
        try:
            col = con.execute("select decks, models, conf from col").fetchone()
            parts += [str(value) for value in col or ()]
        except sqlite3.OperationalError:
            pass
        try:
            config = con.execute("select key, val from config").fetchall()
            counts["config"] = len(config)
            parts += [f"{k} {v}" for k, v in config]
        except sqlite3.OperationalError:
            pass
        counts["revlog"] = con.execute("select count(*) from revlog").fetchone()[0]
    finally:
        con.close()
    return normalise(" ".join(parts)), counts


def collections_from(args: argparse.Namespace) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for given in args.collection:
        found.append((f"given: {given}", Path(given)))
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        for path in sorted(Path(appdata).glob("Anki2/*/collection.anki2")):
            found.append((f"profile: {path.parent.name}", path))
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--collection", action="append", default=[])
    parser.add_argument(
        "--skip-apkg", action="store_true", help="do not check the demo deck's .apkg"
    )
    args = parser.parse_args(argv)

    if not PSET_FILE.exists():
        print(f"no P-set at {PSET_FILE}")
        return 2
    items = [
        json.loads(line)
        for line in PSET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"{len(items)} item(s) in {PSET_FILE.name}\n")

    targets = collections_from(args)
    with tempfile.TemporaryDirectory() as tmp:
        if DECK_APKG.exists() and not args.skip_apkg:
            with zipfile.ZipFile(DECK_APKG) as zf:
                for name in zf.namelist():
                    if name.endswith(".anki2") or name.endswith(".anki21"):
                        zf.extract(name, tmp)
                        targets.append((f"deck package: {DECK_APKG.name}/{name}",
                                        Path(tmp) / name))
        if not targets:
            print("no collection found to check — nothing was verified")
            return 2

        failures = 0
        for label, path in targets:
            if not path.exists():
                print(f"  MISSING  {label}: {path}")
                failures += 1
                continue
            text, counts = collection_text(path)
            stem_hits = [
                item["id"]
                for item in items
                if any(w and w in text for w in windows(item["stem"]))
            ]
            id_hits = [item["id"] for item in items if normalise(item["id"]) in text]
            answer_hits = [
                item["id"] for item in items if normalise(item["answer"]) in text
            ]
            summary = ", ".join(f"{k}={v}" for k, v in counts.items())
            print(f"  {label}\n    {path}\n    {summary}")
            if stem_hits or id_hits:
                failures += 1
                print(f"    LEAK: stems {stem_hits} ids {id_hits}")
            else:
                print("    no item stem, and no item id, appears in this collection")
            print(
                f"    (bare answer strings present: {len(answer_hits)}/{len(items)} — "
                "expected; a deck about this section contains these terms)"
            )
        print()
        if failures:
            print(f"FAILED — item text found in {failures} collection(s).")
            return 1
        print(
            f"OK — no P-set stem and no P-set id in {len(targets)} collection(s). "
            "Reviews carry no text; nothing was searched there."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

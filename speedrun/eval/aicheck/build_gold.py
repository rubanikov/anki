#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Turn the hand-written gold pairs into H3, one ledgered item at a time.

The manifest says H3 is "50 question/answer pairs drawn by hand from one real
source, authored before any card generation runs". `gold_pairs.json` is the
hand-written part; this script is the part that refuses to let a hand-written
pair be wrong about the source:

  * the answer is located inside the chunk the pair names, using the corpus's
    own `spans.find_span` — the same matcher the Generation gate uses, so a gold
    answer is grounded on exactly the terms a generated answer has to meet;
  * the resulting span is re-verified against the full page text, so the
    recorded `start:end` really does read back as the recorded quote;
  * a pair whose answer cannot be located **aborts the build**. Writing it
    without a span would put an unsupported claim into the reference every
    generated card is graded against, which is the one defect a gold set cannot
    survive.

Each item is written to `h3_gold.jsonl` and appended to `MANIFEST.md`'s H3
ledger by `freeze.py --append-item` **as it is produced**, before the next one
is written — the ordering the H2 protocol fixed and H3 inherits.

Usage (from the repo root, with the agent's own interpreter):

    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/build_gold.py --check
    speedrun/agent/.venv/Scripts/python speedrun/eval/aicheck/build_gold.py --build
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

AICHECK_DIR = Path(__file__).resolve().parent
SPEEDRUN_DIR = AICHECK_DIR.parents[1]
AGENT_DIR = SPEEDRUN_DIR / "agent"
CORPUS_DIR = SPEEDRUN_DIR / "corpus"
HOLDOUT_DIR = SPEEDRUN_DIR / "eval" / "holdout"
INDEX = CORPUS_DIR / "out" / "index.sqlite3"

GOLD_PAIRS = AICHECK_DIR / "gold_pairs.json"
#: The path the frozen protocol names for H3. Not ours to move.
GOLD_FILE = HOLDOUT_DIR / "h3_gold.jsonl"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(CORPUS_DIR))

import spans  # noqa: E402
from index import CorpusIndex  # noqa: E402

sys.path.insert(0, str(AICHECK_DIR))
import plan  # noqa: E402


def load_pairs() -> list[dict[str, Any]]:
    return json.loads(GOLD_PAIRS.read_text(encoding="utf-8"))["pairs"]


def chunk_by_id(db: sqlite3.Connection, chunk_id: str) -> Any:
    """One chunk, by id, rebuilt into the corpus's own `Hit`.

    `index.py` has no get-by-id — it is a search index — so the row is fetched
    here and handed to the index's own row-to-Hit constructor rather than
    re-implementing the chunk shape, which would be a second definition of what
    a chunk is.
    """
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT c.*, p.title AS page_title, p.url AS url, 0.0 AS score "
        "  FROM chunk c JOIN page p ON p.source_id = c.source_id "
        " WHERE c.chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        raise KeyError(chunk_id)
    return CorpusIndex._hit(row)  # noqa: SLF001 - the row shape is its own


def resolve(pair: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    """One gold pair, with its span located and re-verified, or an exception."""
    hit = chunk_by_id(db, pair["chunk_id"])
    span = spans.find_span(hit.chunk, pair["answer"])
    if span is None:
        raise ValueError(
            f"{pair['id']}: answer {pair['answer']!r} is not in {pair['chunk_id']}"
        )
    page = CorpusIndex.open(INDEX).page_text(span.source_id)
    if not spans.verify(span, page):
        raise ValueError(f"{pair['id']}: span does not re-verify on its page")
    return {"hit": hit, "span": span}


def record(pair: dict[str, Any], hit: Any, span: Any, target: plan.Target) -> dict[str, Any]:
    """One H3 row. The first five fields are what H3's item hash covers."""
    return {
        "id": pair["id"],
        "question": pair["question"],
        "answer": pair["answer"],
        "source_id": span.source_id,
        "source_span": {
            "chunk_id": span.chunk_id,
            "start": span.start,
            "end": span.end,
            # The source's own characters, copied out of the page by the matcher.
            "quote": span.quote,
            "block_id": span.block_id,
            "url": hit.url,
        },
        # --- not covered by the hash: provenance and bookkeeping ---
        "topic": target.topic_id,
        "target_concept": target.concept,
        "page_title": hit.page_title,
        "citation": span.as_citation(hit.url),
        "authored_by": "hand-written against the retrieved passage; no model call",
        "off_concept": bool(pair.get("off_concept")),
        "authored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "live",
    }


def append_and_ledger(row: dict[str, Any]) -> bool:
    """Write one item, then ledger it. In that order, one item at a time."""
    with GOLD_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    result = subprocess.run(
        [sys.executable, str(HOLDOUT_DIR / "freeze.py"), "--append-item", "--set", "H3"],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    return result.returncode == 0


def existing_ids() -> set[str]:
    if not GOLD_FILE.exists():
        return set()
    return {
        json.loads(line)["id"]
        for line in GOLD_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="resolve every span; write nothing"
    )
    parser.add_argument("--build", action="store_true", help="write and ledger H3")
    args = parser.parse_args(argv)

    pairs = load_pairs()
    targets = {target.gold_id: target for target in plan.targets()}
    missing = [p["id"] for p in pairs if p["id"] not in targets]
    if missing:
        print(f"pairs with no target in the plan: {missing}", file=sys.stderr)
        return 1
    unwritten = [target for target in targets if target not in {p["id"] for p in pairs}]
    if unwritten:
        print(f"targets with no gold pair: {unwritten}", file=sys.stderr)
        return 1

    db = sqlite3.connect(INDEX)
    failures = []
    resolved = []
    try:
        for pair in pairs:
            try:
                found = resolve(pair, db)
            except (KeyError, ValueError) as exc:
                failures.append(str(exc))
                continue
            resolved.append((pair, found))
            print(
                f"  ok  {pair['id']:<10} {pair['answer'][:34]:<36} "
                f"{found['span'].as_citation()}"
            )
    finally:
        db.close()

    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} pair(s) unresolved — nothing written.", file=sys.stderr)
        return 1
    print(f"\n{len(resolved)} of {len(pairs)} pairs resolve to a verified span.")
    if not args.build:
        return 0

    GOLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLD_FILE.touch()
    already = existing_ids()
    written = 0
    for pair, found in resolved:
        if pair["id"] in already:
            continue
        row = record(pair, found["hit"], found["span"], targets[pair["id"]])
        append_and_ledger(row)
        written += 1
    print(f"wrote and ledgered {written} item(s) to {GOLD_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

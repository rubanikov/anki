#!/usr/bin/env python3
"""Freeze and verify Speedrun's held-out sets (ticket T-01).

The held-out sets are H1 (memory-calibration reviews), H2 (the P-set of
Held-out items), H3 (the AI card gold set) and H4 (the R-set of Reworded
cards). `MANIFEST.md` is the single source of truth: this script reads and
writes the delimited tables inside it, so a human reviewer and the script are
always looking at the same bytes.

Modes
  --status                 show what is frozen, open, or pending (default)
  --freeze                 record hashes for data that now exists
  --append-item --set H2   append new item ids + SHA-256 to a ledger
  --close-set H2           fix a set's file-level hash; no more appends
  --verify                 re-verify everything; exit non-zero on mismatch

Stdlib only, on purpose: this runs on a machine that may have nothing else.

Exit codes: 0 = all checks passed, 1 = a check failed, 2 = usage error.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

HOLDOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = HOLDOUT_DIR.parents[2]  # .../anki
MANIFEST = HOLDOUT_DIR / "MANIFEST.md"
GITIGNORE = REPO_ROOT / ".gitignore"

PENDING = "PENDING"

SET_MARKER = "FREEZE-RECORDS"
LEDGER_MARKER = "{key}-LEDGER"

# --------------------------------------------------------------------------
# The four sets, plus the protocol itself
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SetSpec:
    key: str
    name: str
    path: str  # repo-relative POSIX path
    id_field: str | None  # None => file-level hash only, no per-item ledger
    content_fields: tuple[str, ...]  # fields covered by an item's SHA-256
    committed: bool  # may this data file enter the public fork?


SETS: tuple[SetSpec, ...] = (
    SetSpec(
        key="PROTOCOL",
        name="the freeze script itself",
        path="speedrun/eval/holdout/freeze.py",
        id_field=None,
        content_fields=(),
        committed=True,
    ),
    SetSpec(
        key="H1",
        name="memory-calibration reviews",
        path="speedrun/eval/holdout/h1_reviews.jsonl",
        id_field=None,
        content_fields=(),
        committed=False,  # licensed corpus derivative: never in the public fork
    ),
    SetSpec(
        key="H2",
        name="P-set, Held-out items",
        path="speedrun/eval/holdout/h2_pset.jsonl",
        id_field="id",
        content_fields=("id", "topic", "stem", "options", "answer", "source_id", "source_span"),
        committed=True,
    ),
    SetSpec(
        key="H3",
        name="AI card gold set",
        path="speedrun/eval/holdout/h3_gold.jsonl",
        id_field="id",
        content_fields=("id", "question", "answer", "source_id", "source_span"),
        committed=True,
    ),
    SetSpec(
        key="H4",
        name="R-set, Reworded cards",
        path="speedrun/eval/holdout/h4_rset.jsonl",
        id_field="id",
        content_fields=("id", "card_id", "rewording_index", "prompt", "answer"),
        committed=True,
    ),
)

SETS_BY_KEY = {s.key: s for s in SETS}
LEDGER_SETS = tuple(s.key for s in SETS if s.id_field)

# Working-tree paths that must stay empty. The anki-revlogs-10k licence permits
# individual research use and forbids public redistribution, so the leakage
# check has to be able to demonstrate the corpus is not here.
LICENSED_ABSENT_GLOBS: tuple[str, ...] = (
    "speedrun/**/anki-revlogs-10k",
    "speedrun/**/anki-revlogs-10k/**",
    "speedrun/eval/corpus/**/*.parquet",
    "speedrun/eval/holdout/raw",
    "speedrun/eval/holdout/*.parquet",
    "speedrun/eval/holdout/*.anki2",
    "speedrun/eval/holdout/*.colpkg",
)

# .gitignore lines that must exist verbatim for the above to stay true.
REQUIRED_GITIGNORE_PATTERNS: tuple[str, ...] = (
    "speedrun/**/anki-revlogs-10k/",
    "speedrun/eval/corpus/",
    "speedrun/eval/holdout/raw/",
    "speedrun/eval/holdout/h1_reviews.jsonl",
    "speedrun/eval/holdout/*.parquet",
    "speedrun/eval/holdout/*.anki2",
    "speedrun/eval/holdout/*.colpkg",
    "speedrun/eval/.hf_cache/",
)

# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_bytes(obj: dict, fields: tuple[str, ...]) -> bytes:
    """Canonical serialization an item's SHA-256 is taken over.

    Only the declared content fields are covered, so later bookkeeping (when an
    item was shown, how it scored) cannot change an item's hash. Sorted keys,
    no whitespace, UTF-8, no ASCII escaping.
    """
    missing = [f for f in fields if f not in obj]
    if missing:
        raise ValueError(f"item is missing required content field(s): {', '.join(missing)}")
    subset = {f: obj[f] for f in fields}
    return json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def item_hash(obj: dict, fields: tuple[str, ...]) -> str:
    return hashlib.sha256(canonical_bytes(obj, fields)).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{lineno}: not valid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path.name}:{lineno}: expected a JSON object")
            items.append(obj)
    return items


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# MANIFEST.md tables
# --------------------------------------------------------------------------

SET_COLUMNS = ["set", "path", "state", "sha256", "bytes", "records", "frozen_at (UTC)"]
LEDGER_COLUMNS = ["item_id", "sha256", "appended_at (UTC)", "status"]


def _markers(marker: str) -> tuple[str, str]:
    return f"<!-- {marker}:BEGIN -->", f"<!-- {marker}:END -->"


def read_block(text: str, marker: str) -> list[list[str]]:
    """Return the data rows of the markdown table inside a marked block."""
    begin, end = _markers(marker)
    if begin not in text or end not in text:
        raise ValueError(f"MANIFEST.md is missing the {marker} block")
    body = text.split(begin, 1)[1].split(end, 1)[0]
    rows: list[list[str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):  # separator row
            continue
        if cells and cells[0].lower() in ("set", "item_id"):  # header row
            continue
        rows.append(cells)
    return rows


def write_block(text: str, marker: str, columns: list[str], rows: list[list[str]]) -> str:
    begin, end = _markers(marker)
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    table = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    table += ["| " + " | ".join(r) + " |" for r in rows]
    return head + begin + "\n" + "\n".join(table) + "\n" + end + tail


def load_manifest() -> str:
    if not MANIFEST.exists():
        die(f"{MANIFEST} does not exist — nothing to freeze against.")
    return MANIFEST.read_text(encoding="utf-8")


def set_rows(text: str) -> dict[str, list[str]]:
    rows = {}
    for cells in read_block(text, SET_MARKER):
        if len(cells) != len(SET_COLUMNS):
            raise ValueError(f"malformed record row: {cells!r}")
        rows[cells[0]] = cells
    return rows


def ledger_rows(text: str, key: str) -> list[list[str]]:
    return read_block(text, LEDGER_MARKER.format(key=key))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, msg: str) -> None:
        print(f"  ok      {msg}")

    def skip(self, msg: str) -> None:
        print(f"  skip    {msg}")

    def pending(self, msg: str) -> None:
        print(f"  pending {msg}")

    def fail(self, msg: str) -> None:
        print(f"  FAIL    {msg}")
        self.failures.append(msg)


def die(msg: str, code: int = 2) -> None:
    print(f"freeze.py: {msg}", file=sys.stderr)
    raise SystemExit(code)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def cmd_status(_args: argparse.Namespace) -> int:
    text = load_manifest()
    rows = set_rows(text)
    print(f"manifest: {MANIFEST}")
    print(f"repo root: {REPO_ROOT}")
    print()
    for spec in SETS:
        row = rows.get(spec.key)
        if row is None:
            print(f"  {spec.key:<9} NO RECORD IN MANIFEST")
            continue
        path = REPO_ROOT / spec.path
        present = "present" if path.exists() else "absent"
        note = "" if spec.committed else "  (licensed: must stay out of the fork)"
        print(f"  {spec.key:<9} state={row[2]:<8} file={present:<7} {spec.path}{note}")
        print(f"  {'':<9} recorded sha256: {row[3]}")
        if spec.id_field:
            live = [r for r in ledger_rows(text, spec.key) if r[3] == "live"]
            print(f"  {'':<9} ledger: {len(live)} live item(s)")
    return 0


# --------------------------------------------------------------------------
# freeze
# --------------------------------------------------------------------------


def cmd_freeze(args: argparse.Namespace) -> int:
    text = load_manifest()
    rows = set_rows(text)
    changed = False
    for spec in SETS:
        row = rows.get(spec.key)
        if row is None:
            die(f"MANIFEST.md has no record row for {spec.key}")
        if args.set and spec.key not in args.set:
            continue
        path = REPO_ROOT / spec.path
        if not path.exists():
            print(f"  {spec.key}: no data yet — left PENDING")
            continue
        digest = sha256_file(path)
        if row[2] == "frozen" and row[3] != PENDING:
            if row[3] == digest:
                print(f"  {spec.key}: already frozen, hash unchanged")
            elif args.force:
                print(f"  {spec.key}: RE-FREEZING (--force). Record why under Amendments.")
                _fill(row, spec, path, digest, state="frozen")
                changed = True
            else:
                die(
                    f"{spec.key} is frozen but {spec.path} no longer matches its recorded "
                    f"hash.\n  recorded: {row[3]}\n  actual:   {digest}\n"
                    "  Frozen data is not supposed to change. If the change is legitimate, "
                    "re-run with --force and record the reason in MANIFEST.md > Amendments.",
                    1,
                )
            continue
        # pending or open -> record what exists now
        state = "open" if spec.id_field else "frozen"
        _fill(row, spec, path, digest, state=state)
        changed = True
        print(f"  {spec.key}: recorded sha256 {digest} (state={state})")
    if changed:
        MANIFEST.write_text(write_block(text, SET_MARKER, SET_COLUMNS, list(rows.values())), encoding="utf-8")
        print(f"wrote {MANIFEST}")
    else:
        print("nothing to write")
    return 0


def _fill(row: list[str], spec: SetSpec, path: Path, digest: str, state: str) -> None:
    row[2] = state
    row[3] = digest
    row[4] = str(path.stat().st_size)
    row[5] = str(len(read_jsonl(path))) if path.suffix == ".jsonl" else "-"
    row[6] = utc_now()


# --------------------------------------------------------------------------
# append-item
# --------------------------------------------------------------------------


def cmd_append_item(args: argparse.Namespace) -> int:
    key = args.set
    spec = SETS_BY_KEY.get(key)
    if spec is None or not spec.id_field:
        die(f"--set must be one of {', '.join(LEDGER_SETS)}")
    text = load_manifest()
    rows = set_rows(text)
    if rows[key][2] == "frozen":
        die(f"{key} is closed (state=frozen); no more items may be appended", 1)
    path = REPO_ROOT / spec.path
    if not path.exists():
        die(f"{spec.path} does not exist yet — nothing to append", 1)

    existing = ledger_rows(text, key)
    known = {r[0] for r in existing}
    try:
        items = read_jsonl(path)
    except ValueError as exc:
        die(str(exc), 1)

    added: list[list[str]] = []
    stamp = utc_now()
    for obj in items:
        item_id = str(obj.get(spec.id_field, "")).strip()
        if not item_id:
            die(f"an item in {spec.path} has no '{spec.id_field}'", 1)
        if item_id in known:
            continue
        try:
            digest = item_hash(obj, spec.content_fields)
        except ValueError as exc:
            die(f"{item_id}: {exc}", 1)
        added.append([item_id, digest, stamp, "live"])
        known.add(item_id)

    if not added:
        print(f"{key}: no new items — ledger already covers every item in {spec.path}")
        return 0
    for row in added:
        print(f"  + {row[0]}  {row[1]}")
    if args.dry_run:
        print(f"{key}: {len(added)} item(s) would be appended (--dry-run, nothing written)")
        return 0
    MANIFEST.write_text(
        write_block(text, LEDGER_MARKER.format(key=key), LEDGER_COLUMNS, existing + added),
        encoding="utf-8",
    )
    print(f"{key}: appended {len(added)} item(s) to the ledger in {MANIFEST}")
    return 0


# --------------------------------------------------------------------------
# close-set
# --------------------------------------------------------------------------


def cmd_close_set(args: argparse.Namespace) -> int:
    key = args.close_set
    spec = SETS_BY_KEY.get(key)
    if spec is None:
        die(f"--close-set must name a set: {', '.join(SETS_BY_KEY)}")
    text = load_manifest()
    rows = set_rows(text)
    row = rows[key]
    if row[2] == "frozen":
        print(f"{key} is already closed.")
        return 0
    path = REPO_ROOT / spec.path
    if not path.exists():
        die(f"{spec.path} does not exist — cannot close an empty set", 1)
    rep = Report()
    _verify_ledger(text, spec, path, rep)
    if rep.failures:
        die(f"{key} ledger does not match {spec.path}; refusing to close", 1)
    _fill(row, spec, path, sha256_file(path), state="frozen")
    MANIFEST.write_text(write_block(text, SET_MARKER, SET_COLUMNS, list(rows.values())), encoding="utf-8")
    print(f"{key}: closed at {row[6]}, sha256 {row[3]}")
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------


def _verify_ledger(text: str, spec: SetSpec, path: Path, rep: Report) -> None:
    """Every ledger item is in the file with its recorded hash, and vice versa."""
    ledger = {r[0]: r for r in ledger_rows(text, spec.key)}
    live = {k: v for k, v in ledger.items() if v[3] == "live"}
    try:
        items = read_jsonl(path)
    except ValueError as exc:
        rep.fail(f"{spec.key}: {exc}")
        return
    seen: set[str] = set()
    for obj in items:
        item_id = str(obj.get(spec.id_field, "")).strip()
        if item_id in seen:
            rep.fail(f"{spec.key}: duplicate item id {item_id} in {spec.path}")
            continue
        seen.add(item_id)
        row = ledger.get(item_id)
        if row is None:
            rep.fail(f"{spec.key}: {item_id} is in {spec.path} but not in the ledger")
            continue
        try:
            digest = item_hash(obj, spec.content_fields)
        except ValueError as exc:
            rep.fail(f"{spec.key}: {item_id}: {exc}")
            continue
        if digest != row[1]:
            rep.fail(
                f"{spec.key}: {item_id} content changed since it was frozen "
                f"(recorded {row[1][:16]}…, actual {digest[:16]}…)"
            )
    for item_id in live:
        if item_id not in seen:
            rep.fail(f"{spec.key}: {item_id} is in the ledger but missing from {spec.path}")
    if not rep.failures:
        rep.ok(f"{spec.key}: {len(live)} ledger item(s) match {spec.path}")


def cmd_verify(_args: argparse.Namespace) -> int:
    text = load_manifest()
    rows = set_rows(text)
    rep = Report()

    print("recorded hashes")
    for spec in SETS:
        row = rows.get(spec.key)
        if row is None:
            rep.fail(f"{spec.key}: no record row in MANIFEST.md")
            continue
        path = REPO_ROOT / spec.path
        state, recorded = row[2], row[3]
        if not path.exists():
            if state == "pending":
                rep.pending(f"{spec.key}: not generated yet ({spec.path})")
            elif not spec.committed:
                rep.skip(
                    f"{spec.key}: {spec.path} absent — expected, its licence forbids "
                    "redistribution; hash on record for local re-verification"
                )
            else:
                rep.fail(f"{spec.key}: recorded as {state} but {spec.path} is missing")
            continue
        if state == "pending" or recorded == PENDING:
            rep.fail(
                f"{spec.key}: {spec.path} exists but the manifest still says PENDING — "
                "run freeze.py --freeze"
            )
            continue
        digest = sha256_file(path)
        if digest == recorded:
            rep.ok(f"{spec.key}: {spec.path} matches its recorded sha256 ({state})")
        elif state == "open":
            rep.ok(f"{spec.key}: {spec.path} is open; file-level hash not yet fixed")
        else:
            rep.fail(
                f"{spec.key}: {spec.path} does not match its recorded sha256\n"
                f"            recorded {recorded}\n            actual   {digest}"
            )

    print("\nper-item ledgers")
    for key in LEDGER_SETS:
        spec = SETS_BY_KEY[key]
        path = REPO_ROOT / spec.path
        if not path.exists():
            live = [r for r in ledger_rows(text, key) if r[3] == "live"]
            if live:
                rep.fail(f"{key}: ledger has {len(live)} item(s) but {spec.path} is missing")
            else:
                rep.pending(f"{key}: empty at freeze, still empty")
            continue
        _verify_ledger(text, spec, path, rep)

    print("\nlicensed data absent from the working tree")
    for pattern in LICENSED_ABSENT_GLOBS:
        hits = sorted(str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.glob(pattern))
        if hits:
            rep.fail(f"licensed/raw data present: {pattern} -> {', '.join(hits[:5])}")
        else:
            rep.ok(f"nothing matches {pattern}")

    print("\n.gitignore keeps it that way")
    if not GITIGNORE.exists():
        rep.fail(f"{GITIGNORE} does not exist")
    else:
        lines = {ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()}
        for pattern in REQUIRED_GITIGNORE_PATTERNS:
            if pattern in lines:
                rep.ok(f".gitignore contains {pattern}")
            else:
                rep.fail(f".gitignore is missing {pattern}")

    print()
    if rep.failures:
        print(f"VERIFY FAILED — {len(rep.failures)} problem(s).")
        return 1
    print("VERIFY OK — every recorded hash matches and nothing licensed is in the tree.")
    print(
        "Scope: this checks the working tree, not git history. The leakage check "
        "(T-20) adds the git-tracked assertion."
    )
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="freeze.py",
        description=(
            "Freeze and verify Speedrun's held-out sets (H1 calibration reviews, "
            "H2 the P-set, H3 the gold set, H4 the R-set) against "
            "speedrun/eval/holdout/MANIFEST.md."
        ),
        epilog=(
            "Exit codes: 0 ok, 1 a check failed, 2 usage error. "
            "MANIFEST.md is the source of truth; this script only reads and rewrites "
            "the marked tables inside it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="show each set's state (default)")
    mode.add_argument(
        "--freeze",
        action="store_true",
        help="compute and record SHA-256 for any set whose data now exists",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="re-verify hashes, ledgers and licence containment; exit 1 on any mismatch",
    )
    mode.add_argument(
        "--append-item",
        action="store_true",
        help="append every not-yet-recorded item of --set to its ledger in MANIFEST.md",
    )
    mode.add_argument(
        "--close-set",
        metavar="SET",
        help="fix a set's file-level hash after its last item; no further appends",
    )
    parser.add_argument(
        "--set",
        action="append",
        metavar="SET",
        help="limit --freeze to these sets, or name the set for --append-item",
    )
    parser.add_argument("--dry-run", action="store_true", help="--append-item: show, do not write")
    parser.add_argument(
        "--force",
        action="store_true",
        help="--freeze: overwrite an already-frozen hash (record why under Amendments)",
    )
    args = parser.parse_args(argv)

    try:
        if args.verify:
            return cmd_verify(args)
        if args.freeze:
            return cmd_freeze(args)
        if args.append_item:
            if not args.set or len(args.set) != 1:
                die("--append-item needs exactly one --set (H2 or H4)")
            args.set = args.set[0]
            return cmd_append_item(args)
        if args.close_set:
            return cmd_close_set(args)
        return cmd_status(args)
    except ValueError as exc:
        die(str(exc), 1)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

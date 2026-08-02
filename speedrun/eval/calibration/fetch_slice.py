#!/usr/bin/env python3
"""Fetch a bounded slice of the public Anki review-log corpus (ticket T-05).

The corpus is `open-spaced-repetition/anki-revlogs-10k`: ~727M real reviews from
10,000 real Anki collections, the corpus FSRS itself is benchmarked on. Its
licence permits individual research use and **forbids public redistribution**,
so everything this script writes lands under `speedrun/eval/holdout/raw/`, which
is `.gitignore`d, and `--clean` deletes it again. `freeze.py --verify` fails
while that directory exists, which is the point: the proof that the corpus is
not in the tree is a check, not a claim.

Which distribution, and why
---------------------------
The processed distribution (`anki-revlogs-10k`, parquet, per-user directories)
is **gated**: `resolve/.../data.parquet` returns HTTP 401 without a Hugging Face
token, and no token exists on this machine. The publisher also hosts
`open-spaced-repetition/anki-revlogs-10k-raw`, which is ungated, carries the
same `anki-revlogs-10k` licence, and is described by the publisher as "the
original data of open-spaced-repetition/anki-revlogs-10k" — the same reviews,
before the parquet conversion, exported by Anki's own
`Collection::export_dataset` (`rslib/src/scheduler/fsrs/params.rs`). It is a
single 8.46 GB 7-Zip archive holding one protobuf-encoded `anki.stats.Dataset`
per collection.

This is the same real corpus, not a substitute for it. It is also *better*
suited to the job: the raw records carry `id` (the review's epoch-millisecond
timestamp), `review_kind` and `ease_factor`, so Anki's own revlog filtering can
be reproduced exactly, and each collection carries its `next_day_at`, so the
day-boundary arithmetic FSRS uses is reproduced exactly too.

The sampling rule
-----------------
Stated here rather than discovered later, because an unstated sampling rule is
an unstated result:

1. The archive is a solid 7-Zip file in 8 LZMA2 blocks. Block 0 holds the first
   1315 `.revlog` entries in archive order. Only block 0's packed bytes are
   fetched (~1.10 GB of the 8.46 GB), which is what makes the slice bounded.
2. From those 1315 collection ids, sorted ascending as strings, a uniform sample
   of `--collections` (default 300) is drawn with
   `random.Random(20260802).sample(...)`. The seed is the one already
   pre-registered in `speedrun/eval/holdout/MANIFEST.md` for H4; it is fixed
   here before any score exists and is not re-rolled.
3. No filtering on collection size, age, or behaviour. Whatever the sample
   contains is what gets scored.

This samples *which collections were downloaded*. It does not touch the H1 split
rule, which the manifest fixes as deterministic and unsampled and which
`calibrate.py` applies unchanged to every collection in the slice.

Dependency: `py7zr` (`pip install py7zr`), used only to read the archive.
`calibrate.py`, which produces every number, is stdlib-only.

Usage
-----
    python speedrun/eval/calibration/fetch_slice.py            # download
    python speedrun/eval/calibration/fetch_slice.py --clean    # delete the raw slice

Exit codes: 0 ok, 1 the corpus could not be fetched, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

CALIBRATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = CALIBRATION_DIR.parents[2]  # .../anki
RAW_DIR = REPO_ROOT / "speedrun" / "eval" / "holdout" / "raw"
SLICE_RECORD = CALIBRATION_DIR / "corpus_slice.json"

# Pinned so the slice is reproducible. Recorded in MANIFEST.md at download time.
DATASET = "open-spaced-repetition/anki-revlogs-10k-raw"
REVISION = "197633e5ec9f4a177f285447053329db40e2eb5e"
ARCHIVE = "revlogs.7z"
# The archive's own SHA-256, as served in the LFS ETag by huggingface.co.
ARCHIVE_SHA256 = "2921e71e2d39156eef198c8516078ec7806d74443900c0a1005f3c4467389f95"
ARCHIVE_BYTES = 8459427959

GATED_DATASET = "open-spaced-repetition/anki-revlogs-10k"

SAMPLE_SEED = 20260802  # pre-registered in MANIFEST.md
DEFAULT_COLLECTIONS = 300

URL = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{ARCHIVE}"


class HttpRangeFile(io.RawIOBase):
    """A read-only seekable file backed by HTTP range requests.

    Lets py7zr read the archive's header and one solid block without ever
    storing the 8.46 GB archive locally.
    """

    def __init__(self, url: str, size: int) -> None:
        self.url = url
        self.size = size
        self._pos = 0
        self.bytes_fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self.size + offset
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        if n <= 0 or self._pos >= self.size:
            return b""
        end = min(self._pos + n, self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self._pos}-{end}"})
        for attempt in range(5):
            try:
                data = urllib.request.urlopen(req, timeout=300).read()
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 4:
                    raise
        self._pos += len(data)
        self.bytes_fetched += len(data)
        return data

    def readinto(self, buf) -> int:  # type: ignore[no-untyped-def]
        data = self.read(len(buf))
        buf[: len(data)] = data
        return len(data)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_reachable() -> None:
    """Fail loudly and specifically if the corpus cannot be fetched.

    The ticket forbids substituting simulated reviews, so an unreachable corpus
    has to stop the run rather than quietly degrade it.
    """
    req = urllib.request.Request(URL, method="HEAD")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(
                f"fetch_slice.py: {DATASET} now requires authentication "
                f"(HTTP {exc.code}). The gated distribution {GATED_DATASET} already "
                "does. Nothing can be measured without the real corpus, and "
                "simulated reviews are disqualified — stopping.",
                file=sys.stderr,
            )
        else:
            print(f"fetch_slice.py: {URL} returned HTTP {exc.code} — stopping.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 - any network failure stops the run
        print(f"fetch_slice.py: cannot reach {URL}: {exc} — stopping.", file=sys.stderr)
        raise SystemExit(1)
    size = int(resp.headers["content-length"])
    if size != ARCHIVE_BYTES:
        print(
            f"fetch_slice.py: {ARCHIVE} is {size} bytes, expected {ARCHIVE_BYTES}. "
            "The pinned revision has moved — stopping rather than scoring unknown bytes.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def cmd_clean() -> int:
    if RAW_DIR.exists():
        shutil.rmtree(RAW_DIR)
        print(f"removed {RAW_DIR}")
    else:
        print(f"{RAW_DIR} is already absent")
    return 0


def cmd_fetch(n_collections: int) -> int:
    try:
        import py7zr
    except ImportError:
        print(
            "fetch_slice.py: py7zr is required to read the archive "
            "(`pip install py7zr`). calibrate.py itself is stdlib-only.",
            file=sys.stderr,
        )
        return 2

    check_reachable()

    backing = HttpRangeFile(URL, ARCHIVE_BYTES)
    fh = io.BufferedReader(backing, buffer_size=8 << 20)  # type: ignore[arg-type]
    archive = py7zr.SevenZipFile(fh, mode="r")

    streams = archive.header.main_streams
    per_block = streams.substreamsinfo.num_unpackstreams_folders
    packed = streams.packinfo.packsizes
    block0_files = per_block[0]

    # Archive order, directories excluded: the first `block0_files` real files
    # live in solid block 0, so fetching block 0's packed bytes is enough.
    names = [e.filename for e in archive.list() if not e.is_directory]
    block0 = sorted(names[:block0_files])
    if len(block0) != block0_files:
        print("fetch_slice.py: archive layout is not what was pinned — stopping.", file=sys.stderr)
        return 1

    rng = random.Random(SAMPLE_SEED)
    targets = sorted(rng.sample(block0, min(n_collections, len(block0))))

    print(f"dataset   {DATASET}@{REVISION[:12]}")
    print(f"archive   {ARCHIVE}  {ARCHIVE_BYTES} bytes  sha256 {ARCHIVE_SHA256[:16]}…")
    print(f"block 0   {block0_files} collections, {packed[0]} packed bytes of {sum(packed)}")
    print(f"sample    {len(targets)} collections, random.Random({SAMPLE_SEED}).sample")
    print(f"into      {RAW_DIR}")
    print("downloading and decompressing block 0 — this fetches ~1.1 GB …")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    archive.extract(path=RAW_DIR, targets=targets)
    archive.close()

    files = []
    total = 0
    for name in targets:
        path = RAW_DIR / name
        if not path.exists():
            print(f"fetch_slice.py: {name} was not extracted — stopping.", file=sys.stderr)
            return 1
        size = path.stat().st_size
        total += size
        files.append(
            {
                "name": name,
                "collection": int(Path(name).stem),
                "bytes": size,
                "sha256": sha256_file(path),
            }
        )

    record = {
        "dataset": DATASET,
        "revision": REVISION,
        "archive": ARCHIVE,
        "archive_bytes": ARCHIVE_BYTES,
        "archive_sha256": ARCHIVE_SHA256,
        "gated_distribution": GATED_DATASET,
        "gated_distribution_note": (
            f"{GATED_DATASET} returns HTTP 401 without a Hugging Face token; the "
            "ungated raw distribution above is the same corpus from the same "
            "publisher under the same licence."
        ),
        "sampling_rule": (
            "Solid block 0 of revlogs.7z holds the first "
            f"{block0_files} .revlog entries in archive order; only its "
            f"{packed[0]} packed bytes were fetched. From those collection ids, "
            f"sorted ascending as strings, random.Random({SAMPLE_SEED}).sample "
            f"drew {len(targets)}. No filtering on size, age or behaviour."
        ),
        "sample_seed": SAMPLE_SEED,
        "block0_collections": block0_files,
        "block0_packed_bytes": packed[0],
        "bytes_fetched_over_http": backing.bytes_fetched,
        "collections": len(files),
        "extracted_bytes": total,
        "licence": (
            "anki-revlogs-10k licence: individual research use permitted, public "
            "redistribution forbidden. These files are .gitignore'd and deleted "
            "by --clean; only hashes and derived numbers are committed."
        ),
        "files": files,
    }
    SLICE_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"extracted {len(files)} collections, {total} bytes")
    print(f"fetched   {backing.bytes_fetched} bytes over HTTP")
    print(f"wrote     {SLICE_RECORD}")
    print(
        "\nRemember: run --clean once calibrate.py has finished. "
        "freeze.py --verify fails while speedrun/eval/holdout/raw/ exists."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_slice.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--collections",
        type=int,
        default=DEFAULT_COLLECTIONS,
        help=f"how many collections to sample (default {DEFAULT_COLLECTIONS})",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete speedrun/eval/holdout/raw/ and exit",
    )
    args = parser.parse_args(argv)
    if args.clean:
        return cmd_clean()
    return cmd_fetch(args.collections)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

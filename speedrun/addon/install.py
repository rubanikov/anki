#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Link this directory into an Anki profile's add-on folder.

The add-on lives in the fork, not in a `.ankiaddon` bundle, so "installing" it
is pointing Anki's add-on folder at the source tree. A link rather than a copy:
edit a file here, restart Anki, and the change is live — and there is never a
second copy to wonder about.

    python speedrun/addon/install.py            # default profile base
    python speedrun/addon/install.py --base DIR # a specific ANKI_BASE
    python speedrun/addon/install.py --status   # report, change nothing

This script is a developer convenience. It is not imported by the add-on and
Anki never runs it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
PACKAGE = "speedrun"


def default_base() -> Path:
    """Mirrors aqt.profiles.ProfileManager: ANKI_BASE wins, else the platform
    default."""
    override = os.environ.get("ANKI_BASE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Anki2"
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/Anki2").expanduser()
    data = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(data).expanduser() / "Anki2"


def write_meta() -> None:
    """Seed meta.json from manifest.json.

    Anki reads meta.json, not manifest.json, for an add-on already sitting in
    the folder. It rewrites the file when the user toggles or configures the
    add-on, so it is a local artifact rather than a source file — keep it out of
    version control.
    """
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf8"))
    meta_path = SOURCE / "meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf8"))
        except ValueError:
            meta = {}
    meta.setdefault("config", {})
    for key in (
        "name",
        "homepage",
        "human_version",
        "min_point_version",
        "update_enabled",
    ):
        if key in manifest:
            meta[key] = manifest[key]
    meta["disabled"] = False
    meta["mod"] = 0
    meta_path.write_text(json.dumps(meta, indent=4) + "\n", encoding="utf8")


def link(target: Path, dest: Path) -> str:
    try:
        os.symlink(target, dest, target_is_directory=True)
        return "symlink"
    except OSError:
        if sys.platform != "win32":
            raise
        # Windows refuses symlinks without Developer Mode or elevation. A
        # directory junction needs neither and behaves the same for our purpose.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest), str(target)],
            check=True,
            capture_output=True,
        )
        return "junction"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", help="Anki base folder (defaults to ANKI_BASE or the OS default)"
    )
    parser.add_argument(
        "--status", action="store_true", help="report and change nothing"
    )
    args = parser.parse_args()

    base = Path(args.base) if args.base else default_base()
    dest = base / "addons21" / PACKAGE

    if args.status:
        if not dest.exists():
            print(f"not installed: {dest}")
            return 1
        resolved = dest.resolve()
        print(f"{dest} -> {resolved}")
        print(
            "points at this source tree" if resolved == SOURCE else "points elsewhere"
        )
        return 0

    (base / "addons21").mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        if dest.resolve() == SOURCE:
            write_meta()
            print(f"already linked: {dest} -> {SOURCE}")
            return 0
        print(f"refusing to replace existing {dest}", file=sys.stderr)
        return 1

    kind = link(SOURCE, dest)
    write_meta()
    print(f"linked ({kind}): {dest} -> {SOURCE}")
    print("Restart Anki, then open Tools > Speedrun Dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

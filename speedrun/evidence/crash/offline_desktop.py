#!/usr/bin/env python3
"""Start Anki desktop with the network amputated and photograph the dashboard.

Sets up a throwaway `ANKI_BASE` holding the real Speedrun add-on plus the
`offline_probe` add-on beside this file, plants a collection in it, launches the
app, and waits for the probe to write its report and screenshot.

    PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
        speedrun/evidence/crash/offline_desktop.py \
        --base <throwaway> --col <collection.anki2> \
        --shot speedrun/evidence/crash/desktop-dashboard-offline.png \
        --out speedrun/evidence/crash/desktop-offline.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROFILE = "User 1"


def prepare(base: Path, col: Path) -> None:
    if base.exists():
        shutil.rmtree(base)
    addons = base / "addons21"
    addons.mkdir(parents=True)

    # The add-on under test, copied rather than linked so this base is a
    # self-contained artefact.
    shutil.copytree(REPO / "speedrun" / "addon", addons / "speedrun")
    (addons / "speedrun" / "meta.json").write_text(
        json.dumps({"name": "Speedrun", "disabled": False, "mod": 0}), encoding="utf-8"
    )
    shutil.copytree(HERE / "offline_probe", addons / "t21_offline_probe")
    (addons / "t21_offline_probe" / "meta.json").write_text(
        json.dumps({"name": "T-21 offline probe", "disabled": False, "mod": 0}),
        encoding="utf-8",
    )

    profile = base / PROFILE
    profile.mkdir(parents=True)
    shutil.copy2(col, profile / "collection.anki2")


def launch(base: Path, env_extra: dict, log: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["ANKI_BASE"] = str(base)
    env["ANKI_SINGLE_INSTANCE_KEY"] = f"t21offline{os.getpid()}"
    env["PYTHONPATH"] = os.pathsep.join(
        str(REPO / p) for p in ("pylib", "out/pylib", "qt", "out/qt")
    )
    env.update({k: str(v) for k, v in env_extra.items()})
    handle = open(log, "ab")  # noqa: SIM115
    return subprocess.Popen(
        [sys.executable, "-c", "import aqt; aqt.run()"],
        env=env,
        cwd=str(REPO),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--col", required=True)
    ap.add_argument("--shot", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base = Path(args.base).resolve()
    prepare(base, Path(args.col).resolve())
    report = base / "offline-report.json"

    for attempt in range(1, 5):
        if report.exists():
            report.unlink()
        proc = launch(
            base,
            {"T21_SHOT": Path(args.shot).resolve(), "T21_LOG": report},
            base / "anki-offline.log",
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            if report.exists() or proc.poll() is not None:
                break
            time.sleep(0.5)
        if not report.exists():
            proc.kill()
            proc.wait(timeout=60)
            time.sleep(2)
            continue
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        result = json.loads(report.read_text(encoding="utf-8"))
        result["launch_attempts"] = attempt
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "dashboard_text"}, indent=2))
        print("--- dashboard text ---")
        print(result.get("dashboard_text", "")[:4000])
        return
    raise RuntimeError(
        "the offline probe never reported; app log:\n"
        + (base / "anki-offline.log").read_text(errors="replace")
    )


if __name__ == "__main__":
    main()

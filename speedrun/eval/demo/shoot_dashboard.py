#!/usr/bin/env python3
"""Launch Anki on the demo profile and photograph the dashboard.

Runs the real desktop app against the throwaway `ANKI_BASE` that
`make_demo_history.py` built, with the real Speedrun add-on loaded, and lets
`demo_probe` open **Tools → Speedrun Dashboard** and grab the page. Nothing in
the repo is modified to take the picture and the add-on renders exactly what it
renders for a user.

    PYTHONPATH="pylib;out/pylib;qt;out/qt" out/pyenv/Scripts/python.exe \
        speedrun/eval/demo/shoot_dashboard.py \
        --base <throwaway> \
        --shot speedrun/eval/demo/demo-dashboard.png \
        --shot-scrolled speedrun/eval/demo/demo-dashboard-scrolled.png \
        --out speedrun/eval/demo/shot.json

The base must already hold the generated collection; this script does not create
one, so it can never be pointed at a fresh profile and quietly photograph an
empty dashboard.
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


def install_addons(base: Path) -> None:
    """The real add-on plus the throwaway probe, copied into the demo base."""
    addons = base / "addons21"
    addons.mkdir(parents=True, exist_ok=True)
    for source, name in (
        (REPO / "speedrun" / "addon", "speedrun"),
        (HERE / "demo_probe", "speedrun_demo_probe"),
    ):
        dest = addons / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            source,
            dest,
            ignore=shutil.ignore_patterns("tests", "__pycache__", "meta.json"),
        )
        (dest / "meta.json").write_text(
            json.dumps({"name": name, "disabled": False, "mod": 0}), encoding="utf-8"
        )


def launch(base: Path, env_extra: dict, log: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["ANKI_BASE"] = str(base)
    env["ANKI_SINGLE_INSTANCE_KEY"] = f"speedrundemo{os.getpid()}"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--shot", required=True)
    ap.add_argument("--shot-scrolled", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    base = Path(args.base).resolve()
    col = base / PROFILE / "collection.anki2"
    if not col.exists():
        raise SystemExit(
            f"no generated collection at {col}\n"
            "Run speedrun/eval/demo/make_demo_history.py --base <base> first."
        )
    install_addons(base)

    report = base / "demo-shot.json"
    if report.exists():
        report.unlink()
    proc = launch(
        base,
        {
            "DEMO_SHOT": Path(args.shot).resolve(),
            "DEMO_SHOT_SCROLLED": (
                Path(args.shot_scrolled).resolve() if args.shot_scrolled else ""
            ),
            "DEMO_LOG": report,
        },
        base / "anki-demo.log",
    )
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if report.exists() or proc.poll() is not None:
            break
        time.sleep(0.5)
    if not report.exists():
        proc.kill()
        raise SystemExit(
            "the demo probe never reported; app log:\n"
            + (base / "anki-demo.log").read_text(errors="replace")[-4000:]
        )
    try:
        proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()

    result = json.loads(report.read_text(encoding="utf-8"))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({k: v for k, v in result.items() if k != "dashboard_text"}, indent=2)
    )
    print("--- dashboard text ---")
    print(result.get("dashboard_text", "")[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

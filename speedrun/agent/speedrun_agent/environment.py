# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Finding a model key without ever giving the repository a copy of one.

A key is read from the process environment. If it is not there, one `.env` file
outside the repository may be consulted — and that is the whole mechanism. The
value is put into `os.environ` and nowhere else: not into a config file, not
into a trace, not into a rejection record, not into an artifact. Nothing in this
package writes a key anywhere.

**A `.env` inside the repository is refused, loudly.** That is the one rule
worth enforcing in code rather than in a README, because the failure is silent
and permanent: a key committed once is a key leaked forever, and the check costs
a `is_relative_to`. Somebody will eventually copy the file "just to test", and
this is what stops that copy from being loaded — and so from seeming to work.

The path is configurable. `SPEEDRUN_AGENT_ENV_FILE` wins; otherwise a short list
of conventional locations outside the checkout is tried. Hard-coding one
developer's absolute path would make the service unrunnable on the machine that
grades it.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The repository this service ships inside. Nothing under here may hold a key.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Read in order; the first that exists is used. All are outside REPO_ROOT.
DEFAULT_CANDIDATES: tuple[Path, ...] = (
    REPO_ROOT.parent / "brainlifts" / ".env",
    REPO_ROOT.parent / ".env",
    Path.home() / ".config" / "speedrun" / ".env",
)

#: Names this service will take from a `.env`. An allowlist rather than "every
#: assignment in the file": a dotfile shared with other tooling should not be
#: able to set arbitrary environment variables in this process.
LOADABLE = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY")


class KeyInsideRepository(RuntimeError):
    """A `.env` was found inside the checkout. Refused rather than read."""


def candidates(explicit: Path | str | None = None) -> tuple[Path, ...]:
    if explicit is not None:
        return (Path(explicit),)
    configured = os.environ.get("SPEEDRUN_AGENT_ENV_FILE")
    if configured:
        return (Path(configured),)
    return DEFAULT_CANDIDATES


def _is_inside_repo(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(REPO_ROOT)
    except (OSError, ValueError):
        return False


def load_env(path: Path | str | None = None) -> Path | None:
    """Fill in missing keys from a `.env` outside the repo. Returns what it read.

    `setdefault`, never assignment: a key already exported into the environment
    outranks the file, so a caller can always override without editing anything.
    Returns the path used, or `None` if no candidate existed — a missing file is
    the ordinary state on a machine with no key, not an error.
    """
    for candidate in candidates(path):
        if not candidate.is_file():
            continue
        if _is_inside_repo(candidate):
            raise KeyInsideRepository(
                f"{candidate} is inside {REPO_ROOT}. A key inside the "
                f"repository is one commit away from being public; move it "
                f"outside and point SPEEDRUN_AGENT_ENV_FILE at it."
            )
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name in LOADABLE:
                os.environ.setdefault(name, value.strip().strip('"').strip("'"))
        return candidate
    return None


def key(name: str) -> str | None:
    """A key from the environment, consulting the `.env` once if it is missing.

    Returns the value because a client constructor needs it; every caller in
    this package passes it straight to an SDK and none of them keep it. Use
    `has_key` when all you want to do is report.
    """
    if os.environ.get(name):
        return os.environ[name]
    load_env()
    return os.environ.get(name) or None


def has_key(name: str) -> bool:
    """Is a key available? The only form `/health` and the traces ever see."""
    return key(name) is not None

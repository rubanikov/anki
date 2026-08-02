# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""How a key is found, and the ways it is refused. No key and no network needed.

The rule these tests exist to hold is that the repository never becomes a place
a key can live. Every assertion below is about a way that could stop being true
by accident: a `.env` copied into the checkout "just to test", a dotfile shared
with other tooling setting whatever it likes in this process, a hard-coded path
that only works on one machine, or a file quietly overriding a key the operator
exported on purpose.
"""

from __future__ import annotations

import os

import pytest

from speedrun_agent import environment


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No key and no configured path, before *and* after each test.

    `load_env` writes straight to `os.environ` — that is its whole job — so
    monkeypatch cannot unwind it. Without the teardown a fixture value like
    `OPENAI_API_KEY=fine` survives into the next test and gets searched for as
    if it were a real secret.
    """
    for name in (*environment.LOADABLE, "SPEEDRUN_AGENT_ENV_FILE"):
        monkeypatch.delenv(name, raising=False)
    yield
    for name in environment.LOADABLE:
        os.environ.pop(name, None)


def test_a_dotenv_inside_the_repository_is_refused(tmp_path, monkeypatch):
    """The failure this check exists for is silent, permanent, and public.

    A key committed once is leaked forever, so the refusal is in code rather
    than in a README. It raises rather than skipping: a file that is loaded but
    ignored would look like it worked.
    """
    inside = environment.REPO_ROOT / "speedrun" / "agent" / ".env"
    monkeypatch.setattr(environment, "DEFAULT_CANDIDATES", (inside,))
    inside.write_text("OPENAI_API_KEY=not-a-real-key\n", encoding="utf-8")
    try:
        with pytest.raises(environment.KeyInsideRepository, match="inside"):
            environment.load_env()
        assert "OPENAI_API_KEY" not in os.environ
    finally:
        inside.unlink()


def test_the_path_is_configurable_rather_than_one_machine(tmp_path, monkeypatch):
    """A hard-coded absolute path makes the service unrunnable where it is graded."""
    env_file = tmp_path / "elsewhere.env"
    env_file.write_text("OPENAI_API_KEY=from-the-configured-file\n", encoding="utf-8")
    monkeypatch.setenv("SPEEDRUN_AGENT_ENV_FILE", str(env_file))

    used = environment.load_env()

    assert used == env_file
    assert environment.key("OPENAI_API_KEY") == "from-the-configured-file"


def test_an_exported_key_outranks_the_file(tmp_path, monkeypatch):
    """`setdefault`, never assignment — the operator can always override."""
    env_file = tmp_path / "e.env"
    env_file.write_text("OPENAI_API_KEY=from-the-file\n", encoding="utf-8")
    monkeypatch.setenv("SPEEDRUN_AGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("OPENAI_API_KEY", "from-the-environment")

    environment.load_env()

    assert os.environ["OPENAI_API_KEY"] == "from-the-environment"


def test_only_allowlisted_names_are_taken_from_the_file(tmp_path, monkeypatch):
    """A shared dotfile must not be able to set arbitrary variables in here."""
    env_file = tmp_path / "e.env"
    env_file.write_text(
        "OPENAI_API_KEY=fine\nPATH=/definitely/not\nAWS_SECRET_ACCESS_KEY=no\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SPEEDRUN_AGENT_ENV_FILE", str(env_file))

    environment.load_env()

    assert os.environ["OPENAI_API_KEY"] == "fine"
    assert os.environ["PATH"] != "/definitely/not"
    assert "AWS_SECRET_ACCESS_KEY" not in os.environ


def test_a_missing_file_is_the_ordinary_state(tmp_path, monkeypatch):
    """No key on this machine is normal — the stub runs. It is not an error."""
    monkeypatch.setenv("SPEEDRUN_AGENT_ENV_FILE", str(tmp_path / "absent.env"))

    assert environment.load_env() is None
    assert environment.has_key("OPENAI_API_KEY") is False


SKIP_DIRS = {".git", ".venv", "node_modules", "out", "raw", "__pycache__", "target"}


def _speedrun_files():
    root = environment.REPO_ROOT / "speedrun"
    for path in root.rglob("*"):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
            yield path


def test_no_key_shaped_string_is_written_under_speedrun():
    """The claim, checked rather than asserted: nothing here holds a key.

    A coarse net over the provider key prefixes, and coarse on purpose — the
    expensive mistake is a key reaching a file at all, whichever file it is.
    Scoped to `speedrun/` because that is the only tree this project writes to.
    """
    # Assembled at runtime so this file does not itself trip the scan it runs.
    prefixes = ("sk-" + "proj-", "sk-" + "ant-api", "lsv2" + "_")
    offenders = [
        str(path.relative_to(environment.REPO_ROOT))
        for path in _speedrun_files()
        if any(p in path.read_text(encoding="utf-8", errors="ignore") for p in prefixes)
    ]
    assert offenders == [], f"key-shaped strings found in {offenders}"


def test_the_actual_key_is_in_no_file_here():
    """Stronger, when a key exists: search for that exact value, verbatim.

    Never prints or asserts on the key itself — only on the list of files that
    would have contained it, which is empty.
    """
    secret = environment.key("OPENAI_API_KEY") or environment.key("ANTHROPIC_API_KEY")
    if not secret or len(secret) < 32:
        pytest.skip("no real key available to search for")
    offenders = [
        str(path.relative_to(environment.REPO_ROOT))
        for path in _speedrun_files()
        if secret in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == []

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun's agent service: grounded generation behind a span-level gate.

Runs outside Anki's bundled Python, in its own environment, and nothing in the
desktop app imports it. See `speedrun/agent/README.md`.

`create_app` is deliberately the only export. Everything else — the graph, the
gate, the ledger — is reachable by module path for the eval scripts that need
it, but the service's own surface is one function that returns a FastAPI app.
"""

from .app import create_app

__all__ = ["create_app"]

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Run the service, or ask it one question from the shell.

    uv run speedrun-agent                  # serve on 127.0.0.1:8000
    uv run speedrun-agent --attempt 1D     # one attempt, printed, no server

The `--attempt` mode exists because the gate's behaviour is the thing worth
showing, and a reader should not have to start a server and craft a request to
see an item ship and another get dropped.
"""

from __future__ import annotations

import argparse
import json
import sys

DEFAULT_HOST = "127.0.0.1"
#: The add-on's `agent_url` default is http://127.0.0.1:8000/health.
DEFAULT_PORT = 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speedrun-agent")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--attempt",
        metavar="TOPIC_ID",
        help="run one generation attempt against the built corpus and exit",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if args.attempt:
        return _one_attempt(args.attempt, args.seed)

    import uvicorn  # noqa: PLC0415

    from .app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def _one_attempt(topic_id: str, seed: int) -> int:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from .app import create_app

    with TestClient(create_app()) as client:
        response = client.post(f"/item/generate?topic_id={topic_id}&seed={seed}")
    body = response.json()
    print(f"HTTP {response.status_code}")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0 if response.status_code in (200, 409) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Traces, with or without LangSmith, in the same shape either way.

SPEC says LangSmith. LangSmith needs a key, and no key was available, so the
default is a local JSONL tracer that emits the *same record shape* LangSmith's
API takes — `id`, `trace_id`, `parent_run_id`, `name`, `run_type`,
`start_time`/`end_time`, `inputs`, `outputs`, `error`, `extra`. Matching the
shape is the point: when a key appears, `LangSmithTracer` takes over and nothing
that reads traces has to learn a second format, and the local runs can be posted
after the fact rather than thrown away.

What is traced is the attribution triple. Every node's span carries the
`{output, source_id, span}` it produced, so a trace is not "the graph ran" — it
is a re-checkable record of which characters, in which page, licensed the item
that shipped. A rejection is traced the same way, carrying its reason.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol


class Span(Protocol):
    """A single traced step; the caller records its outcome before it closes."""

    def outputs(self, **values: Any) -> None: ...
    def error(self, message: str) -> None: ...


class Tracer(Protocol):
    name: str

    def run(
        self, name: str, run_type: str = "chain", **inputs: Any
    ) -> contextlib.AbstractContextManager[Span]: ...


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class _LocalSpan:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def outputs(self, **values: Any) -> None:
        self._record["outputs"].update(values)

    def error(self, message: str) -> None:
        self._record["error"] = message


class LocalTracer:
    """Append-only JSONL in LangSmith's run shape. The no-key default."""

    name = "local-jsonl"

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._stack: threading.local = threading.local()

    @property
    def path(self) -> Path:
        return self._path

    def _ids(self) -> tuple[str | None, str | None]:
        stack: list[tuple[str, str]] = getattr(self._stack, "stack", [])
        if not stack:
            return None, None
        parent, trace = stack[-1]
        return parent, trace

    @contextlib.contextmanager
    def run(self, name: str, run_type: str = "chain", **inputs: Any) -> Iterator[Span]:
        parent_id, trace_id = self._ids()
        run_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": run_id,
            "trace_id": trace_id or run_id,
            "parent_run_id": parent_id,
            "name": name,
            "run_type": run_type,
            "start_time": _now(),
            "end_time": None,
            "inputs": inputs,
            "outputs": {},
            "error": None,
            "extra": {"tracer": self.name},
        }
        stack: list[tuple[str, str]] = getattr(self._stack, "stack", [])
        stack.append((run_id, record["trace_id"]))
        self._stack.stack = stack
        span = _LocalSpan(record)
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            span.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            stack.pop()
            record["end_time"] = _now()
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")


class LangSmithTracer:
    """The SPEC path, used only when a LangSmith key is in the environment.

    **Untested.** No LangSmith key was available, so this has never posted a
    run. It is deliberately thin — `langsmith.trace` already produces the record
    shape `LocalTracer` imitates — so there is little here to be wrong.
    """

    name = "langsmith"

    def __init__(self, project: str = "speedrun-agent") -> None:
        from langsmith import run_helpers  # noqa: PLC0415

        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_PROJECT", project)
        self._trace = run_helpers.trace

    @contextlib.contextmanager
    def run(self, name: str, run_type: str = "chain", **inputs: Any) -> Iterator[Span]:
        with self._trace(name=name, run_type=run_type, inputs=inputs) as run_tree:

            class _Span:
                def outputs(self, **values: Any) -> None:
                    run_tree.end(outputs=values)

                def error(self, message: str) -> None:
                    run_tree.end(error=message)

            yield _Span()


def langsmith_key() -> str | None:
    return (
        os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or None
    )


def default_tracer(local_path: Path | str) -> Tracer:
    if langsmith_key() is not None:
        try:
            return LangSmithTracer()
        except Exception:  # noqa: BLE001 - tracing must never take the service down
            pass
    return LocalTracer(local_path)

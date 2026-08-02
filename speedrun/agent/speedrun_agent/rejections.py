# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Why items were dropped, counted so Yield can be taken apart.

Yield — usable items per hundred generation attempts — is one number, and one
number is not a finding. ADR-0006 makes the decomposition a requirement rather
than a nicety: the retrieval comparison holds the gate constant and varies the
retriever, so the interesting movement is *which* reason stopped an item, not
how many were stopped. A retriever that fetches the wrong page and a generator
that invents an answer both show up as a lower yield and are not the same
problem.

So every attempt is recorded — shipped ones too, because a rate needs its
denominator — with exactly one reason, drawn from a closed set. The set is
closed on purpose: a free-text reason cannot be counted, and a reason invented
at the call site is a category nobody agreed to.

The log is append-only JSONL. It is evidence, not state: deleting it loses the
decomposition and nothing else.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any


class Reason(StrEnum):
    """Every way an attempt can fail to produce a shippable item.

    Adding a member is a deliberate act: it changes what the yield table can
    say. Removing one silently merges two findings.
    """

    #: Retrieval returned nothing for the topic. The corpus, not the generator.
    NO_RETRIEVAL = "no_retrieval"
    #: The generator declined to propose anything for this topic and seed.
    GENERATOR_EMPTY = "generator_empty"
    #: The proposal was missing a stem, an answer, or its distractors.
    MALFORMED_ITEM = "malformed_item"
    #: The stem contains the answer verbatim. Not a Leakage in the CONTEXT.md
    #: sense — nothing has reached the student — but the item cannot test
    #: anything, so it is dropped rather than shown.
    ANSWER_LEAKS_INTO_STEM = "answer_leaks_into_stem"
    #: The gate's own rejection: no span in the retrieved text supports the
    #: correct answer. This is the one the project exists to count.
    ANSWER_NOT_IN_RETRIEVED_TEXT = "answer_not_in_retrieved_text"
    #: A span was located but did not survive re-checking against its page.
    #: An index that disagrees with itself; the item is not shown either way.
    SPAN_FAILED_REVERIFICATION = "span_failed_reverification"
    #: An output reached the boundary with no source. Unreachable by
    #: construction; counted so that "unreachable" stays a measured claim.
    UNATTRIBUTED_OUTPUT = "unattributed_output"


SHIPPED = "shipped"


@dataclasses.dataclass(frozen=True)
class Attempt:
    """One generation attempt and what became of it."""

    attempt_id: str
    topic_id: str
    seed: int
    generator: str
    outcome: str  #: SHIPPED, or a Reason value
    #: The provider's *resolved* model id — `gpt-5-2025-08-07`, not `gpt-5`.
    #: A Yield figure attributed to a moving alias is not a measurement anyone
    #: can repeat, and this ledger is what #16 reads.
    model: str = ""
    detail: str = ""
    source_id: str | None = None
    citation: str | None = None
    retrieved: tuple[str, ...] = ()
    at_ms: int = dataclasses.field(default_factory=lambda: int(time.time() * 1000))

    @property
    def shipped(self) -> bool:
        return self.outcome == SHIPPED

    def as_dict(self) -> dict[str, Any]:
        record = dataclasses.asdict(self)
        record["retrieved"] = list(self.retrieved)
        return record


class AttemptLog:
    """Append-only record of attempts, plus the counters #16 reads.

    Thread-safe because uvicorn will call it from a threadpool, and a yield
    denominator that races is worse than no yield at all.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._attempts: list[Attempt] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, attempt: Attempt) -> Attempt:
        line = json.dumps(attempt.as_dict(), ensure_ascii=False)
        with self._lock:
            self._attempts.append(attempt)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        return attempt

    def rejections(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            dropped = [a for a in self._attempts if not a.shipped]
        return [a.as_dict() for a in dropped[-limit:]]

    def tally(self) -> dict[str, Any]:
        """Yield, and the reasons it is not higher.

        `yield_per_hundred` is reported as `None` rather than 0 when nothing has
        been attempted: a rate over an empty denominator is an abstention, and
        this project does not print numbers it cannot support.

        `models` lists every resolved model id that contributed, so a tally can
        never be read as belonging to a model it was not produced by.
        """
        with self._lock:
            attempts = list(self._attempts)
        shipped = sum(1 for a in attempts if a.shipped)
        by_reason = Counter(a.outcome for a in attempts if not a.shipped)
        return {
            "attempts": len(attempts),
            "shipped": shipped,
            "rejected": len(attempts) - shipped,
            "generators": sorted({a.generator for a in attempts}),
            "models": sorted({a.model for a in attempts if a.model}),
            "yield_per_hundred": (
                round(100.0 * shipped / len(attempts), 1) if attempts else None
            ),
            "by_reason": {reason: by_reason.get(reason, 0) for reason in Reason},
            "log": str(self._path) if self._path else None,
        }

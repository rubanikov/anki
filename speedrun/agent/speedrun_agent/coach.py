# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach loop — and the one ordering constraint that makes it a measurement.

PRD §4.2 lists seven steps. Four are built here (cold question, confidence,
explain aloud, contrast pair) plus the rule statement; revision and the personal
guide are cut, and the cut is recorded in the README rather than hidden behind a
`TODO`.

**The server owns the order, not the client.** That is the whole reason this is a
state machine on the service rather than a sequence of calls the add-on makes in
whatever order it likes. Confidence stated *after* the answer is revealed is not
a weaker measurement, it is not a measurement at all — it is a memory of having
been right. So the correct answer is not in any response body until the
confidence for that item is on the record, and a client that asks for the reveal
early gets a 409 rather than a shortcut. There is no flag, no query parameter and
no "skip" path: `Session.awaiting` names the single thing the next turn may
carry, and anything else is refused.

**Only step 1 scores.** The answer is graded the moment it arrives — before the
student is told anything — and everything after it is teaching. Steps 3 onward
are never graded, and the agent asks once and then stays quiet: each prompt is
emitted exactly once, and no step re-prompts a student who said little.

**Speak-rate is measured, not assumed.** Every prompt that asks the student to
say something is recorded with whether they actually spoke, because a voice-first
loop whose speak-rate nobody counted is a design intention rather than a
finding. It is a pre-registered measure in the ablation, so it is logged the same
way Yield is: append-only, with an abstention rather than a zero when the
denominator is empty.

This module holds no HTTP and no graph. It is handed an already-shipped item —
one that cleared the Generation gate — and it never asks a model whether an
answer is right.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
import threading
import time
import uuid
from collections import OrderedDict
from enum import StrEnum
from pathlib import Path
from typing import Any

# --- the steps ------------------------------------------------------------


class Step(StrEnum):
    """Where a session is. The value is what the student is being asked for.

    `ANSWER` and `CONFIDENCE` are the graded half's two halves and their order
    is the invariant. `EXPLAIN`, `CONTRAST` and `RULE` are teaching and are
    never graded.
    """

    #: Step 1. The cold question, no hint, no explanation. The only scored step.
    ANSWER = "answer"
    #: Step 2. Stated before the answer is revealed. Never after.
    CONFIDENCE = "confidence"
    #: Step 3. "Explain what this question is actually testing."
    EXPLAIN = "explain"
    #: Step 4. The contrast pair. Protected from cuts.
    CONTRAST = "contrast"
    #: Step 6. The app states the rule, in the source's own words.
    RULE = "rule"
    DONE = "done"


class Confidence(StrEnum):
    """Three levels, because they are spoken aloud and not typed."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: What each step asks for. A turn carrying anything else is refused.
AWAITS: dict[Step, str] = {
    Step.ANSWER: "choice",
    Step.CONFIDENCE: "confidence",
    Step.EXPLAIN: "spoken",
    Step.CONTRAST: "spoken",
    Step.RULE: "nothing",
    Step.DONE: "nothing",
}

PROMPTS: dict[Step, str] = {
    Step.ANSWER: "Say your answer out loud, then choose it.",
    Step.CONFIDENCE: (
        "Before you see the answer: how confident are you? Say it out loud, "
        "then pick one."
    ),
    Step.EXPLAIN: (
        "Explain what this question is actually testing. Not why you picked "
        "your option — what the question is for."
    ),
    Step.CONTRAST: "Same question, one detail changed. What does that change do?",
    Step.RULE: "",
}

#: Steps at which the student is asked to speak. Speak-rate's denominator.
SPOKEN_STEPS: tuple[Step, ...] = (
    Step.ANSWER,
    Step.CONFIDENCE,
    Step.EXPLAIN,
    Step.CONTRAST,
)


class TurnRefused(ValueError):
    """The turn did not carry what the current step is waiting for.

    Raised — rather than tolerated — because every way of being lenient here is
    a way of letting a client reveal the answer before confidence is recorded.
    """

    def __init__(self, message: str, awaiting: str) -> None:
        super().__init__(message)
        self.awaiting = awaiting


# --- the contrast pair ----------------------------------------------------

#: Pairs whose members differ by exactly one detail of the kind an MCAT item
#: turns on. Not a thesaurus and not generated: a fixed table, so "one detail
#: changed" is a property of the data rather than a promise about a model.
#: Longer members are tried first within a pair, so `without` is not matched as
#: `with`.
SWAPS: tuple[tuple[str, str], ...] = (
    ("prokaryotic", "eukaryotic"),
    ("prokaryotes", "eukaryotes"),
    ("mitosis", "meiosis"),
    ("competitive", "noncompetitive"),
    ("hypertonic", "hypotonic"),
    ("endergonic", "exergonic"),
    ("anabolic", "catabolic"),
    ("aerobic", "anaerobic"),
    ("sympathetic", "parasympathetic"),
    ("afferent", "efferent"),
    ("dominant", "recessive"),
    ("depolarizes", "hyperpolarizes"),
    ("oxidizes", "reduces"),
    ("oxidation", "reduction"),
    ("activates", "inhibits"),
    ("increases", "decreases"),
    ("increased", "decreased"),
    ("presence", "absence"),
    ("higher", "lower"),
    ("before", "after"),
    ("without", "with"),
    ("more", "less"),
    ("small intestine", "large intestine"),
    ("cytoplasm", "mitochondrion"),
    ("nucleus", "cytoplasm"),
    ("DNA", "RNA"),
    ("acid", "base"),
    ("positive", "negative"),
    ("first", "second"),
    ("transcription", "translation"),
    ("dephosphorylation", "phosphorylation"),
    ("exothermic", "endothermic"),
    ("hydrolysis", "condensation"),
    ("endocytosis", "exocytosis"),
    ("hydrophobic", "hydrophilic"),
    ("unsaturated", "saturated"),
    ("nonpolar", "polar"),
    ("antagonist", "agonist"),
    ("inhibitor", "activator"),
    ("reactants", "products"),
    ("reactant", "product"),
    ("absorption", "secretion"),
    ("systole", "diastole"),
    ("arteries", "veins"),
    ("artery", "vein"),
    ("anion", "cation"),
    ("excess", "shortage"),
)

STEM_DETAIL = "stem_detail"
ANSWER_SWAP = "answer_swap"


@dataclasses.dataclass(frozen=True)
class ContrastPair:
    """The same question with exactly one detail changed.

    "Exactly one" is checkable rather than asserted. For `STEM_DETAIL`, `at` is
    the character offset of the change and `changed_from` is the text that was
    there, so a reader — or a test — can reconstruct the original from the pair
    and confirm nothing else moved. For `ANSWER_SWAP` the stem is untouched and
    the one changed detail is which option is correct.
    """

    stem: str
    changed_from: str
    changed_to: str
    kind: str
    prompt: str
    at: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _cased_like(model: str, replacement: str) -> str:
    """Match the capitalisation of the text being replaced, and nothing else."""
    if model[:1].isupper() and not model.isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def contrast_pair(stem: str, answer: str, distractors: tuple[str, ...]) -> ContrastPair:
    """Build the contrast pair. Never returns None; the pair is not optional.

    First choice is a one-word swap inside the stem — the strongest form, since
    the student can see that only one thing moved. When no pair in the table
    applies, the changed detail is *which option is correct*, which is still one
    detail and is still a question the student has to talk through. The weaker
    form is labelled rather than disguised, so a reader can count how often it
    was used.

    Only ever called after the reveal, so naming the answer here is not Leakage.
    """
    for a, b in SWAPS:
        for source, target in sorted(((a, b), (b, a)), key=lambda p: -len(p[0])):
            match = re.search(rf"\b{re.escape(source)}\b", stem, flags=re.IGNORECASE)
            if match is None:
                continue
            found = match.group(0)
            replacement = _cased_like(found, target)
            changed = stem[: match.start()] + replacement + stem[match.end() :]
            return ContrastPair(
                stem=changed,
                changed_from=found,
                changed_to=replacement,
                kind=STEM_DETAIL,
                at=match.start(),
                prompt=(
                    f"Same question, with {found!r} changed to {replacement!r} "
                    f"and nothing else. Say what that one change does."
                ),
            )

    other = distractors[0] if distractors else ""
    return ContrastPair(
        stem=stem,
        changed_from=answer,
        changed_to=other,
        kind=ANSWER_SWAP,
        at=None,
        prompt=(
            f"Same question, one detail changed: suppose the answer were "
            f"{other!r} instead of {answer!r}. Say what would have to be "
            f"different about the question for that to be true."
        ),
    )


# --- the rule -------------------------------------------------------------


#: How far either side of a span the rule may reach for its sentence. Bounded
#: so a page with no sentence punctuation yields a paragraph rather than a book.
RULE_WINDOW = 400

#: Below this, the widened text has not said anything — see the glossary case
#: in `widen_to_sentence`.
MIN_RULE_CHARS = 80

#: End of a sentence, or a blank line. Both are needed: the corpus holds prose
#: pages *and* key-terms pages, and a key-terms page has almost no full stops in
#: it, so a sentence-only rule ran the whole window together into one blob.
_BOUNDARY = re.compile(r"[.!?][\"')\]]?\s+|\n\s*\n")


def widen_to_sentence(page_text: str, start: int, end: int) -> str:
    """The sentence containing a span, taken from the page's own characters.

    The Generation gate's span is as narrow as it can be — often the answer
    phrase alone — because a narrow span is a stronger claim about grounding.
    That makes it a good citation and a poor rule: *"substrate-level
    phosphorylation"* is not a statement of anything. So the rule widens to the
    surrounding sentence, and it widens by **copying** rather than composing:
    the characters are the page's, sliced from the same text the gate
    re-verified against. Nothing is generated here.

    The one wrinkle is real and was found by running it. OpenStax key-terms
    pages are *term*, blank line, *definition* — and the span usually lands on
    the term, so stopping at the first boundary returns the term again and the
    rule says nothing. When the widened text is shorter than `MIN_RULE_CHARS`
    the window extends through the following block, which on those pages is the
    definition. It is a heuristic about page shape, and it can only ever change
    *how much* of the source is quoted, never whether the quote is the source's.

    Returns the empty string when the offsets do not fit the text, which is the
    honest answer — the caller then falls back to the span's own quote rather
    than to an invented sentence.
    """
    if not page_text or not (0 <= start < end <= len(page_text)):
        return ""
    left = max(0, start - RULE_WINDOW)
    before = page_text[left:start]
    boundaries = list(_BOUNDARY.finditer(before))
    begin = left + boundaries[-1].end() if boundaries else left
    after = page_text[end : min(len(page_text), end + RULE_WINDOW)]
    stops = [match.end() for match in _BOUNDARY.finditer(after)]
    finish = end + (stops[0] if stops else len(after))
    if len(page_text[begin:finish].strip()) < MIN_RULE_CHARS and len(stops) > 1:
        finish = end + stops[1]
    return page_text[begin:finish].strip()


def rule_statement(quote: str, citation: str, source_id: str | None) -> dict[str, Any]:
    """Step 6, and it is a quotation rather than a composition.

    The app states the rule *after* the student has talked, and what it states
    is the supporting text the Generation gate already found and re-verified —
    the source's own characters, with the citation that locates them. Asking a
    model to phrase a rule here would put an unchecked sentence at the end of a
    loop whose whole point is that nothing unchecked is shown.
    """
    return {
        "lead": "The rule, in the source's own words:",
        "text": quote,
        "citation": citation,
        "source_id": source_id,
    }


# --- speak-rate -----------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Utterance:
    """One prompt, and whether the student actually spoke into it."""

    session_id: str
    step: str
    spoke: bool
    transcribed: bool = False
    audio_ms: int = 0
    at_ms: int = dataclasses.field(default_factory=lambda: int(time.time() * 1000))

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class SpeakLog:
    """Append-only record of prompts and whether they were spoken into.

    Shaped like `AttemptLog` on purpose: speak-rate is a pre-registered measure
    in the ablation, and a measure that lives in a different format from the
    other measures is a measure somebody will forget to collect.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._utterances: list[Utterance] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, utterance: Utterance) -> Utterance:
        line = json.dumps(utterance.as_dict(), ensure_ascii=False)
        with self._lock:
            self._utterances.append(utterance)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        return utterance

    def tally(self) -> dict[str, Any]:
        """Speak-rate, abstaining over an empty denominator.

        `speak_rate` is `None` rather than `0.0` before any prompt, for the same
        reason `/gate/yield` abstains: a share with nothing underneath it is not
        a low share.
        """
        with self._lock:
            utterances = list(self._utterances)
        prompts = len(utterances)
        spoken = sum(1 for u in utterances if u.spoke)
        by_step: dict[str, dict[str, int]] = {}
        for step in SPOKEN_STEPS:
            rows = [u for u in utterances if u.step == str(step)]
            by_step[str(step)] = {
                "prompts": len(rows),
                "spoken": sum(1 for u in rows if u.spoke),
            }
        return {
            "prompts": prompts,
            "spoken": spoken,
            "speak_rate": round(spoken / prompts, 3) if prompts else None,
            "transcribed": sum(1 for u in utterances if u.transcribed),
            "by_step": by_step,
            "sessions": len({u.session_id for u in utterances}),
            "log": str(self._path) if self._path else None,
        }


# --- the session ----------------------------------------------------------


@dataclasses.dataclass
class Session:
    """One run of the loop over one held-out item.

    Mutable, and deliberately dull: the interesting behaviour is which step may
    follow which, and that lives in `turn`.
    """

    session_id: str
    topic_id: str
    attempt_id: str
    stem: str
    answer: str
    choices: tuple[str, ...]
    correct_index: int
    quote: str
    citation: str
    source_id: str | None
    #: The sentence the rule is read from — the span widened to its surrounding
    #: sentence, still the page's own characters. Empty when the offsets did not
    #: fit, in which case the rule falls back to the span's own quote.
    rule_text: str = ""
    model: str = ""
    step: Step = Step.ANSWER
    chosen_index: int | None = None
    correct: bool | None = None
    confidence: Confidence | None = None
    started_ms: int = dataclasses.field(default_factory=lambda: int(time.time() * 1000))

    @property
    def awaiting(self) -> str:
        return AWAITS[self.step]

    @property
    def revealed(self) -> bool:
        """Has the correct answer been disclosed to this client yet?

        False until confidence is recorded. Every response body is assembled
        from this flag, so there is one place to get it wrong rather than one
        per field.
        """
        return self.confidence is not None

    def question(self) -> dict[str, Any]:
        """The cold question. Carries no answer, no index, no hint."""
        return {
            "topic_id": self.topic_id,
            "attempt_id": self.attempt_id,
            "stem": self.stem,
            "choices": list(self.choices),
        }

    def reveal(self) -> dict[str, Any] | None:
        """The answer — or `None`, which is what a client sees before step 2.

        This is the enforcement point. There is no second path to the answer:
        no field on the question, no debug route, no "include_answer" flag.
        """
        if not self.revealed:
            return None
        return {
            "correct_index": self.correct_index,
            "correct_answer": self.answer,
            "your_choice": self.chosen_index,
            "correct": self.correct,
            "confidence": str(self.confidence) if self.confidence else None,
            "citation": self.citation,
            "quote": self.quote,
        }

    def scored(self) -> dict[str, Any] | None:
        """Step 1's record. The only thing in this loop that counts.

        The grading happens the moment the answer arrives — `self.correct` is
        fixed before the student says anything else — but it is *disclosed* on
        the same terms as the reveal. An earlier draft returned this record as
        soon as the answer landed, which handed a client `correct: true` on the
        confidence screen and made the confidence worthless. The rule is the
        same one field: nothing derived from the answer leaves before step 2.
        """
        if self.correct is None or not self.revealed:
            return None
        return {
            "step": str(Step.ANSWER),
            "topic_id": self.topic_id,
            "attempt_id": self.attempt_id,
            "correct": self.correct,
            "confidence": str(self.confidence) if self.confidence else None,
            "graded": True,
        }


def _shuffled(answer: str, distractors: tuple[str, ...], seed: int) -> tuple[list[str], int]:
    """Options in a fixed order for a given seed, and where the answer landed.

    Seeded rather than random so a session can be replayed: an item whose option
    order moves between runs cannot be re-examined after the fact.
    """
    options = [answer, *distractors]
    rng = random.Random(f"{seed}:{answer}")
    rng.shuffle(options)
    return options, options.index(answer)


def start(
    shipped: dict[str, Any],
    *,
    topic_id: str,
    seed: int = 0,
    session_id: str | None = None,
    page_text: str = "",
) -> Session:
    """Open a session over an item that already cleared the Generation gate.

    `shipped` is `attribution.payload`'s output — item, source_id, span,
    citation. Nothing here can construct an item, which is the point: the coach
    cannot show a question the gate did not pass.

    `page_text` is the source page the span was verified against, and it is
    optional: without it the rule quotes the span alone, which is correct but
    terse. It is never used to *find* anything — only to widen a span that has
    already been located and re-checked.
    """
    item = shipped["item"]
    span = shipped.get("span") or {}
    distractors = tuple(item.get("distractors", ()))
    choices, correct_index = _shuffled(item["answer"], distractors, seed)
    return Session(
        session_id=session_id or uuid.uuid4().hex[:12],
        topic_id=topic_id,
        attempt_id=shipped.get("attempt_id", ""),
        stem=item["stem"],
        answer=item["answer"],
        choices=tuple(choices),
        correct_index=correct_index,
        quote=span.get("quote", ""),
        citation=shipped.get("citation", ""),
        source_id=shipped.get("source_id"),
        rule_text=widen_to_sentence(
            page_text, int(span.get("start", 0)), int(span.get("end", 0))
        ),
        model=item.get("model", ""),
    )


def turn(
    session: Session,
    *,
    spoke: bool = False,
    choice: int | None = None,
    confidence: str | None = None,
    transcript: str | None = None,
    audio_ms: int = 0,
    log: SpeakLog | None = None,
) -> dict[str, Any]:
    """Advance one step, or refuse.

    The refusal is the feature. A client that posts a confidence while the
    session is waiting for an answer, or that tries to advance past the
    confidence step without giving one, gets `TurnRefused` — so "confidence
    before the reveal" is enforced by the only code path that can produce a
    reveal, not by the order the UI happens to render its buttons in.
    """
    step = session.step
    if step in (Step.RULE, Step.DONE):
        raise TurnRefused("this session is finished", AWAITS[step])

    if step is Step.ANSWER:
        if choice is None or not (0 <= int(choice) < len(session.choices)):
            raise TurnRefused(
                f"step {step} needs a choice in 0..{len(session.choices) - 1}",
                AWAITS[step],
            )
        session.chosen_index = int(choice)
        # Graded here, disclosed later. Step 1 is the only thing that scores.
        session.correct = session.chosen_index == session.correct_index
        session.step = Step.CONFIDENCE

    elif step is Step.CONFIDENCE:
        try:
            session.confidence = Confidence(str(confidence or "").strip().lower())
        except ValueError:
            raise TurnRefused(
                f"step {step} needs one of "
                f"{', '.join(str(c) for c in Confidence)}",
                AWAITS[step],
            ) from None
        session.step = Step.EXPLAIN

    elif step is Step.EXPLAIN:
        session.step = Step.CONTRAST

    elif step is Step.CONTRAST:
        session.step = Step.RULE

    if log is not None:
        log.record(
            Utterance(
                session_id=session.session_id,
                step=str(step),
                spoke=bool(spoke),
                transcribed=bool(transcript),
                audio_ms=int(audio_ms),
            )
        )
    return state(session)


def state(session: Session) -> dict[str, Any]:
    """The whole client-visible session. Assembled once, from `revealed`.

    Every field that could carry the answer is derived from `Session.reveal`,
    so there is a single place where the disclosure rule is applied.
    """
    body: dict[str, Any] = {
        "session_id": session.session_id,
        "topic_id": session.topic_id,
        "step": str(session.step),
        "awaiting": session.awaiting,
        "prompt": PROMPTS.get(session.step, ""),
        "speak": session.step in SPOKEN_STEPS,
        "question": session.question(),
        "reveal": session.reveal(),
        "scored": session.scored(),
        "contrast": None,
        "rule": None,
        "graded_steps": [str(Step.ANSWER)],
    }
    if session.revealed and session.step in (Step.CONTRAST, Step.RULE):
        pair = contrast_pair(
            session.stem,
            session.answer,
            tuple(c for c in session.choices if c != session.answer),
        )
        body["contrast"] = pair.as_dict()
        if session.step is Step.CONTRAST:
            body["prompt"] = pair.prompt
    if session.step is Step.RULE:
        # Step 6, and the end of the loop. The agent asked once per step and is
        # now finished; there is no state after this that re-prompts anybody.
        body["rule"] = rule_statement(
            session.rule_text or session.quote, session.citation, session.source_id
        )
    return body


class Sessions:
    """In-memory session registry, oldest evicted first.

    **Not a checkpointer.** A LangGraph checkpointer would survive a restart;
    this does not, and a session interrupted by one is lost. That is stated
    rather than papered over — the graded property is the step order within a
    session, and losing a session loses a teaching loop, not a score.
    """

    def __init__(self, limit: int = 64) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def put(self, session: Session) -> Session:
        with self._lock:
            self._sessions[session.session_id] = session
            while len(self._sessions) > self._limit:
                self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

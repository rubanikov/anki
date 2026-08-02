# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach loop, tested at the HTTP boundary and mostly about one ordering.

Everything here drives `create_app` over HTTP, the way the gate tests do, for
the same reason: the graded claim is about what a client can obtain, and a test
that called `coach.turn` directly would prove things about a function while the
route stayed free to add a shortcut.

The load-bearing test is `test_the_answer_is_absent_until_confidence_is_stated`.
It does not check that the reveal is late; it checks that the answer *string*
appears nowhere in any byte a client receives before its confidence is on the
record — because "the answer is not in the `reveal` field" is satisfied by an
implementation that also puts it in `question.choices[correct_index]` under
another name.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import ANSWER, TOPIC
from fastapi.testclient import TestClient

from speedrun_agent import coach, coach_voice
from speedrun_agent.app import create_app
from speedrun_agent.rejections import AttemptLog


@pytest.fixture
def client(supporting_corpus, claiming_generator, tmp_path) -> Any:
    app = create_app(
        corpus=supporting_corpus,
        generator=claiming_generator,
        log=AttemptLog(tmp_path / "attempts.jsonl"),
        speak_log=coach.SpeakLog(tmp_path / "utterances.jsonl"),
        out_dir=tmp_path,
    )
    with TestClient(app) as running:
        yield running


def _start(client: Any) -> dict[str, Any]:
    response = client.post(f"/coach/start?topic_id={TOPIC}&seed=0")
    assert response.status_code == 200, response.text
    return response.json()


def _turn(client: Any, session_id: str, **fields: Any) -> Any:
    return client.post("/coach/turn", json={"session_id": session_id, **fields})


# --- step 1: the cold question -------------------------------------------


def test_the_loop_opens_on_a_gated_item_asked_cold(client):
    """Step 1 is a held-out item with no hint, no explanation and no answer."""
    state = _start(client)

    assert state["step"] == coach.Step.ANSWER
    assert state["awaiting"] == "choice"
    assert state["question"]["stem"]
    assert len(state["question"]["choices"]) == 4
    assert state["reveal"] is None
    assert state["scored"] is None
    assert state["graded_steps"] == [coach.Step.ANSWER]


def test_an_item_the_gate_dropped_does_not_become_a_coach_question(
    silent_corpus, claiming_generator, tmp_path
):
    """No coach-only path around the Generation gate.

    The coach shares `/item/generate`'s graph run, so a claim no source supports
    is refused here exactly as it is there — with the gate's own reason, and
    with no fallback question.
    """
    app = create_app(
        corpus=silent_corpus,
        generator=claiming_generator,
        log=AttemptLog(tmp_path / "attempts.jsonl"),
        speak_log=coach.SpeakLog(tmp_path / "utterances.jsonl"),
        out_dir=tmp_path,
    )
    with TestClient(app) as running:
        response = running.post(f"/coach/start?topic_id={TOPIC}&seed=0")

    assert response.status_code == 409
    body = response.json()
    assert body["item"] is None
    assert body["rejected"]["reason"] == "answer_not_in_retrieved_text"


# --- step 2: confidence, before the reveal --------------------------------


def test_the_answer_is_absent_until_confidence_is_stated(client):
    """The measurement's whole validity, asserted against the raw bytes.

    Confidence stated after seeing the answer is not a weaker number, it is not
    a number. So the assertion is not "the reveal field is null" but "the string
    `citric acid cycle` is nowhere in what the client was sent" — for every
    response up to and including the answer turn.
    """
    started = client.post(f"/coach/start?topic_id={TOPIC}&seed=0")
    state = started.json()
    session_id = state["session_id"]
    correct_option = None
    for index, choice in enumerate(state["question"]["choices"]):
        if choice.casefold() == ANSWER.casefold():
            correct_option = index

    # The cold question. The answer is one of the four options, so it is on
    # screen — but nothing says which, and no field names it.
    assert started.text.count(ANSWER) == 1  # the option itself, and only that
    assert state["reveal"] is None

    answered = _turn(client, session_id, choice=correct_option, spoke=True)
    assert answered.status_code == 200
    # After answering and before stating confidence: still nothing.
    assert answered.json()["reveal"] is None
    assert answered.json()["step"] == coach.Step.CONFIDENCE
    # `scored` is fixed at this point and must still not be disclosed: an
    # earlier draft returned it here, which put `correct: true` on the
    # confidence screen and made the confidence a memory rather than a measure.
    assert answered.json()["scored"] is None
    assert "correct" not in answered.text
    assert answered.text.count(ANSWER) == 1

    revealed = _turn(client, session_id, confidence="high", spoke=True)
    assert revealed.status_code == 200
    reveal = revealed.json()["reveal"]
    assert reveal is not None
    assert reveal["correct_answer"] == ANSWER
    assert reveal["correct"] is True
    assert reveal["confidence"] == "high"


def test_the_reveal_cannot_be_reached_by_skipping_the_confidence(client):
    """A client that posts the next step's payload early is refused, not helped."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)

    # The session is waiting for a confidence; this turn carries none.
    skipped = _turn(client, session_id, spoke=True)

    assert skipped.status_code == 409
    body = skipped.json()
    assert body["awaiting"] == "confidence"
    assert body["step"] == coach.Step.CONFIDENCE
    assert ANSWER not in skipped.text


def test_an_unrecognised_confidence_is_refused_rather_than_defaulted(client):
    """Defaulting to `medium` would invent the measurement rather than take it."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)

    refused = _turn(client, session_id, confidence="pretty sure", spoke=True)

    assert refused.status_code == 409
    assert refused.json()["awaiting"] == "confidence"


def test_the_answer_turn_is_graded_and_nothing_after_it_is(client):
    """Only step 1 scores. The rest are teaching and say so."""
    state = _start(client)
    session_id = state["session_id"]
    wrong = next(
        index
        for index, choice in enumerate(state["question"]["choices"])
        if choice.casefold() != ANSWER.casefold()
    )

    _turn(client, session_id, choice=wrong, spoke=True)
    after_confidence = _turn(client, session_id, confidence="low", spoke=True).json()
    assert after_confidence["scored"]["correct"] is False
    assert after_confidence["scored"]["step"] == coach.Step.ANSWER

    after_explain = _turn(client, session_id, spoke=True).json()
    after_contrast = _turn(client, session_id, spoke=True).json()
    for state_after in (after_explain, after_contrast):
        assert state_after["graded_steps"] == [coach.Step.ANSWER]
        assert state_after["scored"]["step"] == coach.Step.ANSWER


# --- steps 3, 4 and the rule ---------------------------------------------


def test_the_loop_runs_explain_then_contrast_then_the_rule(client):
    """The four built steps in order, each prompt emitted exactly once."""
    state = _start(client)
    session_id = state["session_id"]
    steps = [state["step"]]
    prompts = [state["prompt"]]

    for fields in (
        {"choice": 0},
        {"confidence": "medium"},
        {},
        {},
    ):
        state = _turn(client, session_id, spoke=True, **fields).json()
        steps.append(state["step"])
        prompts.append(state["prompt"])

    assert steps == ["answer", "confidence", "explain", "contrast", "rule"]
    # The agent asks once and then is quiet: no prompt is repeated, and the
    # terminal step asks for nothing.
    assert len(set(prompts[:-1])) == len(prompts[:-1])
    assert state["awaiting"] == "nothing"
    assert state["rule"]["text"]
    assert state["rule"]["citation"]


def test_the_explain_prompt_asks_about_the_concept_not_the_choice(client):
    """"Explain what this question is testing", never "why did you pick B"."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)
    explaining = _turn(client, session_id, confidence="high", spoke=True).json()

    assert explaining["step"] == coach.Step.EXPLAIN
    assert "what this question is actually testing" in explaining["prompt"]
    assert "why you picked" in explaining["prompt"]  # named, to rule it out


def test_the_rule_is_the_sources_own_words_and_not_a_composition(client):
    """Step 6 quotes the page the gate re-verified against, with its citation.

    The span itself is often the answer phrase alone — a good citation and a
    poor rule — so the rule is widened to the sentence around it. Widened by
    slicing the page, never by writing one: the assertion is that the rule's
    text is a literal substring of what the corpus holds.
    """
    state = _start(client)
    session_id = state["session_id"]
    for fields in ({"choice": 0}, {"confidence": "low"}, {}, {}):
        state = _turn(client, session_id, spoke=True, **fields).json()

    rule = state["rule"]
    assert rule["source_id"]
    assert ANSWER in rule["text"]
    assert state["reveal"]["quote"] in rule["text"]
    assert len(rule["text"]) > len(state["reveal"]["quote"])
    assert rule["citation"]


def test_the_rule_widens_a_span_by_slicing_the_page_not_by_writing_prose():
    page_text = (
        "Glycolysis is the first pathway used in the breakdown of glucose. "
        "If oxygen is present, pyruvate enters the mitochondrion, where the "
        "citric acid cycle oxidizes it completely. The pathway is regulated."
    )
    start = page_text.index("citric acid cycle")
    end = start + len("citric acid cycle")

    widened = coach.widen_to_sentence(page_text, start, end)

    assert widened.startswith("If oxygen is present")
    assert widened.endswith("completely.")
    assert widened in page_text


def test_a_glossary_term_widens_far_enough_to_reach_its_definition():
    """The case that was found by running it, not by reading the code.

    A key-terms page is *term*, blank line, *definition*, and the span lands on
    the term — so stopping at the first boundary handed back the term again and
    the rule stated nothing.
    """
    page_text = (
        "redox reaction\n\nchemical reaction that couples an oxidation and a "
        "reduction\n\nsubstrate-level phosphorylation\n\nproduction of ATP from "
        "ADP using the excess energy from a chemical reaction and a phosphate "
        "group from a reactant\n\nTCA cycle\n\nalternate name for the citric "
        "acid cycle"
    )
    start = page_text.index("substrate-level phosphorylation")
    end = start + len("substrate-level phosphorylation")

    widened = coach.widen_to_sentence(page_text, start, end)

    assert widened.startswith("substrate-level phosphorylation")
    assert widened.endswith("a phosphate group from a reactant")
    assert "TCA cycle" not in widened


def test_a_span_that_does_not_fit_its_page_yields_no_rule_sentence():
    """No invented sentence when the offsets disagree with the text."""
    assert coach.widen_to_sentence("short", 0, 900) == ""
    assert coach.widen_to_sentence("", 0, 3) == ""


def test_a_finished_session_refuses_further_turns(client):
    """The agent asks once. There is no state that re-prompts a quiet student."""
    state = _start(client)
    session_id = state["session_id"]
    for fields in ({"choice": 0}, {"confidence": "low"}, {}, {}):
        _turn(client, session_id, spoke=True, **fields)

    assert _turn(client, session_id, spoke=True).status_code == 409


# --- the contrast pair ----------------------------------------------------


def test_the_contrast_pair_changes_exactly_one_detail_of_the_stem():
    """"Exactly one" reconstructed from the pair, not taken on trust.

    `at` and `changed_from` locate the change, so the original stem can be
    rebuilt from the contrast stem. If any second character had moved, this
    round trip would fail.
    """
    stem = "In prokaryotic cells, which compartment houses the Krebs cycle?"
    pair = coach.contrast_pair(stem, "the cytoplasm", ("the nucleoid",))

    assert pair.kind == coach.STEM_DETAIL
    assert pair.changed_from == "prokaryotic"
    assert pair.changed_to == "eukaryotic"
    rebuilt = (
        pair.stem[: pair.at]
        + pair.changed_from
        + pair.stem[pair.at + len(pair.changed_to) :]
    )
    assert rebuilt == stem
    assert pair.stem != stem


def test_the_contrast_pair_preserves_capitalisation_of_the_detail_it_changes():
    stem = "Increases in substrate concentration do what to the rate?"
    pair = coach.contrast_pair(stem, "raise it", ("lower it", "nothing"))

    assert pair.changed_from == "Increases"
    assert pair.changed_to == "Decreases"
    assert pair.stem.startswith("Decreases")


def test_a_stem_with_no_swappable_detail_still_gets_a_pair():
    """The contrast pair is not optional, so the fallback is labelled, not absent."""
    stem = "Which structure filters blood in the kidney?"
    pair = coach.contrast_pair(stem, "nephron", ("ureter", "hilum"))

    assert pair.kind == coach.ANSWER_SWAP
    assert pair.stem == stem
    assert pair.changed_from == "nephron"
    assert pair.changed_to == "ureter"
    assert "one detail changed" in pair.prompt


def test_the_word_boundary_stops_a_swap_inside_a_longer_word():
    """`without` is not `with`; a swap that fired there would change two things."""
    stem = "A reaction proceeding without oxygen is described as what?"
    pair = coach.contrast_pair(stem, "anaerobic", ("aerobic", "isothermal"))

    assert pair.kind == coach.STEM_DETAIL
    assert pair.changed_from == "without"
    assert pair.changed_to == "with"


def test_the_contrast_pair_is_served_after_the_reveal(client):
    """Step 4 names the answer, which is legal only because step 2 already ran."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)
    explaining = _turn(client, session_id, confidence="high", spoke=True).json()
    assert explaining["contrast"] is None

    contrasting = _turn(client, session_id, spoke=True).json()
    assert contrasting["step"] == coach.Step.CONTRAST
    assert contrasting["contrast"]["changed_from"]
    assert contrasting["prompt"] == contrasting["contrast"]["prompt"]


# --- speak-rate -----------------------------------------------------------


def test_speak_rate_abstains_before_any_prompt(client):
    tally = client.get("/coach/speak-rate").json()

    assert tally["prompts"] == 0
    assert tally["speak_rate"] is None


def test_speak_rate_counts_the_prompts_the_student_spoke_into(client):
    """The pre-registered measure: a share, with its denominator on the record."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)
    _turn(client, session_id, confidence="high", spoke=True)
    _turn(client, session_id, spoke=False)  # asked to explain, said nothing
    _turn(client, session_id, spoke=True)

    tally = client.get("/coach/speak-rate").json()

    assert tally["prompts"] == 4
    assert tally["spoken"] == 3
    assert tally["speak_rate"] == 0.75
    assert tally["by_step"]["explain"] == {"prompts": 1, "spoken": 0}
    assert tally["sessions"] == 1


def test_a_refused_turn_is_not_counted_as_a_prompt(client):
    """A denominator that grows on rejected requests is not a speak-rate."""
    state = _start(client)
    session_id = state["session_id"]
    _turn(client, session_id, choice=0, spoke=True)
    _turn(client, session_id, confidence="not a level", spoke=True)

    assert client.get("/coach/speak-rate").json()["prompts"] == 1


def test_the_speak_log_is_written_where_the_yield_ledger_is(client, tmp_path):
    state = _start(client)
    _turn(client, state["session_id"], choice=0, spoke=True)

    lines = (tmp_path / "utterances.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["step"] for line in lines] == ["answer"]


# --- transcription --------------------------------------------------------


def test_transcription_degrades_to_recorded_but_not_transcribed(client):
    """No key, no transcript, and the loop is unaffected. Never a text box."""
    app_response = client.post(
        "/coach/transcribe",
        json={"audio_base64": "AAECAwQF", "mime": "audio/webm"},
    )

    body = app_response.json()
    assert app_response.status_code == 200
    assert body["transcribed"] is False
    assert body["transcript"] is None
    assert body["reason"]


def test_malformed_audio_returns_a_reason_rather_than_a_traceback(client):
    body = client.post("/coach/transcribe", json={"audio_base64": "not base64!"}).json()

    assert body["transcribed"] is False
    assert "base64" in body["reason"]


def test_the_upload_is_named_after_the_container_it_actually_holds():
    """Found by running it: the provider reads the extension, not the bytes.

    The first end-to-end transcription posted WAV bytes under the recorder's
    default `.webm` name and was refused as a corrupt file.
    """
    assert coach_voice.filename_for("audio/wav") == "utterance.wav"
    assert coach_voice.filename_for("audio/webm;codecs=opus") == "utterance.webm"
    assert coach_voice.filename_for("") == "utterance.webm"
    assert coach_voice.filename_for("application/octet-stream") == "utterance.webm"


def test_an_empty_recording_is_reported_as_such():
    audio, problem = coach_voice.decode("")

    assert audio == b""
    assert problem == "no audio was recorded"


def test_an_oversized_recording_is_refused_before_it_reaches_a_provider():
    import base64

    encoded = base64.b64encode(b"\x00" * (coach_voice.MAX_AUDIO_BYTES + 1)).decode()

    audio, problem = coach_voice.decode(encoded)

    assert audio == b""
    assert "exceeded" in problem


# --- sessions -------------------------------------------------------------


def test_an_unknown_session_is_a_404_and_not_a_new_session(client):
    """A typo must not silently open a fresh loop over a different item."""
    response = _turn(client, "deadbeefcafe", choice=0)

    assert response.status_code == 404


def test_the_registry_evicts_rather_than_growing_without_bound(supporting_corpus):
    registry = coach.Sessions(limit=2)
    shipped = {
        "item": {
            "stem": "Which pathway oxidizes pyruvate?",
            "answer": "citric acid cycle",
            "distractors": ["a", "b", "c"],
        },
        "span": {"quote": "citric acid cycle"},
        "citation": "x[0:1]",
        "source_id": "x",
        "attempt_id": "a",
    }
    first = registry.put(coach.start(shipped, topic_id=TOPIC, session_id="one"))
    registry.put(coach.start(shipped, topic_id=TOPIC, session_id="two"))
    registry.put(coach.start(shipped, topic_id=TOPIC, session_id="three"))

    assert len(registry) == 2
    assert registry.get(first.session_id) is None
    assert registry.get("three") is not None

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The coach's HTML and the browser half of the loop.

**There is no text input on this page, and that is the feature.** Not a styling
preference, not a phase-one simplification: a text box on a screen with a live
question is the mechanism by which an answer gets copied in from somewhere else,
and every measurement downstream of that is a measurement of a clipboard. The
whole page is buttons and a microphone. ``tests/test_no_text_input.py`` greps
this file — and every other file the add-on ships — and fails if an ``input``
element, a ``textarea``, or the attribute that makes an ordinary element
editable, appears anywhere in it. That test is the falsifier for the claim, and
it is meant to be run by somebody who does not believe it. (It is also why this
paragraph does not spell that attribute out: the check has no exemption list,
including for prose about the check.)

The page holds no rules of its own. It cannot decide when the answer is shown,
because it never has the answer: the service withholds it until a confidence for
that item is on the record, so a bug in this file — or a student with the
developer console open — cannot produce a reveal that has not been earned. What
arrives is what is displayed.

Text from the service is written with ``textContent``, never as markup. The
stems come from a language model, and a model's output interpolated into HTML is
a script injection with extra steps.

This module imports nothing from ``aqt``, so the template can be read and
asserted on without a Qt event loop — which is what makes the grep test cheap
enough to keep.
"""

from __future__ import annotations

#: What the student is told about the microphone before anything is recorded.
VOICE_NOTICE = (
    "Voice only. There is no text box on this screen — you cannot paste an "
    "answer, and that is the point."
)

#: Shown when the browser has no microphone, or permission was refused. The
#: loop still runs; the prompts that would have been spoken are recorded as not
#: spoken, which is exactly what speak-rate is for.
NO_MIC_NOTICE = (
    "No microphone is available, so nothing can be recorded. The loop still "
    "runs and these prompts count as not spoken."
)

STYLE = """
<style>
.coach { max-width: 46rem; margin: 0 auto; padding: 1rem 1.25rem 3rem; text-align: left; }
.coach h1 { font-size: 1.35rem; margin: 0 0 .2rem; }
.coach .lede { opacity: .75; margin: 0 0 1rem; font-size: .82rem; line-height: 1.5; }
.coach .panel {
    border: 1px solid var(--border, #ccc);
    border-radius: var(--border-radius, 6px);
    padding: .9rem 1.1rem; margin-bottom: 1rem;
}
.coach .steps { display: flex; gap: .35rem; flex-wrap: wrap; margin: 0 0 1rem; font-size: .72rem; }
.coach .steps span {
    border: 1px solid var(--border-subtle, #e0e0e0); border-radius: 999px;
    padding: .15rem .6rem; opacity: .45;
}
.coach .steps span.at { opacity: 1; font-weight: 600; border-color: currentColor; }
.coach .steps span.scored::after { content: " · scored"; opacity: .8; }
.coach .stem { font-size: 1.05rem; line-height: 1.5; margin: 0 0 .9rem; }
.coach .prompt { font-size: .95rem; line-height: 1.5; margin: 0 0 .8rem; }
.coach .choices { display: grid; gap: .4rem; }
.coach button {
    font: inherit; text-align: left; padding: .55rem .75rem; cursor: pointer;
    border: 1px solid var(--border, #ccc); border-radius: var(--border-radius, 6px);
    background: transparent; color: inherit;
}
.coach button:disabled { opacity: .4; cursor: default; }
.coach button.picked { border-color: currentColor; font-weight: 600; }
.coach .row { display: flex; gap: .4rem; flex-wrap: wrap; align-items: center; margin-top: .6rem; }
.coach .mic.on { border-color: #c0392b; color: #c0392b; font-weight: 600; }
.coach .note { font-size: .78rem; opacity: .7; line-height: 1.5; margin: .5rem 0 0; }
.coach .verdict { font-weight: 600; margin: 0 0 .4rem; }
.coach .quote { font-style: italic; line-height: 1.5; margin: 0 0 .4rem; }
.coach .cite { font-size: .72rem; opacity: .6; word-break: break-all; }
.coach .hidden { display: none; }
.coach .bar { font-size: .75rem; opacity: .7; margin-top: 1rem; }
</style>
"""

#: Rendered once. Every later change is a `SpeedrunCoach.render(state)` call
#: from Python with the service's own JSON, so there is one shape of truth and
#: the page never guesses at the next step.
BODY = """
<div class="coach">
  <h1>Speedrun Coach</h1>
  <p class="lede">__VOICE_NOTICE__</p>

  <div class="steps">
    <span data-step="answer" class="scored">1 · cold question</span>
    <span data-step="confidence">2 · confidence</span>
    <span data-step="explain">3 · explain aloud</span>
    <span data-step="contrast">4 · contrast pair</span>
    <span data-step="rule">the rule</span>
  </div>

  <div class="panel" id="coach-status">
    <p class="prompt" id="coach-status-text">Starting the coach…</p>
  </div>

  <div class="panel hidden" id="coach-question">
    <p class="stem" id="coach-stem"></p>
    <div class="choices" id="coach-choices"></div>
  </div>

  <div class="panel hidden" id="coach-reveal">
    <p class="verdict" id="coach-verdict"></p>
    <p class="note" id="coach-calibration"></p>
  </div>

  <div class="panel hidden" id="coach-contrast">
    <p class="note">Contrast pair — the same question, exactly one detail changed.</p>
    <p class="stem" id="coach-contrast-stem"></p>
    <p class="note" id="coach-contrast-change"></p>
  </div>

  <div class="panel hidden" id="coach-rule">
    <p class="note" id="coach-rule-lead"></p>
    <p class="quote" id="coach-rule-text"></p>
    <p class="cite" id="coach-rule-cite"></p>
  </div>

  <div class="panel" id="coach-talk">
    <p class="prompt" id="coach-prompt"></p>
    <div class="row">
      <button type="button" class="mic" id="coach-mic">Start speaking</button>
      <span class="note" id="coach-mic-note"></span>
    </div>
    <div class="row" id="coach-confidence-row"></div>
    <div class="row">
      <button type="button" id="coach-next" class="hidden">Done — next</button>
      <button type="button" id="coach-again" class="hidden">Another question</button>
    </div>
    <p class="note" id="coach-transcript"></p>
  </div>

  <p class="bar" id="coach-speakrate"></p>
</div>
"""

#: The browser half. It records, it renders, and it decides nothing.
SCRIPT = """
<script>
var SpeedrunCoach = (function () {
    var recorder = null;
    var chunks = [];
    var pending = null;        // base64 of the last recording, sent with the turn
    var pendingMs = 0;
    var started = 0;
    var picked = null;
    var state = null;
    var micUsable = true;
    var MAX_MS = 25000;        // a spoken answer, not a monologue

    function el(id) { return document.getElementById(id); }
    function show(id, on) { el(id).classList.toggle('hidden', !on); }
    function say(id, text) { el(id).textContent = text || ''; }

    function send(fields) {
        fields.spoke = pending !== null;
        fields.audio_base64 = pending || '';
        fields.audio_ms = pendingMs;
        pending = null;
        pendingMs = 0;
        picked = null;
        say('coach-mic-note', '');
        say('coach-transcript', '');
        pycmd('coach:turn:' + JSON.stringify(fields));
    }

    // --- recording --------------------------------------------------------

    function stopRecording() {
        if (recorder && recorder.state === 'recording') { recorder.stop(); }
    }

    function toggleMic() {
        if (recorder && recorder.state === 'recording') { stopRecording(); return; }
        if (!micUsable || !navigator.mediaDevices) { return; }
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
            chunks = [];
            recorder = new MediaRecorder(stream);
            recorder.ondataavailable = function (e) {
                if (e.data && e.data.size) { chunks.push(e.data); }
            };
            recorder.onstop = function () {
                var elapsed = Date.now() - started;
                stream.getTracks().forEach(function (t) { t.stop(); });
                el('coach-mic').classList.remove('on');
                el('coach-mic').textContent = 'Record again';
                var blob = new Blob(chunks, { type: 'audio/webm' });
                var reader = new FileReader();
                reader.onloadend = function () {
                    pending = String(reader.result).split(',')[1] || '';
                    pendingMs = elapsed;
                    say('coach-mic-note',
                        'Recorded ' + (elapsed / 1000).toFixed(1) + 's.');
                    pycmd('coach:transcribe:' + pending);
                };
                reader.readAsDataURL(blob);
            };
            started = Date.now();
            recorder.start();
            el('coach-mic').classList.add('on');
            el('coach-mic').textContent = 'Stop';
            setTimeout(stopRecording, MAX_MS);
        }).catch(function (err) {
            micUsable = false;
            say('coach-mic-note', '__NO_MIC_NOTICE__ (' + err.name + ')');
            el('coach-mic').disabled = true;
        });
    }

    // --- rendering --------------------------------------------------------

    function drawChoices(choices, live) {
        var host = el('coach-choices');
        host.textContent = '';
        choices.forEach(function (choice, index) {
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = String.fromCharCode(65 + index) + '.  ' + choice;
            button.disabled = !live;
            if (picked === index) { button.classList.add('picked'); }
            button.addEventListener('click', function () {
                picked = index;
                drawChoices(choices, false);
                send({ choice: index });
            });
            host.appendChild(button);
        });
    }

    function drawConfidence(live) {
        var host = el('coach-confidence-row');
        host.textContent = '';
        if (!live) { return; }
        ['low', 'medium', 'high'].forEach(function (level) {
            var button = document.createElement('button');
            button.type = 'button';
            button.textContent = level;
            button.addEventListener('click', function () {
                host.textContent = '';
                send({ confidence: level });
            });
            host.appendChild(button);
        });
    }

    function drawSteps(step) {
        var at = step === 'rule' ? 'rule' : step;
        document.querySelectorAll('.steps span').forEach(function (node) {
            node.classList.toggle('at', node.getAttribute('data-step') === at);
        });
    }

    function render(next) {
        state = next;
        show('coach-status', false);
        show('coach-question', true);
        drawSteps(state.step);
        say('coach-stem', state.question.stem);
        say('coach-prompt', state.prompt);
        drawChoices(state.question.choices, state.awaiting === 'choice');
        drawConfidence(state.awaiting === 'confidence');

        el('coach-mic').disabled = !micUsable || !state.speak;
        show('coach-next', state.awaiting === 'spoken');
        show('coach-again', state.awaiting === 'nothing');

        var reveal = state.reveal;
        show('coach-reveal', !!reveal);
        if (reveal) {
            say('coach-verdict', reveal.correct
                ? 'Correct — ' + reveal.correct_answer
                : 'Not correct. The answer is ' + reveal.correct_answer + '.');
            say('coach-calibration',
                'You said ' + reveal.confidence + ' confidence before seeing this.');
        }

        var contrast = state.contrast;
        show('coach-contrast', !!contrast);
        if (contrast) {
            say('coach-contrast-stem', contrast.stem);
            say('coach-contrast-change',
                contrast.kind === 'stem_detail'
                    ? 'Changed: ' + contrast.changed_from + ' → ' + contrast.changed_to
                    : 'Changed: the correct answer is ' + contrast.changed_to
                      + ' instead of ' + contrast.changed_from);
        }

        var rule = state.rule;
        show('coach-rule', !!rule);
        if (rule) {
            say('coach-rule-lead', rule.lead);
            say('coach-rule-text', rule.text);
            say('coach-rule-cite', rule.citation);
        }
    }

    function status(text) {
        show('coach-status', true);
        show('coach-question', false);
        show('coach-reveal', false);
        show('coach-contrast', false);
        show('coach-rule', false);
        el('coach-mic').disabled = true;
        show('coach-next', false);
        show('coach-again', true);
        say('coach-prompt', '');
        say('coach-status-text', text);
    }

    function transcript(text) { say('coach-transcript', text || ''); }
    function speakRate(text) { say('coach-speakrate', text || ''); }

    document.addEventListener('DOMContentLoaded', function () {
        el('coach-mic').addEventListener('click', toggleMic);
        el('coach-next').addEventListener('click', function () { send({}); });
        el('coach-again').addEventListener('click', function () {
            status('Asking a new question…');
            pycmd('coach:restart');
        });
        pycmd('coach:ready');
    });

    return { render: render, status: status, transcript: transcript,
             speakRate: speakRate };
})();
</script>
"""


def page() -> str:
    """The whole coach surface, ready for ``AnkiWebView.stdHtml``.

    One string rather than a template engine: the page has no server-rendered
    data in it at all. Every value a student sees arrives later through
    ``render(state)`` and is written as text, so there is no interpolation point
    here for a model's output to reach the DOM as markup.
    """
    return STYLE + BODY.replace("__VOICE_NOTICE__", VOICE_NOTICE) + SCRIPT.replace(
        "__NO_MIC_NOTICE__", NO_MIC_NOTICE
    )

# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""What proposes items, and why the stub is shaped the way it is.

The generator is the replaceable part. The graph, the gate and the rejection
ledger do not change when a model is plugged in behind them, and that is the
whole design: the gate is what makes generation safe, so the gate is what got
built first and what gets tested.

**`RememberedAnswerGenerator` reproduces the failure mode the gate exists for.**
It would be easy — and useless — to write a stub that lifts a phrase straight
out of the retrieved chunk. That stub passes the gate every time, proves
nothing, and quietly turns the pipeline into a copier. A language model does not
work that way: it answers from what it absorbed in training, and the retrieved
passage is context it may or may not lean on. The gap between "what the model
believes" and "what the source says" is the entire reason for the gate, so the
stub reproduces that gap exactly — it answers from a fixed table and never reads
the retrieved text. Whether a given claim ships is then decided by the corpus
and the gate, not by the author of the table.

The claims below are hand-written stand-ins for model output, not vetted MCAT
content, and one of them is deliberately false. The gate does not check whether
a claim is true; it checks whether a real source says it. A false claim is
dropped because nothing supports it, which is the behaviour being demonstrated.

**The real generators are handed the retrieved text; the stub is not.** That is
not an inconsistency, it is the division of labour. Giving a model the sources
is the honest way to do grounded generation and it raises Yield a great deal —
but it does not make the gate ornamental, because the gate re-derives the
citation from the retrieved characters rather than taking the model's word that
it copied them. A model that drifts one word past what it was shown is caught by
exactly the same check as a model that had no source at all. The stub keeps the
no-source behaviour precisely so the suite can still prove the gate fires.

Two real paths, `OpenAIGenerator` and `AnthropicGenerator`, chosen by whichever
key exists; with neither, the stub runs and the service still works. Both are
prompted to answer with a phrase copied verbatim from the retrieved text, and
nothing downstream trusts that they obeyed.

Every proposal records the **resolved** model id — `gpt-5-2025-08-07`, not
`gpt-5` — because "we used GPT-5" is not a fact anyone can re-run.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Protocol

from .corpus_gateway import RetrievedChunk
from .environment import has_key, key

#: Aliases, deliberately. The alias is what a caller asks for; the snapshot the
#: provider resolves it to is what gets recorded on every item it produces.
OPENAI_MODEL = "gpt-5"
ANTHROPIC_MODEL = "claude-opus-5"


@dataclasses.dataclass(frozen=True)
class Candidate:
    """A proposed held-out item, before anything has been checked.

    Deliberately not called an item. It becomes an item only if the gate finds
    the supporting text for `answer`; until then it is a claim.
    """

    stem: str
    answer: str
    distractors: tuple[str, ...]
    topic_id: str
    generator: str
    #: The provider's *resolved* model id, as reported by the response. Empty
    #: for the stub, which is not a model. Carried on the candidate rather than
    #: read off the generator afterwards, so the id travels with the item it
    #: actually produced — into the trace, the ledger and the response.
    model: str = ""

    @property
    def well_formed(self) -> bool:
        return bool(
            self.stem.strip() and self.answer.strip() and len(self.distractors) >= 2
        )

    @property
    def answer_leaks_into_stem(self) -> bool:
        """Does the stem hand the student the answer?

        Not Leakage in CONTEXT.md's sense — nothing has reached a student — but
        an item that contains its own answer measures nothing, so it is dropped
        with its own reason rather than counted against the gate.
        """
        return self.answer.strip().casefold() in self.stem.casefold()

    def as_dict(self) -> dict[str, Any]:
        record = dataclasses.asdict(self)
        record["distractors"] = list(self.distractors)
        return record


class Generator(Protocol):
    name: str

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None: ...


# --- the stub -------------------------------------------------------------

#: Three claims per Bio/Biochem topic, matching ADR-0006's three generation
#: requests per content category. Written from memory the way a model answers
#: from memory: some of these are stated in OpenStax *Biology* in words the gate
#: can match, some are stated in different words, and one is simply wrong. Which
#: is which is not annotated here — that is the gate's answer to give, and
#: annotating it would let a reader take the table's word for it.
_REMEMBERED: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "1A": (
        (
            "An inhibitor binds the enzyme's active site and its effect is "
            "overcome by adding more substrate. What is this called?",
            "competitive inhibition",
            ("allosteric activation", "feedback inhibition", "denaturation"),
        ),
        (
            "Where on an enzyme does the substrate bind?",
            "active site",
            ("allosteric site", "signal peptide", "disulfide bridge"),
        ),
        (
            "Which bond links one amino acid to the next in a polypeptide?",
            "phosphodiester linkage",
            ("peptide bond", "glycosidic bond", "hydrogen bond"),
        ),
    ),
    "1B": (
        (
            "Which molecule carries the coding sequence from the nucleus to "
            "the ribosome?",
            "messenger RNA",
            ("transfer RNA", "ribosomal RNA", "small nuclear RNA"),
        ),
        (
            "What is the process of copying a DNA sequence into RNA called?",
            "transcription",
            ("translation", "replication", "reverse transcription"),
        ),
        (
            "How many nucleotides specify one amino acid in the genetic code?",
            "three",
            ("two", "four", "six"),
        ),
    ),
    "1C": (
        (
            "The two identical copies of a replicated chromosome, joined at "
            "the centromere, are known as what?",
            "sister chromatids",
            ("homologous pairs", "bivalents", "chiasmata"),
        ),
        (
            "What is the exchange of segments between homologous chromosomes "
            "during meiosis called?",
            "crossover",
            ("nondisjunction", "translocation", "conjugation"),
        ),
        (
            "DNA replication in which each daughter molecule keeps one parent "
            "strand is described as what?",
            "hemimethylated replication",
            ("conservative", "dispersive", "rolling circle"),
        ),
    ),
    "1D": (
        (
            "Which cycle oxidizes acetyl CoA in the mitochondrial matrix?",
            "citric acid cycle",
            ("Calvin cycle", "urea cycle", "cell cycle"),
        ),
        (
            "What three-carbon molecule does glycolysis produce from glucose?",
            "pyruvate",
            ("lactate", "acetyl CoA", "oxaloacetate"),
        ),
        (
            "In prokaryotic cells, which organelle houses the Krebs cycle?",
            "the peroxisome of prokaryotic cells",
            ("the mitochondrion", "the cytoplasm", "the nucleoid"),
        ),
    ),
    "2A": (
        (
            "Which structure separates a cell's interior from its surroundings?",
            "the plasma membrane",
            ("the cell wall", "the nuclear envelope", "the cytoskeleton"),
        ),
        (
            "Which model describes membrane proteins moving within a lipid "
            "bilayer?",
            "fluid mosaic",
            ("lock and key", "induced fit", "sliding filament"),
        ),
        (
            "Which junction seals neighbouring epithelial cells so solutes "
            "cannot pass between them?",
            "tight junction",
            ("gap junction", "desmosome", "plasmodesma"),
        ),
    ),
    "2B": (
        (
            "What polymer gives the bacterial cell wall its rigidity?",
            "peptidoglycan",
            ("chitin", "cellulose", "keratin"),
        ),
        (
            "By what process do bacteria transfer plasmid DNA through a pilus?",
            "conjugation",
            ("transduction", "transformation", "transposition"),
        ),
        (
            "Which viral cycle destroys the host cell on release?",
            "lytic cycle",
            ("lysogenic cycle", "latent phase", "budding"),
        ),
    ),
    "2C": (
        (
            "During which phase of mitosis do sister chromatids separate?",
            "anaphase",
            ("prophase", "metaphase", "telophase"),
        ),
        (
            "What is the division of the cytoplasm at the end of mitosis "
            "called?",
            "cytokinesis",
            ("karyokinesis", "interphase", "cleavage furrowing"),
        ),
        (
            "A cell that can give rise to any cell type in the body is "
            "described as what?",
            "totipotent",
            ("pluripotent", "multipotent", "unipotent"),
        ),
    ),
    "3A": (
        (
            "What insulating layer speeds conduction along a vertebrate axon?",
            "myelin sheath",
            ("node of Ranvier", "synaptic cleft", "axon hillock"),
        ),
        (
            "Which gland releases hormones that regulate other endocrine "
            "glands?",
            "pituitary gland",
            ("thyroid gland", "adrenal medulla", "pineal gland"),
        ),
        (
            "What is the gap between two communicating neurons called?",
            "synapse",
            ("dendrite", "soma", "ganglion"),
        ),
    ),
    "3B": (
        (
            "Which organ is the principal site of nutrient absorption?",
            "the small intestine",
            ("the stomach", "the large intestine", "the oesophagus"),
        ),
        (
            "Where does gas exchange occur in the human lung?",
            "alveoli",
            ("bronchi", "trachea", "pleura"),
        ),
        (
            "Which structure filters blood in the kidney?",
            "nephron",
            ("ureter", "hilum", "medulla"),
        ),
    ),
}


class RememberedAnswerGenerator:
    """Answers from a fixed table, never from the retrieved text.

    Standing in for a model means standing in for its failure mode too: the
    proposal is made without consulting retrieval, so grounding is decided
    downstream. Swap a real model in and the graph does not change.
    """

    name = "stub-remembered"
    #: Not a model. An empty id is the honest report, not "unknown".
    model = ""

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        claims = _REMEMBERED.get(topic_id)
        if not claims:
            return None
        stem, answer, distractors = claims[seed % len(claims)]
        return Candidate(
            stem=stem,
            answer=answer,
            distractors=distractors,
            topic_id=topic_id,
            generator=self.name,
        )


class FixedClaimGenerator:
    """Proposes one caller-supplied claim. The ungated control's adversary.

    ADR-0006's fourth arm needs a way to put a specific ungrounded claim through
    the pipeline on demand, and the boundary tests need the same thing. Keeping
    it in the shipped package rather than in a test file means the arm that
    carries the project's actual claim runs the same code path as the arm that
    does not.
    """

    name = "fixed-claim"
    model = ""

    def __init__(self, candidate: Candidate | None) -> None:
        self._candidate = candidate

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        if self._candidate is None:
            return None
        return dataclasses.replace(self._candidate, topic_id=topic_id)


# --- the real ones --------------------------------------------------------

#: One prompt, both providers. Keeping it identical is what makes a Yield
#: comparison between them mean anything; a per-provider prompt would turn a
#: retrieval finding into a prompt-engineering finding.
PROMPT = """\
You are drafting one exam-style multiple-choice item for MCAT content category \
{topic_id}, using only the passages below.

The correct answer MUST be a phrase copied verbatim - character for character - \
from one of the passages. Do not paraphrase it, do not correct its spelling, and \
do not summarise it. If no passage supports a question worth asking, set "skip" \
to true.

The stem must not contain the correct answer. Give three plausible distractors.

Passages:
{passages}
"""

#: Both SDKs take the same JSON Schema. `skip` is required rather than optional
#: because a model that cannot ground an answer should be able to say so, and a
#: schema that lets it omit the field invites it to invent one instead.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stem": {"type": "string"},
        "answer": {"type": "string"},
        "distractors": {"type": "array", "items": {"type": "string"}},
        "skip": {"type": "boolean"},
    },
    "required": ["stem", "answer", "distractors", "skip"],
    "additionalProperties": False,
}


def passages_for(retrieved: list[RetrievedChunk], limit: int) -> str:
    """The retrieved text, labelled by chunk, exactly as retrieval returned it.

    Handing the model the sources is the honest way to do grounded generation.
    It is also why the gate matters more here rather than less: with the text in
    front of it a model will usually copy correctly, so the residual failures
    are the interesting ones — the places it drifted a word past what it was
    shown, which is precisely what a span match catches and a plausibility
    judgement does not.
    """
    return "\n\n".join(f"[{chunk.chunk_id}] {chunk.text}" for chunk in retrieved[:limit])


def _candidate_from(
    drafted: dict[str, Any], *, topic_id: str, generator: str, model: str
) -> Candidate | None:
    if drafted.get("skip"):
        return None
    return Candidate(
        stem=drafted.get("stem", ""),
        answer=drafted.get("answer", ""),
        distractors=tuple(drafted.get("distractors", ())),
        topic_id=topic_id,
        generator=generator,
        model=model,
    )


class OpenAIGenerator:
    """Drafts items with GPT-5. Never asked whether its own item is correct.

    Uses the Responses API with a strict JSON schema, and records the model id
    the API *resolved* — `gpt-5` is an alias that moves, `gpt-5-2025-08-07` is a
    fact. Reasoning effort is left at the provider default on purpose: every
    knob turned here is a knob that has to be reported alongside the Yield
    number, and an unturned one cannot be accused of having been adjusted until
    the number looked good.

    The key is read from the environment (see `environment.py`) and handed
    straight to the SDK. It is not stored on this object, and nothing this class
    returns can contain it.
    """

    name = "openai"

    def __init__(
        self,
        model: str = OPENAI_MODEL,
        max_chunks: int = 4,
        max_output_tokens: int = 4000,
    ) -> None:
        from openai import OpenAI  # noqa: PLC0415  (extra; absent without a key)

        self._client = OpenAI(api_key=key("OPENAI_API_KEY"))
        #: Public: `/health` reports it, and it is the alias, not the snapshot.
        self.model = model
        self._max_chunks = max_chunks
        self._max_output_tokens = max_output_tokens

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        if not retrieved:
            return None
        response = self._client.responses.create(
            model=self.model,
            max_output_tokens=self._max_output_tokens,
            input=PROMPT.format(
                topic_id=topic_id,
                passages=passages_for(retrieved, self._max_chunks),
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "held_out_item",
                    "schema": SCHEMA,
                    "strict": True,
                }
            },
        )
        # An incomplete response is a truncated one, and a truncated item is not
        # a worse item — it is not an item. Returning None counts it as
        # `generator_empty`, which is a different finding from a gate rejection.
        if response.status != "completed" or not response.output_text:
            return None
        return _candidate_from(
            json.loads(response.output_text),
            topic_id=topic_id,
            generator=self.name,
            model=response.model,
        )


class AnthropicGenerator:
    """Drafts items with Claude. Never asked whether its own item is correct.

    **Untested.** No `ANTHROPIC_API_KEY` was available, so this class has never
    issued a request. It is wired, not verified — unlike `OpenAIGenerator`,
    whose numbers are in the README because it was actually run.
    """

    name = "anthropic"

    def __init__(self, model: str = ANTHROPIC_MODEL, max_chunks: int = 4) -> None:
        import anthropic  # noqa: PLC0415  (extra; absent without a key)

        self._client = anthropic.Anthropic(api_key=key("ANTHROPIC_API_KEY"))
        #: Public: `/health` reports it, and it is the alias, not the snapshot.
        self.model = model
        self._max_chunks = max_chunks

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        if not retrieved:
            return None
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(
                        topic_id=topic_id,
                        passages=passages_for(retrieved, self._max_chunks),
                    ),
                }
            ],
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            return None
        return _candidate_from(
            json.loads(text),
            topic_id=topic_id,
            generator=self.name,
            model=response.model,
        )


#: Which key selects which generator, in order. OpenAI first because that is the
#: key this service has actually been measured with.
PROVIDERS: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "openai"),
    ("ANTHROPIC_API_KEY", "anthropic"),
)


def available_provider() -> str | None:
    """The provider a key exists for, by name only. Never returns a key."""
    for env_name, provider in PROVIDERS:
        if has_key(env_name):
            return provider
    return None


def default_generator() -> Generator:
    """A real model when a key exists, the stub when none does.

    Falling back rather than failing is deliberate and load-bearing: the gate is
    what this service is for, and it has to be demonstrable — and testable — on
    a machine with no key at all.
    """
    provider = available_provider()
    builders: dict[str, Any] = {
        "openai": OpenAIGenerator,
        "anthropic": AnthropicGenerator,
    }
    if provider in builders:
        try:
            return builders[provider]()
        except Exception:  # noqa: BLE001 - a missing extra is not a reason to be down
            pass
    return RememberedAnswerGenerator()

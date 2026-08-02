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

`AnthropicGenerator` is the real path and activates only when a key is present.
It is prompted to answer using a phrase copied verbatim from the retrieved text
— but nothing downstream trusts that it obeyed, because the gate checks the
characters either way.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Protocol

from .corpus_gateway import RetrievedChunk

MODEL = "claude-opus-5"


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

    def __init__(self, candidate: Candidate | None) -> None:
        self._candidate = candidate

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        if self._candidate is None:
            return None
        return dataclasses.replace(self._candidate, topic_id=topic_id)


# --- the real one ---------------------------------------------------------


def model_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


_PROMPT = """\
You are drafting one exam-style multiple-choice item for MCAT content category \
{topic_id}, using only the passages below.

The correct answer MUST be a phrase copied verbatim — character for character — \
from one of the passages. Do not paraphrase it, do not correct its spelling, and \
do not summarise it. If no passage supports a question worth asking, return \
{{"skip": true}}.

The stem must not contain the correct answer.

Passages:
{passages}

Return only JSON: {{"stem": "...", "answer": "...", "distractors": ["...", "...", "..."]}}\
"""


class AnthropicGenerator:
    """Drafts items with Claude. Never asked whether its own item is correct.

    The prompt asks for a verbatim phrase because that raises Yield, not because
    it is trusted: the gate re-checks the characters, and an answer the model
    paraphrased is dropped with a reason like any other. There is no step
    anywhere in this file, or downstream of it, that asks a model to grade
    model output.

    **Untested.** No `ANTHROPIC_API_KEY` was available while this was written,
    so this class has never issued a request. It is wired, not verified.
    """

    name = "anthropic"

    def __init__(self, model: str = MODEL, max_chunks: int = 4) -> None:
        import anthropic  # noqa: PLC0415  (optional extra; absent without a key)

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_chunks = max_chunks

    def propose(
        self, *, topic_id: str, retrieved: list[RetrievedChunk], seed: int
    ) -> Candidate | None:
        if not retrieved:
            return None
        passages = "\n\n".join(
            f"[{chunk.chunk_id}] {chunk.text}" for chunk in retrieved[: self._max_chunks]
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "stem": {"type": "string"},
                            "answer": {"type": "string"},
                            "distractors": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "skip": {"type": "boolean"},
                        },
                        "required": ["stem", "answer", "distractors", "skip"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[
                {
                    "role": "user",
                    "content": _PROMPT.format(topic_id=topic_id, passages=passages),
                }
            ],
        )
        if response.stop_reason == "refusal":
            return None
        import json  # noqa: PLC0415

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            return None
        drafted = json.loads(text)
        if drafted.get("skip"):
            return None
        return Candidate(
            stem=drafted.get("stem", ""),
            answer=drafted.get("answer", ""),
            distractors=tuple(drafted.get("distractors", ())),
            topic_id=topic_id,
            generator=self.name,
        )


def default_generator() -> Generator:
    """The real model when a key exists, the stub when it does not.

    Falling back rather than failing is deliberate: the gate is what this
    service is for, and it must be demonstrable on a machine with no key.
    """
    if model_key() is None:
        return RememberedAnswerGenerator()
    try:
        return AnthropicGenerator()
    except Exception:  # noqa: BLE001 - a missing extra is not a reason to be down
        return RememberedAnswerGenerator()

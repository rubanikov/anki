# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""How much of a card's wording a rewording reuses — the one check that decides
whether the paraphrase test is a paraphrase test at all.

If the reworded item repeats the card's distinctive phrasing, a student who
memorised the card recognises the string and answers without knowing the fact.
The three numbers then collapse for a reason that has nothing to do with the
Performance model, and the test's headline finding is an artifact of its own
item writing. So overlap is measured, with the rule stated before the items were
generated and applied to all 60 identically:

**A rewording is `clean` when both hold**

1. the **longest run of consecutive words** it shares with the card's prompt is
   **<= 3**, and
2. the **content-word Jaccard** against the card's prompt is **< 0.50**.

Both comparisons drop stopwords' effect where it would be noise, ignore case and
punctuation, and — importantly — **exclude the answer's own words**. Naming the
thing being asked about is unavoidable: a rewording of a card about the
arachidonic acid pathway has to say "arachidonic acid pathway". Counting that as
reuse would flag every correct rewording and flag nothing else.

Neither number is a verdict on its own. A shared run of three can be one
technical term ("citric acid cycle") or it can be the card's own clause; the
run's text is reported alongside its length so a reader can tell which, and
`QUALITY.md` records a hand read of all 60 on top of this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words whose reuse says nothing. Function words plus the small set of question
#: words every exam item contains — "which", "what" appearing in both a card and
#: its rewording is not evidence of copying.
STOPWORDS = frozenset(
    """
    a an the and or but if of in on at to for from by with without into onto as is
    are was were be been being do does did done has have had it its this that these
    those there here which what who whom whose when where why how not no nor so than
    then thus can could may might must shall should will would you your they them
    their he she his her we our us i me my one two both each any all more most other
    another such same own very also just about over under between during through
    """.split()
)

WORD = re.compile(r"[a-z0-9][a-z0-9'\-+]*")
#: Cloze blanks as `select_rset.py` renders them, plus the image marker. Removed
#: before comparison: `[...]` is not wording, and neither is `[image]`.
BLANK = re.compile(r"\[[^\]]*\]")


def tokens(text: str) -> list[str]:
    return WORD.findall(BLANK.sub(" ", text).casefold())


def content(text: str, *, drop: frozenset[str] = frozenset()) -> set[str]:
    return {t for t in tokens(text) if t not in STOPWORDS and t not in drop}


def longest_shared_run(left: list[str], right: list[str]) -> tuple[int, str]:
    """Longest run of consecutive words present in both, and the run itself.

    Plain dynamic programming over the two token lists. Stopwords are kept here
    on purpose: "is a type of integral protein that" is exactly the kind of
    lifted clause this is looking for, and dropping its function words would
    hide it.
    """
    if not left or not right:
        return 0, ""
    best_len = 0
    best_end = 0
    previous = [0] * (len(right) + 1)
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        for j in range(1, len(right) + 1):
            if left[i - 1] == right[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    return best_len, " ".join(left[best_end - best_len : best_end])


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


#: Fixed before the run. Changing either afterwards is moving a threshold to fit
#: a result, which is the habit this project's freeze exists to prevent.
MAX_SHARED_RUN = 3
MAX_JACCARD = 0.50


@dataclass(frozen=True)
class Overlap:
    shared_run: int
    shared_text: str
    jaccard: float

    @property
    def clean(self) -> bool:
        return self.shared_run <= MAX_SHARED_RUN and self.jaccard < MAX_JACCARD

    @property
    def why(self) -> str:
        reasons = []
        if self.shared_run > MAX_SHARED_RUN:
            reasons.append(f"shares {self.shared_run} consecutive words: '{self.shared_text}'")
        if self.jaccard >= MAX_JACCARD:
            reasons.append(f"content-word overlap {self.jaccard:.2f}")
        return "; ".join(reasons)

    def as_dict(self) -> dict[str, object]:
        return {
            "shared_run": self.shared_run,
            "shared_text": self.shared_text,
            "jaccard": round(self.jaccard, 3),
            "clean": self.clean,
        }


def overlap(card_prompt: str, rewording_prompt: str, answer: str) -> Overlap:
    """How much of the card the rewording reuses, answer terms excluded."""
    answer_words = frozenset(tokens(answer))
    card_tokens = [t for t in tokens(card_prompt) if t not in answer_words]
    reword_tokens = [t for t in tokens(rewording_prompt) if t not in answer_words]
    run, text = longest_shared_run(card_tokens, reword_tokens)
    return Overlap(
        shared_run=run,
        shared_text=text,
        jaccard=jaccard(
            content(card_prompt, drop=answer_words), content(rewording_prompt, drop=answer_words)
        ),
    )

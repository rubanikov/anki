# speedrun/eval

Everything that turns a claim into a number someone else can check. The tests
themselves are specified in [`../docs/TEST_PLAN.md`](../docs/TEST_PLAN.md); this
directory holds the scripts and the artifacts they produce.

## Start here: the freeze

[`holdout/MANIFEST.md`](holdout/MANIFEST.md) is the first thing written in this
project and the thing every later evidence claim leans on. It fixes, **in
advance of any result**, what is in each held-out set, how it was split, and what
counts as passing:

| set | what it is | state at freeze |
|---|---|---|
| **H1** | memory-calibration reviews held back from `anki-revlogs-10k` — most recent 20% by time, per collection | protocol fixed; data not downloaded (licence) |
| **H2** — the **P-set** | Held-out items, never derived from the student's cards | **empty on purpose**; ids and hashes appended as generated |
| **H3** | AI card gold set, 50 question/answer pairs from one real source | protocol and cutoff rule fixed; pairs not yet authored |
| **H4** — the **R-set** | 30 of the student's own cards × 2 Reworded cards | protocol fixed; needs a studied deck first |

Nothing in the manifest states a number that has been measured. Where a hash does
not exist yet it reads `PENDING`, and `--verify` fails if data appears while the
record still says `PENDING`.

```bash
python speedrun/eval/holdout/freeze.py --status        # what is frozen, open, pending
python speedrun/eval/holdout/freeze.py --freeze        # record hashes for data that now exists
python speedrun/eval/holdout/freeze.py --append-item --set H2   # append new item ids + hashes
python speedrun/eval/holdout/freeze.py --close-set H2  # fix the file-level hash; no more appends
python speedrun/eval/holdout/freeze.py --verify        # exits non-zero on any mismatch
```

`freeze.py` is stdlib-only and hashes itself, so the protocol cannot be edited
after the fact without `--verify` noticing.

## Rules that apply to everything in here

- **A placeholder must read as a placeholder.** No script and no artifact in this
  directory may print a number that has not been measured.
- **The licensed corpus never enters the public fork.** `anki-revlogs-10k` permits
  individual research use and forbids public redistribution. The `.gitignore`
  entries carry that reason; `freeze.py --verify` demonstrates the working tree is
  clean and that the ignore rules are still there. The git-tracked half of that
  proof belongs to the leakage check.
- **Held-out item text never enters the Collection**, a generation prompt, or
  coaching material. Any path by which it could is Leakage, and a score
  contaminated by Leakage is void.
- **Results are committed with the command that produced them**, including the
  ones that miss their pre-registered target.

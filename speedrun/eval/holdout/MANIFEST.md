# Held-out data manifest — the freeze

**Frozen at: `2026-08-02T08:12:41Z`** (ISO-8601, UTC)

This file was written **before any generation run, any calibration run, any
attempt, and any score existed**. Nothing had been measured when the rules below
were fixed. That ordering is the whole point of the document: a cutoff chosen
after seeing a result is not a cutoff, and a held-out set assembled after seeing
a score is not held out.

At freeze time **no data file exists**. Every hash below reads `PENDING`, and a
`PENDING` is a promise, not a number. `freeze.py --verify` fails if a data file
appears while its record still says `PENDING`, so the promise cannot be quietly
skipped.

What this manifest fixes, in advance:

- what goes into each of the four sets, and what may never go into them;
- the split rule for H1, stated precisely enough to be re-run by someone else;
- the **cutoff rule for H3**, stated before anyone looks at a result;
- the pre-registered comparison for H4;
- how an item's SHA-256 is computed, so a later edit to an item is detectable;
- which data may never enter the public fork, and why.

Verify at any time:

```
python speedrun/eval/holdout/freeze.py --verify    # exits non-zero on mismatch
```

Terms used here are the project's: **Held-out item**, **Reworded card**,
**Attempt**, **Leakage**, **P-set**, **R-set** — see `speedrun/CONTEXT.md`.

---

## The record

`state` is one of:

| state | meaning |
|---|---|
| `pending` | the data does not exist yet. The hash is a placeholder, not a number. |
| `open` | the data exists and is still being appended to. Per-item hashes are already fixed in the ledger; the file-level hash is not fixed until the set is closed. |
| `frozen` | the file-level SHA-256 is fixed. Any later change is a `--verify` failure. |

`sha256` is over the **raw bytes of the file**. `records` counts non-empty JSONL
lines. Rows in the block below are written by `freeze.py`; do not hand-edit them.

<!-- FREEZE-RECORDS:BEGIN -->
| set | path | state | sha256 | bytes | records | frozen_at (UTC) |
|---|---|---|---|---|---|---|
| PROTOCOL | speedrun/eval/holdout/freeze.py | frozen | 0ca303002325d6d62ab0fc96fa4224d9601c518f870386e0d72df4469a02dbbe | 22957 | - | 2026-08-02T08:16:07Z |
| H1 | speedrun/eval/holdout/h1_reviews.jsonl | frozen | 3563d7a6f385ac7e4277d749c943f61ef96e879a38bcaddc1f037a6f33e2e257 | 341240865 | 3781295 | 2026-08-02T16:16:28Z |
| H2 | speedrun/eval/holdout/h2_pset.jsonl | open | 32b569f1f8fe219c38aece9515945b4dfa15336e0f1335e20df651dbe042bd5f | 31644 | 28 | 2026-08-02T19:25:07Z |
| H3 | speedrun/eval/holdout/h3_gold.jsonl | open | 624c16097e6bc5008dfade03bc057faa36099b0c7f6e8b9b1884cce648ee677c | 43551 | 50 | 2026-08-02T20:41:43Z |
| H4 | speedrun/eval/holdout/h4_rset.jsonl | open | 9036e446a674f5d9514df4c7b4209c5cfd014a7a8e772de5f84a4f870644dbbb | 44205 | 60 | 2026-08-02T20:48:27Z |
<!-- FREEZE-RECORDS:END -->

`PROTOCOL` is `freeze.py` itself. It is hashed so the rules cannot be edited
after the fact without the change showing up in `--verify`.

**Item SHA-256.** For a set with a per-item ledger, an item's hash is

```
sha256( json.dumps(content_fields_only, sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8") )
```

Only the declared content fields are covered, so bookkeeping added later — when
an item was shown, how an Attempt scored — cannot change an item's hash, while
any edit to the question or the answer does.

---

## H1 — memory-calibration reviews

**Contents.** Reviews held back from
[`open-spaced-repetition/anki-revlogs-10k`](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k),
per [ADR-0001](../../docs/adr/0001-calibration-uses-a-public-review-log-corpus.md).
The corpus carries no card text and no topic tags: H1 can validate the Memory
model and can say nothing about Topics, Coverage, Performance or Readiness. The
calibration artifact must say so in its own text.

**Split rule — fixed now, so it cannot be tuned to a Brier score later.**

1. Group every review by collection (the corpus's per-user collection id).
2. Within a collection, sort reviews ascending by review timestamp. Ties break
   on `(card_id, review_th)` ascending — a total order, so the split is
   reproducible byte-for-byte by anyone with the same corpus revision.
3. The **last `ceil(0.20 × n)` reviews of each collection** are H1, held out.
   The remaining reviews are the fitting set. The split is per collection, never
   pooled across collections: a global time split would leak a user's future
   through other users' pasts.
4. Collections with `n < 5` reviews contribute nothing to H1 (fewer than 5 gives
   a held-out block of one review, which is noise, not evidence).
5. No sampling, no shuffling, no seed. The rule is deterministic.

**Corpus revision — recorded at download (T-05).** The exact Hugging Face
dataset revision (commit SHA) is recorded here, together with the SHA-256 of
each downloaded file. Without a pinned revision the split above is not
reproducible.

| field | value |
|---|---|
| dataset | `open-spaced-repetition/anki-revlogs-10k-raw` — see the note below |
| revision (commit SHA) | `197633e5ec9f4a177f285447053329db40e2eb5e` |
| downloaded file | `revlogs.7z`, 8 459 427 959 bytes, sha256 `2921e71e2d39156eef198c8516078ec7806d74443900c0a1005f3c4467389f95` |
| bytes actually fetched | 1 107 379 967 — solid block 0 only |
| per-collection file hashes | `speedrun/eval/calibration/corpus_slice.json` (300 rows: collection id, bytes, sha256) |
| collections sampled | 300 of the 1315 in block 0, `random.Random(20260802).sample`, sorted ascending as strings |
| `h1_reviews.jsonl` sha256 | see the record block above |

**Which distribution, and why.** The processed distribution named above,
`open-spaced-repetition/anki-revlogs-10k`, is **gated**: without a Hugging Face
token its parquet files return HTTP 401, and no token exists on the machine that
ran calibration. The same publisher hosts
[`anki-revlogs-10k-raw`](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k-raw),
ungated, under the same `anki-revlogs-10k` licence, described by the publisher as
"the original data of open-spaced-repetition/anki-revlogs-10k" — the same
reviews from the same 10 000 collections, before the parquet conversion,
exported by Anki's own `Collection::export_dataset`. That is what was downloaded.
It is the same corpus, not a stand-in for it, and it is a closer fit to the split
rule than the processed form: the raw records carry the review's epoch-millisecond
`id`, its `review_kind` and its `ease_factor`, so "sort ascending by review
timestamp" is the record's own timestamp rather than a reconstructed day offset.

`review_th` in step 2 above does not exist as a field in the raw distribution; it
is the review's 1-based rank within its collection under exactly the total order
step 2 describes, and is written into each H1 row as `th`.

**Licence.** Individual research use is permitted; public redistribution is not.
`h1_reviews.jsonl` and every raw corpus file are therefore `.gitignore`d and must
never enter the public fork. `freeze.py --verify` demonstrates their absence from
the working tree rather than asserting it; the leakage check (T-20) extends that
to git-tracked files. The recorded hash still lets the person who ran calibration
prove locally that they scored the same bytes they froze.

---

## H2 — the P-set (Held-out items)

**Empty at freeze time. This is deliberate and is the point of the section.**
No Held-out item exists yet. What is frozen now is the *protocol*; each item's id
and SHA-256 is appended to the ledger below as it is generated, by

```
python speedrun/eval/holdout/freeze.py --append-item --set H2
```

**Contents.** New exam-style Held-out items generated from the corpus,
span-gated by the Generation gate, each mapped to one Topic.

**Rules fixed in advance:**

1. **Never derived from the student's own cards.** An item traceable to a card
   is not a Held-out item; that is what H4 is for
   ([ADR-0004](../../docs/adr/0004-performance-and-the-paraphrase-test-use-separate-sets.md)).
2. **Append before showing.** An item's id and hash must be in the ledger
   *before* the item is shown to the student. An Attempt on an item absent from
   the ledger does not count toward Performance.
3. **Never hinted, explained, or coached on** before its Attempt. Item text never
   enters the Collection, a generation prompt, or coaching material — this is
   what the leakage check tests for.
4. **Append-only.** Item content is never edited after it is appended. A needed
   correction becomes a **new id**; the old row's `status` changes from `live` to
   `retired:<reason>` and the row itself stays. Retired items are excluded from
   every score.
5. `freeze.py --close-set H2` fixes the file-level hash once the last item is in.

**Item schema.** Content fields covered by the item hash:
`id`, `topic`, `stem`, `options`, `answer`, `source_id`, `source_span`.
Anything else in the record (generation metadata, gate log references) is not
hashed and may be added later.

<!-- H2-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
| h2-1D-01 | c4aa6508df5dbfe2bd3d93f84c3ee76f20aebe46c3b869e6c4799340787214a2 | 2026-08-02T19:21:01Z | live |
| h2-1A-01 | 9578556efc2df07ccafb02a3a0d323d186e9008f3bb26afefd270e3a3fb7850b | 2026-08-02T19:21:31Z | live |
| h2-1A-02 | 2b3839723f688281cebe3aba76e95861583f548525c733c51b299572cfb04a08 | 2026-08-02T19:21:42Z | live |
| h2-1A-03 | 626955fe278edfe5a961947556c91c1aba94e319f13e2b0cfb16cc5162218b8e | 2026-08-02T19:21:46Z | live |
| h2-1B-01 | a84132575ec49861a2437d034e8d17fb2725d7bd32185040f65350e931a08760 | 2026-08-02T19:21:48Z | live |
| h2-1B-02 | 3a7cd7fa4020f86e63dc6f51e5996dd130621c486ad93d4fe95fa858872391a1 | 2026-08-02T19:21:54Z | live |
| h2-1B-03 | a638c7b9eb0df97229f30263b1bd0fd3c5506b83fdaf5db2d76731a4b0a8cb25 | 2026-08-02T19:22:04Z | live |
| h2-1C-01 | ba9ba01c9774611af08dafcf1fa710f7c0b8ecb3b71683270c2e0925a9d4981a | 2026-08-02T19:22:07Z | live |
| h2-1C-02 | 6ba7ace836ad8def75a4bc9416e6823e5fba24d46fa52fc349fbab9ce5d188b1 | 2026-08-02T19:22:24Z | live |
| h2-1C-03 | 91cc4108c3ac5741dc6db230336dd6b94848414d37cea18aa5889fb62f4740fa | 2026-08-02T19:22:25Z | live |
| h2-1C-04 | 5da7cb22c8d1d46001c73d39b4679d35c357151a5c7faf60ba869e077aabfe40 | 2026-08-02T19:22:31Z | live |
| h2-1D-02 | 1dfb1d38c2f914485d06c1abe96e41571e4c9e057fbb3a70af1c7c1add29b682 | 2026-08-02T19:22:41Z | live |
| h2-1D-03 | 349134cab224a15a4d404a836717e475c4bb3919b1e71d271d41a99d74e0a578 | 2026-08-02T19:22:43Z | live |
| h2-2A-01 | 1183b53c64e527b2346149d46c8b35b28d4337eaf727e015a09ca50ef9a26c20 | 2026-08-02T19:23:03Z | live |
| h2-2A-02 | e67858c35147882ce7e99f0b874b7903180228c9cf27f2b218f7f61d30e87901 | 2026-08-02T19:23:06Z | live |
| h2-2A-03 | 1cc8078dc0a7318e7d7b6a51619cea7a2ea39f8225ade327044cc02e7341d28b | 2026-08-02T19:23:07Z | live |
| h2-2B-01 | 8804b13747bd2e61e9662dfa0aebb71e93dc2a835d7c717454f12b8c5c1b915b | 2026-08-02T19:23:16Z | live |
| h2-2B-02 | 72ef702ab8e027ef02a0e336c5bd3657c7964a069460e83ef4288de546e2d6b3 | 2026-08-02T19:23:28Z | live |
| h2-2A-04 | 155eb69f6a1da33af427532dbcfc193f4cc4dd4d246629fda314045509067602 | 2026-08-02T19:23:36Z | live |
| h2-2C-01 | ca96e6e7a392b7c77ce434fc2274e1af433b9f6e9d1470c879e6560f98a0f684 | 2026-08-02T19:23:42Z | live |
| h2-2B-03 | 68b81358776eaee176cf8f2fcf975e192ef2e7981b7983d0745f46f685d8e6a2 | 2026-08-02T19:23:45Z | live |
| h2-3A-01 | a4c1f1157322ca0e1cbf460157c3d4c6e960f672c05d4df75bca4775b690b59c | 2026-08-02T19:23:58Z | live |
| h2-2C-02 | 39ced579c77fe627d9488490f64e166c5710a657920f55603da12860b833aa79 | 2026-08-02T19:24:05Z | live |
| h2-2C-03 | 7bebb8b1f9ea7e290ec8fff80c3d9e071c923a8d03c750848f6d513f47d634f1 | 2026-08-02T19:24:05Z | live |
| h2-3A-02 | ab81ba9ba9cd609ea0210704dcae14a07ad3267cb7b7737dff663a7cefe6b025 | 2026-08-02T19:24:10Z | live |
| h2-3B-01 | 6a1a4bd2e1d3582a48785bab87696bdeeffcf01287174f2f194db45515804fe7 | 2026-08-02T19:24:20Z | live |
| h2-3A-03 | 78933231d3048a752a922d0807b471b47166139e74f271fc83b0d7935a711db3 | 2026-08-02T19:24:27Z | live |
| h2-3B-02 | d944d4c8fb6c69c5c62ca5ef266bf69fb3aee87dc9b86d4507b322eb3ff835f7 | 2026-08-02T19:24:32Z | live |
<!-- H2-LEDGER:END -->

*(Empty at freeze — as it should be. Rows are appended by `freeze.py`.)*

---

## H3 — AI card gold set

**Contents.** 50 question/answer pairs drawn by hand from **one real source**,
authored before any card generation runs, and used only as the reference the
generated cards are scored against. Gold text never enters a generation prompt
or coaching material — a gold set fed to the generator is Leakage, and the
leakage check flags H3 items exactly as it flags H2 items.

**Source — recorded at T-18.** One book, as the rule required. The manifest asked
for the book, the edition, the chapter range and a SHA-256; all four are below.

| field | value |
|---|---|
| book | *Biology*, OpenStax, Rice University — `openstax-biology-1e` |
| edition | 1st edition, content version `e989ec3`, uuid `185cbf87-c72e-48f5-b51e-f14f21b5eabd` |
| licence | CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/ |
| fetched from | `https://openstax.org/apps/archive/20260604.144757` |
| download manifest | `speedrun/corpus/raw/manifest.json`, 114 795 bytes, sha256 `f74414dd687f8f5d54aa4a7fe6515cfee07e5afbd2a58ae2e8fc39e67be27a5d` |
| indexed corpus | `speedrun/corpus/out/index.sqlite3`, 10 792 960 bytes, sha256 `8e55edfcbf6f38bc188f58123e120f8ce07e221364d7e117cd9c9e18ea291235` |
| chapters the 50 pairs draw on | 3, 4, 5, 6, 7, 9, 10, 12, 15, 17, 18, 19, 21, 22, 33, 35, 37, 38, 39, 41, 42, 43 — plus per-chapter *Key Terms* and *Chapter Summary* pages |
| pages the 50 pairs cite | 44 distinct `source_id`s of the 350 indexed |

The index's SHA-256 is the operative one: the pairs' spans are byte offsets into
pages inside that file, so a different index is a different source and
`build_gold.py` would not resolve the same spans against it.

**Item schema.** Content fields covered by the item hash:
`id`, `question`, `answer`, `source_id`, `source_span`.

### The cutoff rule — stated now, before any result exists

50 cards are generated from the same source and graded against H3 into the three
buckets from the test plan. Each generated card lands in exactly one bucket:

| bucket | definition |
|---|---|
| **correct and useful** | the answer matches the gold pair on the fact tested, and the card is a card a student would actually be served by reviewing: one fact, answerable from the prompt, no give-away wording. |
| **wrong** | the answer contradicts the gold pair, or states something the source does not support. |
| **correct but bad teaching** | factually right, and still bad: two facts in one card, the answer inferable from the phrasing, trivia with no bearing on the Topic, or a near-duplicate of another card in the batch. |

**Pre-registered cutoff — the run passes only if all three hold:**

1. **correct and useful ≥ 70%** (≥ 35 of 50);
2. **wrong ≤ 10%** (≤ 5 of 50);
3. the gated arm's **wrong** rate is **strictly lower** than the ungated arm's
   wrong rate on the same source and the same 50 generation requests. If it is
   not, the Generation gate is theatre and the write-up says so in those words.

**Grading procedure, also fixed now:**

- The grader sees the generated card and the gold pair, and assigns one bucket.
  Cards are graded in a shuffled order, with gated and ungated cards mixed and
  their arm hidden, so the arm cannot bias the bucket.
- Bucket boundaries are not renegotiated during grading. A card the grader
  genuinely cannot place goes to **correct but bad teaching** — the conservative
  bucket, chosen now so the tie-break cannot be chosen later.
- The percentages are reported **whether or not they clear the cutoff**, with the
  denominator (50) printed beside them. Failing the cutoff is a result, not a
  reason to move the cutoff.

These three numbers are thresholds, not measurements. **Nothing has been measured
yet.**

<!-- H3-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
| h3-1A-01 | 3865ec11a8d209208b460eb687e7c017a6b7553875f8b1fe7006c34121b70013 | 2026-08-02T20:41:33Z | live |
| h3-1A-02 | 1799ece451eb0dbd0a4dbba417d8112f25c7bcb852477ab1fc623de1fb202019 | 2026-08-02T20:41:34Z | live |
| h3-1A-03 | 1ffeda1cede3cba32f1fdd53185efdbf574843b245c24edfd4b7beb8067bf66a | 2026-08-02T20:41:34Z | live |
| h3-1A-04 | 44d0c0fc699baba90a8c2e316ed655db321181973b25245c94a27489104d208f | 2026-08-02T20:41:34Z | live |
| h3-1A-05 | fa06a0134e61ee8062b7770e7cb1fb7eb345279b7cc8ac0421083dd9a73a54ec | 2026-08-02T20:41:34Z | live |
| h3-1B-01 | dbde9a68f86ca32ed1a2ba31246a49e63f47c326a948cdccc60478de115f3a69 | 2026-08-02T20:41:34Z | live |
| h3-1B-02 | 96d85d73be9a09d2903a4caef1b406e6aee941933e130baf1ec1a71edcc1bd0c | 2026-08-02T20:41:35Z | live |
| h3-1B-03 | b9ff3042b7d751c600ae2aaf01f0216570f7cbe6db7ed53ba76cd0568363129a | 2026-08-02T20:41:35Z | live |
| h3-1B-04 | 3b7e78c4952eb5c5a1b85a7cccf2526304eb7053601d4fb76f0a06878ea3d581 | 2026-08-02T20:41:35Z | live |
| h3-1B-05 | 24936cbed490dc622fef2ee55a54f6180fa5476abb2110b80c56e1af86dfd02f | 2026-08-02T20:41:35Z | live |
| h3-1B-06 | 2a077ca3790d69c405f5d8aeaff797691cc28f9d5e6a684dbd8b142bddc7ed59 | 2026-08-02T20:41:35Z | live |
| h3-1C-01 | 6256681daf53c0e14425735a6aa4e6a76255271017c06fce91d287fd2a8da7cd | 2026-08-02T20:41:35Z | live |
| h3-1C-02 | 7d03f13bbe34fa616c90e2f2496f497c5a7c167fcc0feeab0eaea6a52bd5f20f | 2026-08-02T20:41:36Z | live |
| h3-1C-03 | 923b6ec51fd49ce5caa1b8722bdb4cd6e2bd550f50cab030db57baba608e474a | 2026-08-02T20:41:36Z | live |
| h3-1C-04 | 4c39545144134ec5a0ab96293cca382d8d2b795219fbca1193a59e5ead561e37 | 2026-08-02T20:41:36Z | live |
| h3-1C-05 | bf71861f4ef071a60a59b162da6b40efc91686e327c5200a06bc0950a0e5b8b4 | 2026-08-02T20:41:36Z | live |
| h3-1C-06 | 717652cf81c74e0aa5c823c3c1008f069240c524abff853ef983291aaafcf8e9 | 2026-08-02T20:41:36Z | live |
| h3-1D-01 | 9cbd45940fa2c4489e53cb84d0390b8f94dfef9169d7675fc5684742344fb106 | 2026-08-02T20:41:37Z | live |
| h3-1D-02 | 3dbb166ea14779be19ebd199425f8bf733dc6e9ae115d015bb9faaa01d07c3da | 2026-08-02T20:41:37Z | live |
| h3-1D-03 | d5430e1ec056e1ede80562cf0381dc861e8f38351730406db707cca340083c4b | 2026-08-02T20:41:37Z | live |
| h3-1D-04 | 0cf3caaf64cc4664f4720e0ba1a54d6e0d254ed905ef8329fd559dc27b7f01e9 | 2026-08-02T20:41:37Z | live |
| h3-1D-05 | 4d5dfc50c6ecb533cfe1bbe6a30972a761be9e68341499fe38934ee0faa96d9a | 2026-08-02T20:41:37Z | live |
| h3-2A-01 | d09a564a1ec201b7f0335dd11ef3dee4d99e55be20ea830b85a21256fcd587bd | 2026-08-02T20:41:38Z | live |
| h3-2A-02 | d2b298d7c5fec0eb441c33d07f4fdc5c2836bcc7402dcb1a49418d336e1066f9 | 2026-08-02T20:41:38Z | live |
| h3-2A-03 | be10872ff152163d78445ab1bc34562d2d4dbdd704f4d3dd41bbe41642198412 | 2026-08-02T20:41:38Z | live |
| h3-2A-04 | a34b5e82f21fa9c7d154787bb908a0aaae1bbb25ca5b0cde4c42b03ffc8ce11f | 2026-08-02T20:41:38Z | live |
| h3-2A-05 | d072cb1deaf1498e0495e30776ab248975812518f83bd898d20446c50fedaa38 | 2026-08-02T20:41:38Z | live |
| h3-2A-06 | b64a2c530fc603866c7d6c9dab02513f9d5f60b5a61bd97ae3108f59f3fe4166 | 2026-08-02T20:41:39Z | live |
| h3-2B-01 | c7d59201651ff6cda1d657696d2bd1c52dbe3ac033be9b85f35b97bfb51e02fd | 2026-08-02T20:41:39Z | live |
| h3-2B-02 | c2423c175c47d3840bfcda29eabb5d789d84024de3780f45ef6ff5d2614896ef | 2026-08-02T20:41:39Z | live |
| h3-2B-03 | d4883e969a958ae923e36163f9eed88b5cc68d0643536a8f3aedb57256086560 | 2026-08-02T20:41:39Z | live |
| h3-2B-04 | e88fba94e05239a474d71320c6983e64706f60a9be4fc547fbbf2c1410db2d7f | 2026-08-02T20:41:39Z | live |
| h3-2B-05 | 98e057e1eaaa7e81c3ecf6551802795b774bcabe8180736f19cbe6cab172c1ab | 2026-08-02T20:41:39Z | live |
| h3-2C-01 | f7214e11d5f689cbd03954a23f7bf9469ab07efea019f3ac14b29ea5318941ed | 2026-08-02T20:41:40Z | live |
| h3-2C-02 | ff27b284a2007dbad636b78451d13d16586ae117e13cec4831ec48ed4bc31aba | 2026-08-02T20:41:40Z | live |
| h3-2C-03 | d0d29898681f4f8cb8d7b410da34c529a8944c915a2c33349a2a3373b9bb2716 | 2026-08-02T20:41:40Z | live |
| h3-2C-04 | da45d0a1483bebfe8efc6cdad3e717b033b83b0b5140e5ac713dfd2cf4bb6cc6 | 2026-08-02T20:41:40Z | live |
| h3-2C-05 | becc49eee561994165a140f6f9e82e30e55db5e6eed937c58147c7158f42e85c | 2026-08-02T20:41:40Z | live |
| h3-3A-01 | d53719108caf76fd580045f2def1394a1327fec0b372df8c562db5018ddc2bef | 2026-08-02T20:41:41Z | live |
| h3-3A-02 | 89ce33be5cb88b028e8612627ce0b030e66d1a0f1ce1bb9541022b5ebe194235 | 2026-08-02T20:41:41Z | live |
| h3-3A-03 | 72577a7e7d99b5f562c31eb3b73aa7ebeacfb0ef27ea6c2d1e7293310dc30d75 | 2026-08-02T20:41:41Z | live |
| h3-3A-04 | e81d461f384b6bb39ea6b3d7fd5ba5e8704aa06adcc750abfe101fb3e34e4bee | 2026-08-02T20:41:41Z | live |
| h3-3A-05 | c46cc50a63db5689c6c3729679689fc7ca9f028f6e9eb78476908f8b88e24ea4 | 2026-08-02T20:41:41Z | live |
| h3-3A-06 | 1b1eb0a55173d92340a987afebbf294278d63ee6b12fe72c9f3a0c1d954f2c47 | 2026-08-02T20:41:42Z | live |
| h3-3B-01 | 2a21f5395ceba25ed6fed7a69c0b04dd26456ffc6ccd59f9cdec18a0ba8a6a94 | 2026-08-02T20:41:42Z | live |
| h3-3B-02 | 1b55f18f277b86ae89e99fc91de3047298ea7611b63e79a626e189ef865e4746 | 2026-08-02T20:41:42Z | live |
| h3-3B-03 | 4de5aaa6cb89998a38e949a051d40365812cc61df9abf041bdcefef047431db0 | 2026-08-02T20:41:42Z | live |
| h3-3B-04 | 64528133d6a42843a28a7b6a14c49d7dc28be23a19ecd1a14ea35db082111c25 | 2026-08-02T20:41:42Z | live |
| h3-3B-05 | 75975e16f5be3922e2a82768f300546bf83a11af9763c13bc9c91c88ba73e19c | 2026-08-02T20:41:43Z | live |
| h3-3B-06 | 4c95968e26d40f213ab96cf8192883c5ce26923cd19ab8e0d9ffb708d96d6dc5 | 2026-08-02T20:41:43Z | live |
<!-- H3-LEDGER:END -->

---

## H4 — the R-set (Reworded cards)

**Contents.** 30 of the student's own cards × 2 rewordings each = 60 Reworded
cards. Feeds the paraphrase test only and **never counts toward any score**.
Added once a real deck exists (T-03) and the student has studied it (T-11).

**Selection rule — fixed now, so the 30 cannot be picked to flatter a gap.**

1. Eligible: cards in the demo section that the Crosswalk maps to a Topic and
   that carry **≥ 3 graded reviews** at selection time. Unmapped cards are not
   eligible.
2. Sort eligible cards by card id ascending, then take a sample of **30** using
   `random.Random(seed).sample(...)` with **`seed = 20260802`** — recorded here,
   in advance, so the selection is reproducible and was not re-rolled.
3. Each selected card gets exactly **2** rewordings: the same fact, restated as
   an exam-style question, with no wording carried over from the card beyond
   unavoidable technical terms.
4. A rewording that changes the fact tested is a defect, not a rewording; it is
   replaced and the replacement recorded as a new id.
5. No Reworded card is shown to the student before the paraphrase test runs.

**Item schema.** Content fields covered by the item hash:
`id`, `card_id`, `rewording_index`, `prompt`, `answer`.

**Pre-registered comparison.** The paraphrase test reports three numbers with
ranges, on one student: recall on the card, accuracy on the R-set, accuracy on
the P-set. The target stated in advance is a **gap ≥ 15 points** between card
recall and P-set accuracy. The gap is reported whichever way it comes out, and
if the three numbers collapse into one, that is published as a finding — the
Performance model would be copying the Memory model.

<!-- H4-LEDGER:BEGIN -->
| item_id | sha256 | appended_at (UTC) | status |
|---|---|---|---|
| h4-01-1 | d433ac3cbc337de7258b167baa4e42638b41dc4b7985e3521e674f87ed9bff0c | 2026-08-02T20:39:45Z | live |
| h4-01-2 | ef58a5ef566c8ca562645bc07c385f0076f5cbae94c326ac10b5077868f70d8c | 2026-08-02T20:39:45Z | live |
| h4-02-1 | f316e629c10d49193b991d56d85e0dd0ab53a088e1ba3b00705e2c5aa64efb19 | 2026-08-02T20:40:12Z | live |
| h4-02-2 | 2f96b83de6d22d9617623f3bbf34d649410a4129b5250a21afecf82c0e4c7ae6 | 2026-08-02T20:40:12Z | live |
| h4-03-1 | 3d1c73ef22cc9db58eb33c93a57a95922333084f6a9fda90287101e13cec7d21 | 2026-08-02T20:40:31Z | live |
| h4-03-2 | eccfbb63463f1c6b733e30e40bb4c5d88347f4e8b8784c2f56284247bb7d8469 | 2026-08-02T20:40:31Z | live |
| h4-04-1 | 6a3bf0fe1d1cc21f588bc8d6c17ae4facc43ec4c341c8337908de6fbef38441e | 2026-08-02T20:40:45Z | live |
| h4-04-2 | 55c7da52ea4efcc7f4203a62d98a606560cd16e08c6d6268879ed5fa53d1238e | 2026-08-02T20:40:45Z | live |
| h4-05-1 | 538645579d7c5c34237a442bf347e96038788a0b3475e05a2c3fedcb5a26014a | 2026-08-02T20:40:56Z | live |
| h4-05-2 | 4ac10d6aeaf579efbfffa116c51c0cca3f7a2e030d541e872b17877df7efdc36 | 2026-08-02T20:40:56Z | live |
| h4-06-1 | 9c00a5176d9cf28e67ec68b7108ded83cbf66e2e7147d268da927812a69fedb6 | 2026-08-02T20:41:08Z | live |
| h4-06-2 | 1adf3a354e00a7383e849345845c921fbf6d73b116264fb1ea88731b69a3f91f | 2026-08-02T20:41:08Z | live |
| h4-07-1 | cbe78472a464f69582bca1f18966db31a6e2f24afb3d02d8a82fa500baad2208 | 2026-08-02T20:41:24Z | live |
| h4-07-2 | e4e4cc9efd226b529c19094966606270f0d2d249139522c39aa974518996f4fe | 2026-08-02T20:41:24Z | live |
| h4-08-1 | dce2c81206e73d8ce9ebb171db6f26c6b6ac7c9861826b780b11fc92d276efd8 | 2026-08-02T20:41:39Z | live |
| h4-08-2 | 374a1a477b763d493425646138a52ecfbd4ae7ca844ed3bc0d4fc7041480df2a | 2026-08-02T20:41:39Z | live |
| h4-09-1 | 59b01cbe08a7b57092e5879124a1aadb4e0f8df6a822ba0877ea47414793533b | 2026-08-02T20:41:49Z | live |
| h4-09-2 | 78350ea3a96889b0dca462cee0135850636c91fecde8bc375d6a84860ae27842 | 2026-08-02T20:41:49Z | live |
| h4-10-1 | b02632648942a54f4282d20b429f95f2151b6b9d688586cfab0de05dd8145a49 | 2026-08-02T20:42:09Z | live |
| h4-10-2 | b80257830a72bb8293e7e8e8429e9cf58ceed23e189762f7b92a15b634319357 | 2026-08-02T20:42:09Z | live |
| h4-11-1 | b03ce03221d561b3cba8bcf29761c6ea630dcdf07a153a7e98cc442f78744453 | 2026-08-02T20:42:18Z | live |
| h4-11-2 | 3903bebe0c5668e998e069dc21fd35960e10e18a28513d4cf6c5e17b9af3625f | 2026-08-02T20:42:18Z | live |
| h4-12-1 | 198a79b5ffc3730a9979948befa72cf936080cca4a69eb89fffec6e43e71c545 | 2026-08-02T20:42:41Z | live |
| h4-12-2 | c82ac2b7ae5996d7e6cc9edc5076b4cff26f0d927531743f17c5ddd558666c1e | 2026-08-02T20:42:41Z | live |
| h4-13-1 | cd06610a0468212f029c90e74c54d9b0b3f70b06357a243efe34e3bf6c45ceb1 | 2026-08-02T20:42:59Z | live |
| h4-13-2 | f0b315ac3b9f23c63b21363cb1e8c5526aab3dbcdc93bbc0359125e4c1d296a8 | 2026-08-02T20:42:59Z | live |
| h4-14-1 | ba775cb7af57260c7de21fac589c8a7c60503231e018bbef83e52a5a8995c2a5 | 2026-08-02T20:43:15Z | live |
| h4-14-2 | 6a9a8da8193c0bd0a14bc6a77282e719251e2dc4b0d94d72df50bdb1d5cb06f6 | 2026-08-02T20:43:15Z | live |
| h4-15-1 | 9dd2b2ad5994ae804e7ccc73764f58f5a73f60bfb0e0e430c72783dd55fbc8df | 2026-08-02T20:43:30Z | live |
| h4-15-2 | 850455c236378517ba2b90c8b76f9b4947ad8a83aa1bc077d9adc8903c5d5ab2 | 2026-08-02T20:43:30Z | live |
| h4-16-1 | ed41db8d54eabc953476d832734dd128a3b07f1e6eac5e3e0439b8b823a3cb17 | 2026-08-02T20:43:43Z | live |
| h4-16-2 | 9cd7e7e46bc0f0624d1740df4c3c4252dee408d4a27aa44ad469eb9bf4c5c284 | 2026-08-02T20:43:43Z | live |
| h4-17-1 | d4fc78bffd10c9c5f58c65335d84ae48598b7c2dcb94ab69e774c8a022e41d89 | 2026-08-02T20:43:57Z | live |
| h4-17-2 | a345858b1aa3c20982d82d7aa665eaad416bf0f7f88136a8696d48f370827771 | 2026-08-02T20:43:57Z | live |
| h4-18-1 | 91d559cb23a1e250a860d0ada319c6de23c298ba9a8b769432e355a1b758f906 | 2026-08-02T20:44:10Z | live |
| h4-18-2 | 86ddd54d6acde86215849f5cf96520885fdbb2ace46620c410a5911251b61947 | 2026-08-02T20:44:10Z | live |
| h4-19-1 | d62ffbfbb84f6539ffc179efe0b381b3dbf7b3df97c5bac420a7c018b3f8d007 | 2026-08-02T20:44:22Z | live |
| h4-19-2 | 4e91ea9e4aea058afe78b507115dd0d0226d6f6d841189d39ab3d9acd7547099 | 2026-08-02T20:44:22Z | live |
| h4-20-1 | 1d8ce72c962d449e27b26d74482e3c3b84d0e47059b9de29082f8dd8652e09eb | 2026-08-02T20:44:40Z | live |
| h4-20-2 | 3885280783c38abd634a00f99f7a582038ee5c915c80a6ecf231c0f83417dce2 | 2026-08-02T20:44:40Z | live |
| h4-21-1 | 6e690c8e166e297e3c519203e705f2f72660f67491961021da52c4a7fe11fa26 | 2026-08-02T20:44:52Z | live |
| h4-21-2 | 1ecbf8511dde7a31052d9215a7e5c2a4be879e52a04c307a4898e3bd7f75a2e8 | 2026-08-02T20:44:52Z | live |
| h4-22-1 | 4a8d70dd5e6a5f01fde4596c60b38a54a5e26cdcf558a2c2229d1a080d476451 | 2026-08-02T20:45:10Z | live |
| h4-22-2 | fd5dfeacf6243febafc3aa1a9cd5481c952dfa08ea2790603e68524f1df59dea | 2026-08-02T20:45:10Z | live |
| h4-23-1 | cddd106c1ece5cf73203f740eab47a14519075ce4e6d602fb88173d517d36307 | 2026-08-02T20:45:21Z | live |
| h4-23-2 | 8b34c9f68b65c0bd12eeeb31cab0591c7973be2756cfec07d758b3c56e3b9c06 | 2026-08-02T20:45:21Z | live |
| h4-24-1 | 4068240ca80a03e02d5e56cc941011d929c7c191181da9f58c4e996c77dfcb7b | 2026-08-02T20:45:34Z | live |
| h4-24-2 | ab1795a8aead571f1cafc2e3a5e05282f2fe24cef588daa2f0d9cdf25be13efb | 2026-08-02T20:45:34Z | live |
| h4-25-1 | a033ca5ca3390405e3477f100d0f1cce13f594578a9ea7f6fba92c0c0b5d715c | 2026-08-02T20:45:47Z | live |
| h4-25-2 | af1eb791f8688d667ce69d73ad11ae5cd128c474f3f7ab648d2c8fd948868db3 | 2026-08-02T20:45:47Z | live |
| h4-26-1 | 690ddde319616fa743a40be44088b23739afda118293ac1595804bdb2b009d29 | 2026-08-02T20:46:01Z | live |
| h4-26-2 | fb01b24b6793d6e8fea55190c9ea7ca53a4da61693bb9152eeb57a221d0226c1 | 2026-08-02T20:46:01Z | live |
| h4-27-1 | 4a86a4f72bbf780be7fecdb3a9d61e1956f315ef4d39cc31853b921f24a3da97 | 2026-08-02T20:46:35Z | live |
| h4-27-2 | 8da6c47046a28707dcbc3eab23b852c131c1a2f9a1b4865998869895abcab684 | 2026-08-02T20:46:35Z | live |
| h4-28-1 | 7116179f240fc017162c6e07e32f5b768cb12d5a61129ef58f3d7214444f8397 | 2026-08-02T20:46:49Z | live |
| h4-28-2 | 18c33d542a0f8f343f2fb7a1525c1f60479ae834223274e3a5f65463f0bf2029 | 2026-08-02T20:46:49Z | live |
| h4-29-1 | 01ea7c0971fe2d0671c609f10f34577a33cb1b9453e9090c585ba7901abca8a4 | 2026-08-02T20:47:12Z | live |
| h4-29-2 | bd3d5cbf48c93faad1218fb5bbb367a13a9009eed86e12c59424714e6bda08b1 | 2026-08-02T20:47:12Z | live |
| h4-30-1 | 81cdf8d0018614169f3d085f9adc821de607dbbd93dce89fa67a079cdbbbec8e | 2026-08-02T20:47:29Z | live |
| h4-30-2 | af6f9d81cf8154e7a8eec54e5d60f3a69628fdbce8b4a167770714f3c0cb117f | 2026-08-02T20:47:29Z | live |
<!-- H4-LEDGER:END -->

---

## What must never enter the public fork

| kept out | why |
|---|---|
| the `anki-revlogs-10k` corpus, in any form | its licence permits individual research use and **forbids public redistribution** |
| `h1_reviews.jsonl` | it is a derivative of that corpus — the same licence applies |
| any raw review data or collection file under `speedrun/eval/holdout/` | raw review history is the student's own study data and, for H1, licensed third-party data. Only hashes and derived numbers commit. |

The `.gitignore` entries that enforce this each carry the reason as a comment.
`freeze.py --verify` checks both directions: that nothing matching those patterns
is in the working tree, and that the ignore rules are still present in
`.gitignore` — a deleted ignore rule fails the check even when no file has
appeared yet.

**Scope of that check, stated honestly:** it inspects the working tree, not git
history. The git-tracked assertion belongs to the leakage check (T-20), which
also flags near-copies of H2/H3 items in generation prompts, corpus chunks and
coaching material.

---

## Amendments

Append-only. Every change to this manifest after the freeze timestamp gets a row
here — what changed, when, and why. An empty section is the strongest state this
section can be in.

| when (UTC) | what changed | why |
|---|---|---|
| 2026-08-02 | H1: the `PENDING` corpus-revision block filled in with the pinned revision, the archive's SHA-256, the sampling rule and the per-collection hash file. | The manifest said these were to be recorded at download time. T-05 downloaded the corpus. |
| 2026-08-02 | H4: the selection rule's "≥ 3 graded reviews at selection time" clause was **not applied** to the draw recorded in `speedrun/eval/paraphrase/rset_selection.json`. Seed, sort order and sample size are unchanged. | The only collection available is a pristine shared deck with an empty `revlog` and `reps = 0` on all 2,888 cards, so the clause leaves zero eligible cards and no R-set can exist. Studying the deck needs the participant the paraphrase test is itself blocked on. Named rather than deleted: `select_rset.py` refuses `--no-study-history` against a collection that *does* have reviews, so re-drawing against a studied collection restores the rule exactly — and changes which 30 cards are drawn. |
| 2026-08-02 | H1: the recorded distribution is `anki-revlogs-10k-raw`, not `anki-revlogs-10k`. | The processed distribution is gated and returns HTTP 401 without a Hugging Face token. The raw distribution is the same corpus from the same publisher under the same licence, ungated. Stated rather than silently substituted; the split rule itself is unchanged. |
| 2026-08-02 | H1: noted that `review_th` is not a field in the raw distribution and is computed as the rank under the total order step 2 already fixes. | The split rule was written against the processed distribution's column names. The order it describes is unchanged; only where the number comes from is. |
| 2026-08-02 | H3: the `PENDING` source block filled in — book, edition, licence, archive base, and the SHA-256 of both the download manifest and the indexed corpus the pairs' spans address. | The manifest said the source was to be recorded once the demo-section corpus landed. T-07 built it and T-18 authored the 50 pairs against it. The cutoff rule, the bucket definitions and the grading procedure are untouched. |

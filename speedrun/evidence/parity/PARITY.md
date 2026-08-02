# Platform parity: the same collection, offline, on both platforms

**Verdict: every field agrees.** One collection, byte-identical on desktop and on
the phone, read with no network on either. Every `SectionScores` field the
Android screen exposes matches the desktop value exactly, including
`cards_unmapped = 947` — the number that only a build whose engine can read the
Crosswalk could produce.

Two gaps are stated rather than papered over: `TopicMastery` has **no on-device
surface** in this build, so its per-topic rows are compared only on desktop
(§6); and the phone prints Memory to two decimals, so the agreement on that one
float is verified to two decimals and not further (§4).

---

## 1. What was compared

| | |
|---|---|
| Collection | 3,372 cards · 3,372 notes · 12,958 reviews · 2,460 with FSRS memory state |
| Built by | `speedrun/eval/bench/gen_deck.py` via `parity.py build`, seed `20260802` |
| Crosswalk | `speedrun/crosswalk/miledown-bb-v1.json` (38 entries), installed with `col.set_config("speedrunCrosswalk", <parsed json>)` |
| SHA-256 | `e17b781415960f90b29310326c225d95f4b6526276dc998fe10c6a44e98c9410` |
| Desktop engine | fork `rslib`, Anki 26.08, through `pylib` |
| Phone engine | same `rslib` through `rsdroid-release.aar` built 11:41, packaged into `AnkiDroid-play-x86_64-debug.apk` at 11:57 and installed at 11:57 |
| Device | `Medium_Tablet` AVD (`sdk_gtablet_x86_64`), AnkiDroid `2.25.0alpha2-debug` |

The deck is synthetic and generated, which the collection says about itself in
its own config (`speedrunSyntheticBench`). That does not weaken this test: parity
is a claim about two engines reading the same bytes, and the bytes being
generated rather than studied changes nothing about whether the two agree. No
score in this file is a measurement of a person.

## 2. Commands

```sh
# build the collection and install the crosswalk into it
PYTHONPATH="pylib;out/pylib" out/pyenv/Scripts/python.exe \
  speedrun/evidence/parity/parity.py build \
  --base <throwaway> --cards 3000 --out <scratch>/parity-collection.anki2

# desktop: read every score with the network guard on
PYTHONPATH="pylib;out/pylib" out/pyenv/Scripts/python.exe \
  speedrun/evidence/parity/parity.py read \
  --col <scratch>/desktop-read.anki2 --out speedrun/evidence/parity/desktop.json

# phone: same bytes, no network
adb shell settings put global airplane_mode_on 1
adb shell svc wifi disable; adb shell svc data disable
adb shell am force-stop com.ichi2.anki.debug
adb shell 'rm -f .../AnkiDroid/collection.anki2*'
adb push <scratch>/phone-push.anki2 .../AnkiDroid/collection.anki2
adb shell am start -n com.ichi2.anki.debug/com.ichi2.anki.IntentHandler
adb shell am start -n com.ichi2.anki.debug/com.ichi2.anki.SingleFragmentActivity \
  --es extra_fragment_name com.ichi2.anki.speedrun.SpeedrunScoresFragment
adb shell uiautomator dump /sdcard/ui.xml   # -> phone-scores.txt

# control: the same read with the crosswalk uninstalled
PYTHONPATH="pylib;out/pylib" out/pyenv/Scripts/python.exe \
  speedrun/evidence/parity/parity.py read --col <scratch>/control-no-crosswalk.anki2 \
  --remove-crosswalk --out speedrun/evidence/parity/desktop-no-crosswalk.json
```

## 3. "Offline" means something on both sides

**Desktop.** `parity.py read` replaces `socket.socket.connect`,
`connect_ex`, `create_connection`, `getaddrinfo` and `gethostbyname` with a
function that raises `NetworkUsed`. The read completed, so nothing in the path
from `SectionScores` to the JSON reached for the network. This is stronger
evidence than unplugging the machine — an unplugged machine only shows that
nothing *got through* — and it does not disturb the three other agents sharing
this box. `"network_blocked": true` is recorded in `desktop.json`.

**Phone.** Airplane mode on, wifi and mobile data disabled:

```
$ adb shell settings get global airplane_mode_on   -> 1
$ adb shell dumpsys connectivity | grep 'Active default network'
      Active default network: none
$ adb shell ping -c 1 -W 2 8.8.8.8
      connect: Network is unreachable
```

The airplane-mode icon is visible in the status bar of
`phone-speedrun-scores-offline.png`, taken while the scores were on screen.

**Agent service.** Nothing was listening on `127.0.0.1:8000` on the host during
any of this (`Get-NetTCPConnection -LocalPort 8000` returned nothing), and the
emulator had no network at all, so it could not have reached a service on the
host either. The scores below were computed with the agent service absent —
which is the condition T-21 asks for, and is currently also just the truth.

## 4. Field by field

Desktop values are from `desktop.json`; phone values are the text of the
Speedrun screen, captured with `uiautomator dump` into `phone-scores.txt` and
photographed in `phone-speedrun-scores-offline.png`.

### Chem/Phys (CP)

| Field | Desktop | Phone | |
|---|---|---|---|
| `memory.available` | `true` | shown as a number | = |
| `memory.estimate` | `0.715801` | `0.72` | = at printed precision |
| `memory.range_low` / `high` | `0.621982` / `0.809621` | `0.62` / `0.81` | = |
| `memory.abstain_reason` | `""` | none printed | = |
| `performance.available` | `false` | `ABSTAINS` | = |
| `performance.abstain_reason` | `120 held-out attempts across 10 topics in CP, but the performance model is not fitted yet.` | identical | = |
| `readiness.available` | `false` | `ABSTAINS` | = |
| `readiness.abstain_reason` | `No readiness for CP until performance is available: 120 held-out attempts across 10 topics in CP, but the performance model is not fitted yet.` | identical | = |
| `coverage_pct` | `100.0` | `100%` | = |
| `graded_reviews` | `861` | `861` | = |
| `holdout_attempts` | `120` | `120` | = |
| `topics_attempted` | `10` | `10` | = |
| **`cards_unmapped`** | **`947`** | **`947`** | **=** |

### Bio/Biochem (BB)

| Field | Desktop | Phone | |
|---|---|---|---|
| `memory.available` | `true` | number shown | = |
| `memory.estimate` | `0.710731` | `0.71` | = |
| `memory.range_low` / `high` | `0.679457` / `0.742005` | `0.68` / `0.74` | = |
| `performance.abstain_reason` | `108 held-out attempts across 9 topics in BB, but the performance model is not fitted yet.` | identical | = |
| `readiness.abstain_reason` | `No readiness for BB until performance is available: …` | identical | = |
| `coverage_pct` | `100.0` | `100%` | = |
| `graded_reviews` | `6944` | `6944` | = |
| `holdout_attempts` | `108` | `108` | = |
| `topics_attempted` | `9` | `9` | = |
| **`cards_unmapped`** | **`947`** | **`947`** | **=** |

### Psych/Soc (PS)

| Field | Desktop | Phone | |
|---|---|---|---|
| `memory.estimate` | `0.717939` | `0.72` | = |
| `memory.range_low` / `high` | `0.623797` / `0.812081` | `0.62` / `0.81` | = |
| `performance.abstain_reason` | `144 held-out attempts across 12 topics in PS, but the performance model is not fitted yet.` | identical | = |
| `readiness.abstain_reason` | `No readiness for PS until performance is available: …` | identical | = |
| `coverage_pct` | `100.0` | `100%` | = |
| `graded_reviews` | `936` | `936` | = |
| `holdout_attempts` | `144` | `144` | = |
| `topics_attempted` | `12` | `12` | = |
| **`cards_unmapped`** | **`947`** | **`947`** | **=** |

### CARS

| Field | Desktop | Phone | |
|---|---|---|---|
| `memory` / `performance` / `readiness` | all `available: false` | all `ABSTAINS` | = |
| abstain reason (all three) | `We don't model CARS knowledge, because the AAMC states there isn't any to model: everything needed to answer is in the passage.` | identical | = |
| `coverage_pct` | `0.0` | `0%` | = |
| `graded_reviews` / `holdout_attempts` / `topics_attempted` | `0` / `0` / `0` | `0` / `0` / `0` | = |
| `cards_unmapped` | `0` | `0` | = |

**Note on CP and PS Memory.** Both print `0.72 (range 0.62 – 0.81)` on the
phone. That is not the same score twice: the desktop floats are `0.715801` and
`0.717939`, which genuinely round to the same two decimals, as do their bounds.
The phone's `%.2f` is the limit of what its screen can be checked against, so
Memory is verified to two decimals and the underlying float is not. Verifying it
further would need a numeric surface on the device that does not exist yet.

## 5. The `cards_unmapped` control

`cards_unmapped = 947` is not a number that could arrive by accident, and it is
the field that says whether the phone resolved topics through the Crosswalk. Run
the identical read with the Crosswalk uninstalled and the engine falls back to
counting cards that carry no `mcat::` tag of their own:

| | Crosswalk installed | Crosswalk removed |
|---|---|---|
| `cards_unmapped` (all sections) | **947** | **2400** |
| BB `graded_reviews` | **6944** | 774 |
| BB `cards_considered` | 1633 | 180 |

The phone printed 947 and 6944. An APK carrying an engine that could not read
the Crosswalk would have printed 2400 and 774 — and one carrying no unmapped
accounting at all would have printed 0. It printed neither. The `.aar` rebuilt at
11:41 is in the APK the emulator is running.

## 6. `TopicMastery`: desktop only, and why

`TopicMastery` is exposed on desktop (the add-on's per-topic breakdown) and
**has no screen, menu entry or intent on Android** — `SpeedrunScoresFragment` is
the only Speedrun surface in the app, and it calls `SectionScores` alone. There
is therefore no honest way to run `TopicMastery` *on the device* without adding
code to AnkiDroid, which this ticket does not own.

What that does and does not leave unverified:

* **Verified on both platforms**, because `SectionScores` computes them *from*
  `TopicMastery` and prints them: `cards_unmapped` (identical field),
  `graded_reviews` (sum of every topic's `review_count`), `coverage_pct`
  (covered topics ÷ outline count), and Memory (the `cards_with_memory_state`-
  weighted mean of every topic's `mean_retrievability`, with its range).
* **Not verified on the device**: the per-topic rows themselves, and
  `cards_considered` / `cards_excluded`, which `SectionScores` does not expose.

Desktop `TopicMastery` for Bio/Biochem, for the record — `cards_considered`
1633, `cards_excluded` 372 (Speedrun's own attempt cards, kept out of every
measurement), `cards_unmapped` 947:

| topic | mean R | range low | range high | cards | with memory state | reviews | covered |
|---|---|---|---|---|---|---|---|
| `mcat::BB::1A` | 0.7188 | 0.6839 | 0.7536 | 161 | 132 | 657 | true |
| `mcat::BB::1B` | 0.6909 | 0.6353 | 0.7465 | 67 | 56 | 265 | true |
| `mcat::BB::1C` | 0.6919 | 0.6626 | 0.7211 | 208 | 173 | 934 | true |
| `mcat::BB::1D` | 0.6941 | 0.6577 | 0.7304 | 161 | 141 | 692 | true |
| `mcat::BB::2A` | 0.7260 | 0.6965 | 0.7554 | 208 | 167 | 886 | true |
| `mcat::BB::2B` | 0.7205 | 0.6687 | 0.7722 | 67 | 52 | 274 | true |
| `mcat::BB::2C` | 0.7173 | 0.6876 | 0.7469 | 208 | 169 | 955 | true |
| `mcat::BB::3A` | 0.7366 | 0.6974 | 0.7759 | 114 | 94 | 483 | true |
| `mcat::BB::3B` | 0.7081 | 0.6865 | 0.7297 | 439 | 356 | 1798 | true |

Their review counts sum to 6,944, which is the `graded_reviews` the phone
printed.

## 7. Neither platform wrote to the collection

The Sensor rule says Speedrun reads the collection and never writes to it. That
is testable here, because both platforms were handed the same file and the file
can be hashed afterwards:

| | SHA-256 |
|---|---|
| as built | `e17b781415960f90b29310326c225d95f4b6526276dc998fe10c6a44e98c9410` |
| after the desktop read | `e17b7814…c9410` (identical) |
| pulled back off the phone after AnkiDroid opened it and computed every score | `e17b7814…c9410` (identical) |

The phone's write-ahead log was 0 bytes when the app was stopped. Opening a
collection, resolving 3,372 cards through a 38-entry crosswalk and reporting
twelve scores changed not one byte of the student's data on either platform.

## 8. What failed, and what is still untested

* **Nothing disagreed.** No discrepancy was found between the two platforms on
  any field either of them exposes.
* **`TopicMastery` has no Android surface.** §6. This is a gap in what can be
  compared, not a disagreement, and it is worth closing: the field with the most
  room to drift between platforms is the one that cannot currently be read on
  one of them.
* **Memory is compared to two decimals.** §4. The phone prints `%.2f` and there
  is no other numeric output on the device.
* **One collection, one device, one architecture.** This is x86_64 on an
  emulator. An arm64 phone runs a different `librsdroid.so` from the same
  sources; nothing here tests that build.
* **Anki's single-instance key is machine-wide.** Not a parity finding, but
  discovered while doing this and it will bite anyone running two profiles at
  once: `AnkiApp.KEY` is `anki<checksum(username)>`, ignoring `ANKI_BASE`, so a
  second Anki hands its arguments to the first and exits. `ANKI_SINGLE_INSTANCE_KEY`
  overrides it.

## Files

| | |
|---|---|
| `parity.py` | builds the collection, installs the crosswalk, reads every score with the network guard on |
| `desktop.json` | every `SectionScores` and `TopicMastery` field, desktop, offline |
| `desktop-no-crosswalk.json` | the control in §5 |
| `phone-scores.txt` | the Speedrun screen's text, from `uiautomator dump` |
| `phone-speedrun-scores-offline.png` | the same screen, airplane mode visible in the status bar |

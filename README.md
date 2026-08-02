# Speedrun

## Exam: MCAT (472–528)

Three science sections modeled — Chem/Phys, Bio/Biochem, Psych/Soc.
**CARS is deliberately not modeled**, because the AAMC states there is no content knowledge to model there. See [SpikyPOV 4](speedrun/docs/TRACEABILITY.md).

A study app that reports **three separate scores, each with a range, never blended**: Memory (can you recall this fact?), Performance (can you answer a *new* exam-style question?), and Readiness (what would you score today?). It abstains rather than guess — a score appears only once it is earned.

- **What it is and why:** [speedrun/docs/PRD.md](speedrun/docs/PRD.md)
- **How it's built:** [speedrun/docs/ARCHITECTURE.md](speedrun/docs/ARCHITECTURE.md)
- **Every feature traced to the claim that forced it:** [speedrun/docs/TRACEABILITY.md](speedrun/docs/TRACEABILITY.md)
- **Companion app:** [rubanikov/Anki-Android](https://github.com/rubanikov/Anki-Android), sharing this engine

### Credit and license

This is a **fork of [Anki](https://github.com/ankitects/anki)** by Ankitects Pty Ltd — the spaced repetition program that does the actual scheduling work here. Speedrun adds measurement on top of it; FSRS, the scheduler, and the sync protocol are Anki's.

Licensed **GNU AGPL, version 3 or later**, with portions contributed by Anki users under the BSD-3 license. See [LICENSE](./LICENSE) and [CONTRIBUTORS](./CONTRIBUTORS).

---

# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)

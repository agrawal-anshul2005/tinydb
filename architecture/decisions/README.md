# Architecture Decision Records — Index & Evolution Log

All ADRs follow Michael Nygard's (2011) format (`Title`, `Status`, `Context`, `Decision`, `Consequences`). Whenever an ADR is revised based on empirical evidence, design review, or run findings, the superseded version is preserved under [`archive/`](./archive/) using `<name>_v<version>.md` nomenclature and marked `Superseded`.

## Active ADRs

| ADR | Decision | Current Version | Status | Superseded History |
|---|---|---|---|---|
| [ADR-001.md](./ADR-001.md) | D1: Splitting the work | v1 | Accepted | — |
| [ADR-002.md](./ADR-002.md) | D2: Control flow | v3 | Accepted | [`ADR-002_v1.md`](./archive/ADR-002_v1.md) → [`ADR-002_v2.md`](./archive/ADR-002_v2.md) |
| [ADR-003.md](./ADR-003.md) | D3: Hand-offs | v1 | Accepted | — |
| [ADR-004.md](./ADR-004.md) | D4: State | v1 | Accepted | — |
| [ADR-005.md](./ADR-005.md) | D5: Tools | v2 | Accepted | [`ADR-005_v1.md`](./archive/ADR-005_v1.md) |
| [ADR-006.md](./ADR-006.md) | D6: Models | v3 | Accepted | [`ADR-006_v1.md`](./archive/ADR-006_v1.md) → [`ADR-006_v2.md`](./archive/ADR-006_v2.md) |
| [ADR-007.md](./ADR-007.md) | D7: Checks | v2 | Accepted | [`ADR-007_v1.md`](./archive/ADR-007_v1.md) |
| [ADR-008.md](./ADR-008.md) | D8: Reviewer independence | v2 | Accepted | [`ADR-008_v1.md`](./archive/ADR-008_v1.md) |
| [ADR-009.md](./ADR-009.md) | D9: Safety and failures | v1 | Accepted | — |
| [ADR-010.md](./ADR-010.md) | D10: Triggers | v1 | Accepted | — |

## Evolution Highlights (Pre-Implementation Evidence)

1. **v1 → v2 (`ADR-002`, `ADR-006`, `ADR-008`):** Deprecated `gemini-2.5-*` models (Dec 1, 2026 automatic rerouting) and single-provider quota pressure led us to migrate Stages 1–4 to Gemini 3.x and offload Stages 5–6 to GitHub Models (`models: read`), upgrading Stage 6 to true **cross-provider** reviewer independence (and rejecting desktop Ollama on a self-hosted runner for public-repo security reasons).
2. **v2 → v3 (`ADR-002`, `ADR-006`):** Live API endpoint probing on our free-tier Gemini key returned `503 UNAVAILABLE` for `gemini-3.8-flash` and `429 RESOURCE_EXHAUSTED` for `gemini-4-argon`/`gemini-4-neon`, while `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`, and `gemma-4-31b-it` returned `200 OK`. We revised the Coder escalation ladder to `gemini-3.5-flash` (×2) → `gemini-3.7-flash` (×1) with an ordered `429`/`503` fallback chain.
3. **v1 → v2 (`ADR-005`, `ADR-007`):** Upgraded Stage 3/4 testing from example-only unit tests to a **Property-Based Testing (PBT)-first** strategy using `hypothesis` (dev/test-only, `max_examples=50`, `derandomize=True`) followed by example-based boundary tests and the full TinyDB regression suite, ensuring universal behavioral invariants are verified and shrunk counterexamples guide CoderAgent retries.

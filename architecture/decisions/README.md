# Architecture Decision Records — Index & Evolution Log

All ADRs follow Michael Nygard's (2011) format (`Title`, `Status`, `Context`, `Decision`, `Consequences`). Whenever an ADR is revised based on empirical evidence, design review, or live Actions runs, the superseded version is preserved under [`archive/`](./archive/) using `<name>_v<version>.md` nomenclature and marked `Superseded`.

## Active ADRs

| ADR | Decision | Current Version | Status | Superseded History |
|---|---|---|---|---|
| [ADR-001.md](./ADR-001.md) | D1: Splitting the work | v1 | Accepted | — |
| [ADR-002.md](./ADR-002.md) | D2: Control flow | v4 | Accepted | [`ADR-002_v1.md`](./archive/ADR-002_v1.md) → [`ADR-002_v2.md`](./archive/ADR-002_v2.md) → [`ADR-002_v3.md`](./archive/ADR-002_v3.md) |
| [ADR-003.md](./ADR-003.md) | D3: Hand-offs | v1 | Accepted | — |
| [ADR-004.md](./ADR-004.md) | D4: State | v1 | Accepted | — |
| [ADR-005.md](./ADR-005.md) | D5: Tools | v2 | Accepted | [`ADR-005_v1.md`](./archive/ADR-005_v1.md) |
| [ADR-006.md](./ADR-006.md) | D6: Models | v4 | Accepted | [`ADR-006_v1.md`](./archive/ADR-006_v1.md) → [`ADR-006_v2.md`](./archive/ADR-006_v2.md) → [`ADR-006_v3.md`](./archive/ADR-006_v3.md) |
| [ADR-007.md](./ADR-007.md) | D7: Checks | v4 | Accepted | [`ADR-007_v1.md`](./archive/ADR-007_v1.md) → [`ADR-007_v2.md`](./archive/ADR-007_v2.md) → [`ADR-007_v3.md`](./archive/ADR-007_v3.md) |
| [ADR-008.md](./ADR-008.md) | D8: Reviewer independence | v2 | Accepted | [`ADR-008_v1.md`](./archive/ADR-008_v1.md) |
| [ADR-009.md](./ADR-009.md) | D9: Safety and failures | v2 | Accepted | [`ADR-009_v1.md`](./archive/ADR-009_v1.md) |
| [ADR-010.md](./ADR-010.md) | D10: Triggers | v1 | Accepted | — |

## Evolution Highlights

1. **Pre-Implementation v1 → v2 (`ADR-002`, `ADR-006`, `ADR-008`):** Migrated off deprecated `gemini-2.5-*` models to Gemini 3.x + GitHub Models (`models: read`) for cross-provider reviewer independence.
2. **Live Model Probe v2 → v3 (`ADR-002`, `ADR-006`):** Live API probing caught `503` on `gemini-3.8-flash` and `429` on `gemini-4-*`; switched escalation to verified `gemini-3.5-flash` → `gemini-3.7-flash` with fallback chain.
3. **Testing Strategy v1 → v2 (`ADR-005`, `ADR-007`):** Adopted **Property-Based Testing (PBT)-first** (`hypothesis`, dev-only, `max_examples=50`, `derandomize=True`) followed by boundary tests and full regression.
4. **Live Run 1 Findings (`44881708823`) → `ADR-006` v4 & `ADR-007` v3:** Run 1 passed Stages 1–4 on Attempt 1, but exposed two fork-specific GitHub Actions behaviors: (a) default `GITHUB_TOKEN` returned empty bodies from `models.github.ai`, resolved by storing a dedicated `GH_MODELS_TOKEN` repository secret + `X-GitHub-Api-Version: 2022-11-28` header; (b) `gh run list` in Stage 5 caught an `action_required` `pull_request` event instead of our passing `workflow_dispatch` CI run (`44881876871`), resolved by filtering explicitly on `--event workflow_dispatch`.
5. **Live Run 2 Findings (`44884332705`) → `ADR-007` v4:** `ReproAgent` generated a syntactically valid PBT file (`py_compile` OK) using an invalid Hypothesis kwarg (`st.recursive(..., max_depth=...)`), causing `pytest` collection error (`rc=2`) across all 3 Coder attempts. Added a deterministic `pytest --collect-only` gate + self-repair in `ReproAgent`, and prevented non-matching `SEARCH/REPLACE` attempts from reverting prior valid edits.
6. **Live Run 3 Findings (`44885745409`) → `ADR-002` v4 & `ADR-009` v2:** `ReproAgent` hit `HealthCheck.filter_too_much` (`st.text().filter(isidentifier)`) while free-tier Gemini showed frequent `503` demand spikes. Added deterministic Hypothesis auto-sanitization (`_harden_hypothesis_settings`) + a symmetric 2-primary / 1-escalated loop for `ReproAgent` (mirroring `CoderAgent`), and formally excluded transient `429`/`503` provider errors from all call/token/retry budgets (`transient_errors_uncounted` in `usage.json`).

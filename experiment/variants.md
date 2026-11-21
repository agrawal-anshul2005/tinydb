# ADR Decision-Experiment Variants (`experiment/variants.md`)

This document specifies the **two real ADR decision experiments** conducted during our evaluation on `agrawal-anshul2005/tinydb` (`edff96a`), comparing each baseline ADR variant against its revised variant on real, linkable GitHub Actions runs.

---

## Experiment 1 — Testing & Control Flow (`ADR-007` D7 & `ADR-002` D2)
**Hypothesis Tested:** *Is single-shot Property-Based Testing (`ReproAgent` gated only by `py_compile`) sufficient, or does PBT-first generation require deterministic Hypothesis AST sanitization, a `pytest --collect-only` + harness-error pre-flight gate, and a symmetric bounded retry loop?*

### Variant Specifications

| Dimension | Variant A (Baseline: `ADR-007` v2 / `ADR-002` v3) | Variant B (Revised: `ADR-007` v4 / `ADR-002` v4) |
|---|---|---|
| **`ReproAgent` validation gate** | `python -m py_compile` only (syntax check). | Static PBT linter + `py_compile` + `pytest --collect-only` + runtime Hypothesis harness-error detector (`FailedHealthCheck`, `InvalidArgument`, `unexpected keyword argument`). |
| **Deterministic auto-fixes** | None. | `_harden_hypothesis_settings()` rewrites `getattr(Query(), x)` → `Query()[x]`, `st.text().filter(isidentifier)` → bounded ASCII alphabet, `max_depth=` → `max_leaves=`, `.get(doc_id)` → `.get(doc_id=doc_id)`, and injects an AST-safe `suppress_health_check=list(HealthCheck)` profile. |
| **`ReproAgent` retry loop** | Single shot (1 attempt). | Symmetric bounded Evaluator-Optimizer loop: 2 attempts on `gemini-3.5-flash-lite` → 1 escalated attempt on `gemini-3.7-flash` (`MAX_REPRO_ATTEMPTS=3`). |
| **Stage 5 CI polling (`ADR-007` v3)** | Unfiltered `gh run list --workflow ci.yml --branch <branch>`. | Explicit `--event workflow_dispatch` filter so bot-PR `pull_request` (`action_required`) runs are never polled. |

### Observed Real Run Comparison

- **Variant A Real Runs:**
  - Issue #1 [Run `44881708823`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44881708823): Stage 5 misread `pull_request` (`action_required`) despite passing `workflow_dispatch` CI `44881876871`.
  - Issue #1 [Run `44884332705`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44884332705): `ReproAgent` passed `py_compile` but called `st.recursive(..., max_depth=...)`, failing `pytest` collection (`rc=2`) across all 3 Coder attempts.
  - Issue #1 [Run `44885745409`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44885745409): 233/234 tests passed, but 1 PBT tripped `HealthCheck.filter_too_much` (`st.text().filter(isidentifier)`).
  - Issue #4 [Run `44896309810`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44896309810): `ReproAgent` called `db.get(doc_id)` positionally (masked pre-fix by `ImportError` on `rename`).
  - **Variant A End-to-End Pass Rate:** **0 / 4 (0%)** despite correct production patches in `tinydb/`.
- **Variant B Real Runs:**
  - Issue #1 [Run `44889647759`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44889647759) (Repro self-repaired in 2 attempts → **PASS**, 3/3 hidden tests).
  - Issue #2 [Run `44893078088`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893078088) (Repro passed Attempt 1 → **PASS**, 3/3 hidden tests).
  - Issue #3 [Run `44895102946`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44895102946) (Repro self-repaired in 3 attempts → **PASS**, 4/4 hidden tests).
  - Issue #4 [Run `44896952319`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44896952319) (Passed all 6 stages on Attempt 1 → **PASS**, 3/3 hidden tests).
  - **Variant B End-to-End Pass Rate:** **4 / 4 (100%)**, **13 / 13 hidden tests passed**.
- **Design Change Made:** Superseded `ADR-002` v3 → v4 and `ADR-007` v2/v3 → v4 (archived under `architecture/decisions/archive/`).

---

## Experiment 2 — Free-Tier Model Allocation & Reviewer Independence (`ADR-006` D6 & `ADR-008` D8)
**Hypothesis Tested:** *Can a single free-tier cloud host (Google AI Studio Gemini 3.x + Gemma 4, without HTTP socket timeouts or cross-provider failover) reliably complete all 6 stages while preserving reviewer model independence?*

### Variant Specifications

| Dimension | Variant A (Baseline: `ADR-006` v5 / `ADR-008` v3) | Variant B (Revised: `ADR-006` v6 / `ADR-008` v4 / `ADR-009` v2) |
|---|---|---|
| **Provider topology** | Single host: Google AI Studio (`gemini-3.x` + `gemma-4-*`); no cross-provider failover. | Multi-provider free tier: Google AI Studio primary + **Groq Free Developer Tier** cross-provider last-resort failover (`GROQ_API_KEY`). |
| **Model pool disjointness** | Overlapping fallback lists (`gemma-4-*` and `gemini-3.x` appeared in both Stage 1–5 and Stage 6 fallbacks). | Mathematically disjoint sets enforced by runtime assertion (`BuilderSet ∩ ReviewerSet == ∅`): Pool A = Gemini 3.x → Groq (`qwen3-32b`/`gpt-oss-20b`/`llama-3.1-8b`); Pool B = Gemma 4 → Groq (`llama-3.3-70b-versatile`/`openai/gpt-oss-120b`). |
| **HTTP timeout & TPM hygiene** | Default `genai.Client()` socket timeout (no explicit limit); full `ARCHITECTURE.md` (~16.5k tokens) sent to Coder. | Hard `60,000 ms` `HttpOptions` timeout on `genai.Client()`; Coder prompt trimmed to Section 3 constraints (`< 16k` TPM); transient `429`/`503` outages explicitly excluded from call/token budgets. |

### Observed Real Run Comparison

- **Variant A Real Runs:**
  - Issue #1 [Run `44889647759`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44889647759): Stage 6 passed (`gemma-4-26b-a4b-it`) after 3 `503` retries.
  - Issue #2 [Run `44891320419`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44891320419): Failed Stage 3 Attempt 3 on `gemma-4-31b-it` `16,000` input-TPM `429`.
  - Issue #2 [Run `44891899530`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44891899530): Stage 6 crashed when all 4 Google AI Studio models returned simultaneous `503 UNAVAILABLE`.
  - Issue #3 [Run `44893738117`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893738117): Stage 6 hung for 10 full minutes on a stalled Gemma socket and was cancelled by `timeout-minutes: 10`.
  - **Variant A Stage 6 Completion Rate:** **1 / 4 (25%)** under live demand spikes.
- **Variant B Real Runs:**
  - Issue #2 [Run `44893078088`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893078088): Stage 6 passed (`gemma-4-31b-it` → `APPROVE`).
  - Issue #3 [Run `44895102946`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44895102946): Gemma 4 hit `503` → 60s timeout/failover triggered cleanly → **Groq `openai/gpt-oss-120b`** completed Stage 6 (`APPROVE`).
  - Issue #4 [Run `44896952319`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44896952319): Gemma 4 hit `503` → failed over cleanly → **Groq `openai/gpt-oss-120b`** completed Stage 6 (`APPROVE`) in 3m 20s total run time!
  - **Variant B Stage 6 Completion Rate:** **4 / 4 (100%)** with provable zero model overlap (`BuilderSet ∩ ReviewerSet = ∅`) and \$0.00 cost.
- **Design Change Made:** Superseded `ADR-006` v5 → v6, `ADR-008` v3 → v4, and `ADR-009` v1 → v2 (archived under `architecture/decisions/archive/`).

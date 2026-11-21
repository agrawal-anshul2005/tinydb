# Evaluation Runs, Pull Requests, and Reviews (`runs.md`)

Repository fork: [`https://github.com/agrawal-anshul2005/tinydb`](https://github.com/agrawal-anshul2005/tinydb) (pinned base commit: `edff96a`).

> All links below point to real, unmerged Pull Requests, live GitHub Actions runs, downloadable stage artifacts, and posted independent reviews on our public fork.

---

## Final Evaluation Runs (All 5 Issues)

| Issue | Type | Actions Run | Pull Request | Dispatched CI (`ci.yml`) | Independent Review (Stage 6) | Hidden Tests | Total Tokens |
|---|---|---|---|---|---|---|---|
| **[#1](https://github.com/agrawal-anshul2005/tinydb/issues/1)** | Bug (`Query.fragment`) | [Run `44889647759`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44889647759) | [PR #8](https://github.com/agrawal-anshul2005/tinydb/pull/8) | [CI `44889975396`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44889975396) ✅ | [PR #8 Review](https://github.com/agrawal-anshul2005/tinydb/pull/8) (`gemma-4-26b-a4b-it` → **APPROVE**) | **3 / 3** ✅ | `69,796` |
| **[#2](https://github.com/agrawal-anshul2005/tinydb/issues/2)** | Bug (`Query.one_of`) | [Run `44893078088`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893078088) | [PR #17](https://github.com/agrawal-anshul2005/tinydb/pull/17) | [CI `44893202098`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893202098) ✅ | [PR #17 Review](https://github.com/agrawal-anshul2005/tinydb/pull/17) (`gemma-4-31b-it` → **APPROVE**) | **3 / 3** ✅ | `63,923` |
| **[#3](https://github.com/agrawal-anshul2005/tinydb/issues/3)** | Feature (`Query.between`) | [Run `44895102946`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44895102946) | [PR #20](https://github.com/agrawal-anshul2005/tinydb/pull/20) | [CI `44895821801`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44895821801) ✅ | [PR #20 Review](https://github.com/agrawal-anshul2005/tinydb/pull/20) (Groq `openai/gpt-oss-120b` → **APPROVE**) | **4 / 4** ✅ | `79,174` |
| **[#4](https://github.com/agrawal-anshul2005/tinydb/issues/4)** | Feature (`operations.rename`) | [Run `44896952319`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44896952319) | [PR #23](https://github.com/agrawal-anshul2005/tinydb/pull/23) | [CI `44897037757`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44897037757) ✅ | [PR #23 Review](https://github.com/agrawal-anshul2005/tinydb/pull/23) (Groq `openai/gpt-oss-120b` → **APPROVE**) | **3 / 3** ✅ | `38,216` |
| **[#5](https://github.com/agrawal-anshul2005/tinydb/issues/5)** | Vague (messy documents) | [Run `44897372948`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44897372948) | None *(halted cleanly at Stage 1)* | N/A | N/A — `spec.md` flagged 2 blocking `[UNRESOLVED]` API questions & posted halt comment on [Issue #5](https://github.com/agrawal-anshul2005/tinydb/issues/5) | N/A *(correct Stage-1 halt)* | `3,153` |

- **Aggregate Across 5 Final Runs:** **31 successful LLM calls · 254,262 total tokens** (`210,533` prompt + `37,872` output), **27 uncounted transient `429`/`503` retries**, **\$0.00 USD total cost**.
- **Implemented PR Hidden Test Score:** **13 / 13 (100%)** across all 4 concrete issues (PRs #8, #17, #20, #23), with **0 regressions** against TinyDB's 228 baseline tests.

---

## Earlier Diagnostic & ADR-Evolution Runs (Real Failure Evidence)

Every architectural revision in [`architecture/decisions/archive/`](../architecture/decisions/archive/) was driven by real failures observed during live runs:

| Issue | Run Link | Observed Failure / Finding | Resulting ADR & Code Fix |
|---|---|---|---|
| #1 | [Run `44881708823`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44881708823) | Stages 1–4 passed on Attempt 1 (opened PR #8), but (a) `models.github.ai` returned empty body with `GITHUB_TOKEN`, and (b) Stage 5 `gh run list` picked up `pull_request` (`action_required`) instead of passing `workflow_dispatch` CI [`44881876871`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44881876871). | `ADR-006` v4, `ADR-007` v3 (`--event workflow_dispatch` filter). |
| #1 | [Run `44884332705`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44884332705) | `ReproAgent` generated syntactically valid PBT file calling `st.recursive(..., max_depth=...)`, failing `pytest` collection (`rc=2`) across all 3 Coder attempts. | `ADR-007` v4 (`pytest --collect-only` gate + self-repair in `ReproAgent`). |
| #1 | [Run `44885745409`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44885745409) | 233/234 tests passed; single failure was `HealthCheck.filter_too_much` from `st.text().filter(isidentifier)`. | `ADR-002` v4 (symmetric `ReproAgent` escalation loop + deterministic AST Hypothesis sanitizer), `ADR-009` v2 (`429`/`503` uncounted). |
| #1 | [Run `44888379411`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44888379411) | Stages 1–5 + CI [`44888636577`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44888636577) passed, but Stage 6 failed because GitHub Models (`models.github.ai`) was retired. | `ADR-006` v5, `ADR-008` v3 (migrated Stages 5–6 to open-weight Gemma 4). |
| #2 | [Run `44891320419`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44891320419) & [Run `44891899530`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44891899530) | Hit `gemma-4-31b-it` `16,000` input-TPM `429` in Attempt 3 and a Google AI Studio-wide `503` wave during Stage 6 (`44891899530`). | `ADR-006` v6 & `ADR-008` v4 (Groq Free Tier cross-provider failover with strictly disjoint Builder vs. Reviewer pools + runtime overlap assertion; trimmed Coder prompt < 16k tokens). |
| #3 | [Run `44893738117`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893738117) | Stages 1–5 + CI [`44893822922`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44893822922) passed, but Stage 6 hung 10 minutes because `genai.Client()` lacked a default HTTP timeout. | Added `HttpOptions(timeout=60000)` (60s) in `llm.py`; subsequent Run `44895102946` failed over cleanly to Groq `openai/gpt-oss-120b` and passed! |
| #4 | [Run `44896309810`](https://github.com/agrawal-anshul2005/tinydb/actions/runs/44896309810) | `ReproAgent` called `db.get(doc_id)` positionally instead of `db.get(doc_id=doc_id)` (masked pre-fix by `ImportError` on `rename`). | Added deterministic `.get(doc_id)` → `.get(doc_id=doc_id)` rule/auto-fix; subsequent Run `44896952319` passed all 6 stages on **Attempt 1**! |

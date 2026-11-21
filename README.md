# AutoSE Assignment 3 — Architecting an Agentic SDLC Workflow on TinyDB

**Student:** Anshul Agrawal (`2025901015`) — IIIT Hyderabad, Automated Software Engineering (AutoSE)  
**Target Fork:** [`https://github.com/agrawal-anshul2005/tinydb`](https://github.com/agrawal-anshul2005/tinydb)  
**Pinned Base Commit:** [`edff96a`](https://github.com/agrawal-anshul2005/tinydb/commit/edff96aeb2616402e9489d46e90a592c05565621) (`msiemens/tinydb` v4.9.0)  
**Report:** [`report.pdf`](./report.pdf) *(editable source: [`report.html`](./report.html))*  
**Demo Video:** [`demo.mp4`](./demo.mp4) *(or link here if hosted externally)*

---

## Overview

This repository implements a 6-stage GitHub Actions Agentic SDLC Workflow ([`.github/workflows/autose.yml`](./.github/workflows/autose.yml)) that converts a GitHub Issue into a tested, independently reviewed Pull Request while **leaving the final merge decision strictly to a human maintainer**.

### Key Architectural Highlights
- **Zero-LLM Deterministic Orchestrator ([`orchestrator.py`](./workflow/agents/orchestrator.py)):** Enforces all 6 fixed stage gates, write allowlists (`tinydb/` and `tests/` only), retry caps, and fail-closed halting with zero LLM routing calls.
- **Property-Based Testing (PBT)-First TDD (`ADR-007` v4):** Stage 3A (`ReproAgent`) writes Hypothesis `@given` property-based invariants + boundary tests, runs an AST-safe Hypothesis sanitizer + `pytest --collect-only` self-repair loop, and confirms pre-fix reproduction before `CoderAgent` applies `SEARCH/REPLACE` patches.
- **Context-Saving Local AST Tools (`ADR-005` v2):** Pure-Python `ast` `repo_map`, `list_directory`, `read_file_lines`, and `search_symbol` keep prompts compact without native Tree-sitter dependencies.
- **Mathematically Disjoint Builder vs. Reviewer Model Pools (`ADR-006` v6, `ADR-008` v4):**
  - **Stages 1–5 (Builder Pool):** Gemini 3.x (`gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`) → Groq Builder Failover (`qwen/qwen3-32b`, `openai/gpt-oss-20b`, `llama-3.1-8b-instant`).
  - **Stage 6 (Independent Reviewer Pool — Isolated Read-Only Job):** Open-weight Gemma 4 (`gemma-4-26b-a4b-it`, `gemma-4-31b-it`) → Groq Reviewer Failover (`llama-3.3-70b-versatile`, `openai/gpt-oss-120b`).
  - `stage6_review.py` asserts `BuilderSet ∩ ReviewerSet == ∅` at runtime, runs in a separate runner with `contents: read` (no push rights), and never downloads Stage 1–5 artifacts or reasoning traces.
- **Hard Free-Tier Budgets (`ADR-009` v2):** \$0.00 cost ceiling (Free-Tier Google AI Studio + Groq Developer Tier), `MAX_TOKENS_PER_RUN=200000`, `MAX_LLM_CALLS_PER_RUN=20`, `timeout-minutes: 15/10`, and `60s` HTTP timeouts, with transient `429`/`503` outages explicitly excluded from call/retry budgets.

---

## How to Trigger the Workflow

1. **Secrets required (Repository Settings → Secrets and variables → Actions):**
   - `GEMINI_API_KEY` — Google AI Studio Free-Tier API key
   - `GROQ_API_KEY` — Groq Free Developer Tier API key (cross-provider failover)
2. **Trigger on any open issue in this fork** (authorized `OWNER`/`MEMBER`/`COLLABORATOR` only):
   - **Option A (Label trigger):** Add the label `autose` (`gh issue edit <N> --add-label autose`).
   - **Option B (Comment trigger):** Post a comment starting with `/autose` (in Git Bash on Windows: `MSYS_NO_PATHCONV=1 gh issue comment <N> --body "/autose"`).
3. **Inspect the run:** Every stage uploads its artifacts (`spec.md`, `design.md`, `context.json`, `status.md`, `diff.patch`, `test_report.md`, `pr.md`, `usage.json`, `review.md`, `review_usage.json`) to the GitHub Actions run page, opens a PR against `main`, runs `ci.yml`, posts the independent review, and stops for human merge/close.

---

## Summary of Results & Token Usage

- **Issues #1–#4 (2 bugs + 2 features):** **4 / 4** passed all 6 stages, passed real `ci.yml`, received independent Round-1 `APPROVE` (2 by Gemma 4, 2 via cross-provider Groq `openai/gpt-oss-120b` failover), and scored **13 / 13 (100%)** on hidden acceptance tests with **0 regressions**.
- **Issue #5 (Vague issue):** Correctly **halted at Stage 1** by `RequirementsAgent` + A1 `skill.md`, flagging 2 blocking `[UNRESOLVED]` public-API questions in `spec.md` instead of hallucinating breaking changes.
- **Total Tokens Used (5 Final Evaluation Runs):** **254,262 total tokens** (`210,533` prompt + `37,872` output across 31 successful calls; **\$0.00 total spend**). Full links and metrics are in [`results/results.csv`](./results/results.csv) and [`results/runs.md`](./results/runs.md).

---

## Repository Layout

```text
README.md                       # This file
ARCHITECTURE.md                 # TinyDB (edff96a) architecture doc used by Stage 2
report.pdf                      # Final report (<= 8 pages)
report.html                     # Editable HTML/SVG source for report.pdf
demo.mp4                        # <= 5-minute end-to-end demo video
architecture/
  views/                        # component-view.md, sequence-view.md, stage-map.md
  decisions/                    # ADR-001.md .. ADR-010.md + README.md + archive/ (versioned superseded ADRs)
workflow/
  github-workflows/             # Mirror of .github/workflows/ (autose.yml, ci.yml)
  agents/                       # orchestrator.py, llm.py, tools.py, stage1..stage6
  prompts/skill.md              # Reusable A1 Requirements Specification Skill
  requirements.txt
experiment/
  issues/                       # Exact texts of Issues #1-#5
  hidden_tests/                 # Hidden pytest suites (kept outside repo during all runs)
  seeded_prs/                   # 5 reviewer-check PR diffs + ground-truth labels + eval harness
  variants.md                   # Specifications & real-run results of our 2 ADR decision experiments
results/
  results.csv                   # Structured per-issue metrics & token counts
  runs.md                       # Direct links to every real Actions run, PR, CI run, and review
```

---

## AI Assistance Disclosure

Per the IIIT Hyderabad AutoSE course policy:
- **Antigravity (AI coding assistant)** was used to assist in scaffolding the Python workflow modules (`workflow/agents/*.py`), GitHub Actions YAML (`.github/workflows/*.yml`), hidden test templates, and HTML/PDF report formatting.
- All generated code, workflow YAML, and test outputs were reviewed, executed live on GitHub Actions, and iteratively debugged by the student.
- Core architectural choices — including the PBT-first Hypothesis testing strategy (`ADR-005` v2, `ADR-007` v2–v4), symmetric `ReproAgent`/`CoderAgent` escalation loops (`ADR-002` v4), excluding transient `429`/`503` outages from budgets (`ADR-009` v2), cross-provider Groq failover (`ADR-006` v6), strictly disjoint Builder vs. Reviewer model pools (`ADR-008` v4), and archive-based ADR evolution tracking — were directed and reasoned through by the student based on live empirical observations.

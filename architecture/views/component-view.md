# Component View — Agentic SDLC Workflow

## High-Level Architecture

The workflow runs on GitHub Actions (`.github/workflows/autose.yml`) and is split across **two isolated GitHub Actions jobs** per review round to enforce least-privilege security and strict cross-family reviewer independence:

1. **Builder Pipeline Job (`round1_build` / `round2_build`)** — Runs Stages 1–5 via a **zero-LLM deterministic Python orchestrator** (`workflow/agents/orchestrator.py`) with permissions `contents: write`, `pull-requests: write`, `issues: write`, `actions: write`. Stages 1–4 use **Gemini 3.x** (`gemini-3.5-flash-lite` primary → `gemini-3.7-flash` escalation, with `429`/`503` uncounted fallback); Stage 5 offloads PR summarization to open-weight **Gemma 4** (`gemma-4-31b-it`).
2. **Independent Review Job (`round1_review` / `round2_review`)** — Runs Stage 6 in a **fresh GitHub Actions runner container** with **read-only code permissions** (`contents: read`, `pull-requests: write`, `issues: read` — **cannot push**), a fresh checkout of PR HEAD, zero access to Stage 1–5 traces, and a distinct open-weight model family (**Gemma 4 `gemma-4-31b-it`**, fallback `gemma-4-26b-a4b-it`).

```mermaid
flowchart TB
    Trigger["GitHub Event<br/>issues:labeled ('autose') OR<br/>issue_comment:created ('/autose')<br/>+ Authorized Actor Guard + Concurrency Group"]

    subgraph Job1["Job 1: Builder Pipeline (contents: write, pull-requests: write, issues: write, actions: write)"]
        Orch["Deterministic Python Orchestrator (orchestrator.py — NO LLM)<br/>Enforces stage gates, token/call budgets (429/503 uncounted), retry caps"]
        S1["Stage 1: RequirementsAgent<br/>(Gemini: gemini-3.5-flash-lite + skill.md)"]
        S2["Stage 2: ExplorerDesignAgent<br/>(Gemini: gemini-3.5-flash-lite + ARCHITECTURE.md)"]
        Tools["Context-Saving Repo Tools (tools.py)<br/>list_dir | ast repo_map | read_file_lines | search_symbol"]
        S3["Stage 3: ReproAgent (PBT-First TDD) + CoderAgent<br/>(Symmetric 2x flash-lite -> 1x 3.7-flash escalation, SEARCH/REPLACE)"]
        S4["Stage 4: Evaluator / Testing Loop<br/>(Hypothesis PBT invariants + boundary tests + full regression suite)"]
        S5["Stage 5: DeliveryAgent<br/>(Gemma 4: gemma-4-31b-it structured PR + gh pr create + workflow_dispatch CI)"]

        Orch --> S1
        S1 -->|"spec.md (gate: testable ACs)"| S2
        S2 <--> Tools
        S2 -->|"design.md + context.json (gate: files & funcs named)"| S3
        S3 <--> Tools
        S3 -->|"diff.patch + status.md (gate: compileall builds)"| S4
        S4 -->|"fail: stderr trace (<=2 flash-lite + 1 3.7-flash)"| S3
        S4 -->|"test_report.md (gate: all tests pass)"| S5
    end

    CI["ci.yml (workflow_dispatch / pull_request)<br/>Runs full pytest + Hypothesis suite"]

    subgraph Job2["Job 2: Independent Review (contents: read, pull-requests: write — NO PUSH)"]
        S6["Stage 6: ReviewerAgent (Open-Weight Gemma 4: gemma-4-31b-it)<br/>Fresh container + fresh PR HEAD checkout<br/>Inputs: ONLY Issue + PR Diff + Repo<br/>Can run pytest locally (read-only)"]
    end

    Human["Human Maintainer<br/>Final Merge or Close Decision<br/>(Workflow NEVER merges)"]

    Trigger --> Orch
    S5 -->|"opens/updates PR + pr.md"| CI
    CI -->|"CI green"| Job2
    S6 -->|"APPROVE or 2 rounds exhausted<br/>+ review.md"| Human
    S6 -.->|"FIX_DESIGN (Stage 2) or FIX_CODE (Stage 3)<br/>(max 2 review rounds)"| Orch
```

---

## Component Responsibilities & Boundaries

| Component | File(s) | Model / Provider & Permissions | Outputs |
|---|---|---|---|
| **Orchestrator** | `workflow/agents/orchestrator.py` | **Deterministic Python (No LLM)**; enforces gates, caps, path allowlist | Stage routing & exit codes |
| **LLM Gateway** | `workflow/agents/llm.py` | `google-genai` (`GEMINI_API_KEY`); pacing, 429/503 uncounted backoff + fallback chains, token & call caps | `usage.json` |
| **Repo Context Tools** | `workflow/agents/tools.py` | Read-only Python `ast` `repo_map`, `list_dir`, `read_file_lines`, `search_symbol` + `SEARCH/REPLACE` patcher | Minimal slices (prevents context bloat) |
| **Stage 1: RequirementsAgent** | `workflow/agents/stage1_requirements.py` | Gemini `gemini-3.5-flash-lite`; reads sanitized issue JSON + `skill.md` | `spec.md` |
| **Stage 2: ExplorerDesignAgent** | `workflow/agents/stage2_design.py` | Gemini `gemini-3.5-flash-lite`; reads `spec.md`, `ARCHITECTURE.md`, `tools.py` | `design.md`, `context.json` |
| **Stage 3: Repro + CoderAgent** | `workflow/agents/stage3_implement.py` | Symmetric loop: `gemini-3.5-flash-lite` (×2) → `gemini-3.7-flash` (×1); PBT-first repro + `SEARCH/REPLACE` on `autose/issue-<N>` | `diff.patch`, `status.md` |
| **Stage 4: Evaluator / Testing** | `workflow/agents/stage4_test.py` | Deterministic `pytest` + `hypothesis` (PBT-first invariants + boundary tests + regression) & feedback loop to CoderAgent | `test_report.md` |
| **Stage 5: DeliveryAgent** | `workflow/agents/stage5_release.py` | Open-weight Gemma 4 `gemma-4-31b-it` + `git`/`gh` (`--event workflow_dispatch` CI verification) | `pr.md`, PR link |
| **Stage 6: ReviewerAgent** | `workflow/agents/stage6_review.py` | **Isolated Job 2:** Open-weight Gemma 4 `gemma-4-31b-it` (`contents: read`, NO push); sees ONLY Issue + PR diff + repo | `review.md`, verdict |

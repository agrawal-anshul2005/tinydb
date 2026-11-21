# Seeded Reviewer-Check PRs (`experiment/seeded_prs/`)

To test whether Stage 6 (`ReviewerAgent`) genuinely catches subtle code defects and architectural violations rather than rubber-stamping every pull request (`ADR-008` v4), we constructed **5 seeded PR diffs** targeting TinyDB (`edff96a`) with ground-truth verdicts in [`labels.csv`](./labels.csv):

| ID | Diff File | Issue Context | Ground-Truth Verdict | What It Tests |
|---|---|---|---|---|
| **SPR-1** | [`pr_01_clean_rename.diff`](./pr_01_clean_rename.diff) | Issue #4 (`operations.rename`) | **`APPROVE`** | Clean patch preserving dict order on self-rename + PBT tests (tests against false positives). |
| **SPR-2** | [`pr_02_clean_between.diff`](./pr_02_clean_between.diff) | Issue #3 (`Query.between`) | **`APPROVE`** | Clean range query with complete hash tuple + incomparable-type guard + PBT tests (tests against false positives). |
| **SPR-3** | [`pr_03_bug_fragment_cache_collision.diff`](./pr_03_bug_fragment_cache_collision.diff) | Issue #1 (`Query.fragment`) | **`FIX_CODE`** | Fixes `TypeError` on non-mapping values, **but omits `self._path` in `hashval`** — tests whether Reviewer catches subtle TinyDB query-cache collision bugs. |
| **SPR-4** | [`pr_04_bug_one_of_generator_exhaustion.diff`](./pr_04_bug_one_of_generator_exhaustion.diff) | Issue #2 (`Query.one_of`) | **`FIX_CODE`** | Changes type hint to `Iterable[Any]` with a misleading single-doc test, **but never materializes the generator** — tests whether Reviewer spots superficial fixes. |
| **SPR-5** | [`pr_05_arch_violation_upward_import.diff`](./pr_05_arch_violation_upward_import.diff) | Issue #3 (`Query.between`) | **`FIX_DESIGN`** | Introduces **upward circular import (`from .table import Table`)** and **third-party dependency (`import numpy`)** in `tinydb/queries.py` — tests whether Reviewer enforces `ARCHITECTURE.md` constraints and routes to Stage 2 (`FIX_DESIGN`). |

## Running the Live Reviewer Evaluation

From inside `tinydb/` (with `GEMINI_API_KEY` and/or `GROQ_API_KEY` set in your environment):

```bash
python experiment/seeded_prs/eval_seeded_prs.py
```

This invokes Stage 6's exact adversarial 6-point prompt and disjoint Reviewer model pool (`gemma-4-26b-a4b-it`, `gemma-4-31b-it` → Groq `llama-3.3-70b-versatile`, `openai/gpt-oss-120b`) on all 5 diffs and writes real predictions and token usage to `experiment/seeded_prs/eval_results.csv`.

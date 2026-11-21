"""Stage 3: ReproAgent (PBT-first TDD) + CoderAgent (SEARCH/REPLACE + Flash->3.7 escalation)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .llm import LLMGateway, get_model_chain
from .tools import (
    apply_search_replace_blocks,
    read_file_lines,
    run_cmd,
    validate_allowed_path,
)


def record_baseline_status(repo_root: Path, artifacts_dir: Path) -> tuple[bool, str]:
    """Run existing TinyDB test suite before edits and record baseline in status.md."""
    proc = run_cmd([sys.executable, "-m", "pytest", "-o", "addopts=", "-q"], cwd=repo_root, timeout=60)
    summary_line = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    status_md = (
        "# Baseline Test & Regression Status (`status.md`)\n\n"
        f"- **Baseline Exit Code:** `{proc.returncode}`\n"
        f"- **Baseline Summary:** `{summary_line}`\n\n"
        "```\n"
        f"{proc.stdout[-2500:]}\n"
        "```\n"
    )
    (artifacts_dir / "status.md").write_text(status_md, encoding="utf-8")
    return proc.returncode == 0, summary_line


def _extract_python_code(text: str) -> str:
    m = re.search(r"```python\r?\n(.*?)\r?\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip() + "\n"
    m2 = re.search(r"```\r?\n(.*?)\r?\n```", text, re.DOTALL)
    if m2:
        return m2.group(1).strip() + "\n"
    return text.strip() + "\n"


def run_repro_agent(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    issue_number: int,
    spec_text: str,
    design_text: str,
    target_files: list[str],
) -> tuple[bool, Path, str]:
    """Generate PBT-first (Hypothesis) + boundary pytest tests before coding (ADR-007 v2)."""
    test_rel = f"tests/test_issue_{issue_number}_pbt.py"
    test_path = validate_allowed_path(repo_root, test_rel)

    target_excerpts = "\n\n".join(
        f"### {f}\n```python\n{read_file_lines(repo_root, f, 1, 600)}\n```"
        for f in target_files[:3]
    )

    system_prompt = (
        "You are ReproAgent (QA / PBT-First TDD Agent) for TinyDB.\n"
        "Write a clean, self-contained pytest module using **Property-Based Testing (`hypothesis`)** "
        "as the PRIMARY testing strategy, followed by targeted example-based boundary tests.\n\n"
        "STRICT RULES:\n"
        "1. Import `from hypothesis import given, settings, strategies as st`.\n"
        "2. Decorate EVERY Hypothesis test with `@settings(max_examples=50, derandomize=True, deadline=None)`.\n"
        "3. Use `TinyDB(storage=MemoryStorage)` so tests never create temporary files on disk.\n"
        "4. Use simple, reliable strategies (`st.integers`, `st.floats(allow_nan=False, allow_infinity=False)`, "
        "`st.text`, `st.booleans`, `st.none`, `st.lists`, `st.dictionaries`, `st.one_of`). "
        "NEVER pass `max_depth` to `st.recursive` (avoid `st.recursive` altogether).\n"
        "5. If testing a brand-new function or symbol that does not yet exist in `tinydb/` (e.g., `from tinydb.operations import rename`), "
        "import it INSIDE each test function rather than at module top-level so `pytest --collect-only` succeeds cleanly.\n"
        "6. Cover EVERY Acceptance Criterion (`AC-*`) in `spec.md` with at least one PBT invariant or boundary test.\n"
        "7. Output ONLY a single ```python ... ``` code block containing the complete test file."
    )

    user_prompt = (
        f"Create `{test_rel}` for Issue #{issue_number}.\n\n"
        f"## spec.md\n{spec_text}\n\n"
        f"## design.md\n{design_text}\n\n"
        f"## Current Target Code\n{target_excerpts}"
    )

    models = get_model_chain("GEMINI_CODER_PRIMARY_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite,gemma-4-31b-it")
    raw = llm.call_gemini(
        stage="stage3_repro_pbt",
        models=models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
    )
    code = _extract_python_code(raw)
    test_path.write_text(code, encoding="utf-8")

    # Deterministic collection gate: syntax + pytest --collect-only (catches invalid Hypothesis kwargs like max_depth)
    for repair_try in range(2):
        comp = run_cmd([sys.executable, "-m", "py_compile", str(test_path)], cwd=repo_root, timeout=30)
        collect = (
            run_cmd([sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", str(test_rel)], cwd=repo_root, timeout=30)
            if comp.returncode == 0
            else comp
        )
        if comp.returncode == 0 and collect.returncode == 0:
            break
        err_trace = (collect.stdout + "\n" + collect.stderr)[-2000:]
        if repair_try == 1:
            return False, test_path, f"ReproAgent test failed pytest collection after self-repair:\n{err_trace}"
        print(f"[stage3_repro] Collection failed (rc={collect.returncode}); running 1 self-repair call...")
        repair_prompt = (
            f"The pytest file `{test_rel}` failed syntax/collection with this error:\n```\n{err_trace}\n```\n\n"
            f"Current file:\n```python\n{code}\n```\n\n"
            "Fix the collection/Hypothesis API error (keep all PBT `@given` tests and boundary tests) "
            "and return ONLY the complete corrected ```python ... ``` code block."
        )
        raw = llm.call_gemini(
            stage="stage3_repro_pbt_repair",
            models=models,
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            temperature=0.1,
        )
        code = _extract_python_code(raw)
        test_path.write_text(code, encoding="utf-8")

    has_pbt = "@given" in code and "hypothesis" in code
    repro_run = run_cmd([sys.executable, "-m", "pytest", "-o", "addopts=", str(test_rel), "-v"], cwd=repo_root, timeout=60)
    note = (
        f"\n## Pre-Implementation TDD / Repro Check (`{test_rel}`)\n"
        f"- **Hypothesis PBT Present:** `{has_pbt}`\n"
        f"- **Pytest Collection Gate:** `PASS`\n"
        f"- **Pre-Fix Exit Code:** `{repro_run.returncode}` (1 confirms bug/feature fails before patch)\n\n"
        f"```\n{(repro_run.stdout + repro_run.stderr)[-2000:]}\n```\n"
    )
    status_path = artifacts_dir / "status.md"
    status_path.write_text(status_path.read_text(encoding="utf-8") + note, encoding="utf-8")
    return True, test_path, f"Created {test_rel} (PBT={has_pbt}, collect=OK, pre-fix rc={repro_run.returncode})"


def run_coder_attempt(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    attempt: int,
    spec_text: str,
    design_text: str,
    target_files: list[str],
    test_rel: str,
    error_feedback: str | None = None,
    review_feedback: str | None = None,
) -> tuple[bool, str, str]:
    """Run one CoderAgent SEARCH/REPLACE attempt.

    Attempts 1-2 use primary model (gemini-3.5-flash); attempt 3 escalates to gemini-3.7-flash.
    Returns (build_passed, message, model_tier).
    """
    is_escalated = attempt >= 3
    tier = "escalated" if is_escalated else "primary"
    models = (
        get_model_chain("GEMINI_CODER_ESCALATION_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemma-4-31b-it")
        if is_escalated
        else get_model_chain("GEMINI_CODER_PRIMARY_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite,gemma-4-31b-it")
    )

    files_to_show = list(dict.fromkeys(target_files + [test_rel]))
    code_sections = []
    for rel in files_to_show:
        p = repo_root / rel
        if p.exists():
            # Provide exact raw content (no line number prefixes!) so SEARCH blocks match verbatim
            raw_content = p.read_text(encoding="utf-8")
            code_sections.append(f"### FILE: {rel}\n```python\n{raw_content}\n```")

    arch_text = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")

    system_prompt = (
        "You are Stage 3 (CoderAgent) for TinyDB (Python >=3.10, ZERO third-party runtime dependencies in tinydb/).\n"
        "You MUST output edits strictly as exact SEARCH/REPLACE blocks — NEVER rewrite entire files unless creating a test.\n\n"
        "EXACT OUTPUT FORMAT (repeat for each edit):\n"
        "FILE: tinydb/queries.py\n"
        "<<<<<<< SEARCH\n"
        "<exact verbatim existing lines from the file, including indentation>\n"
        "=======\n"
        "<replacement lines>\n"
        ">>>>>>> REPLACE\n\n"
        "RULES:\n"
        "1. Only edit files under `tinydb/` or `tests/`.\n"
        "2. Copy SEARCH lines character-for-character from the file contents provided below.\n"
        "3. Include enough surrounding context lines (3-6 lines) so each SEARCH block is unique.\n"
        "4. Respect all TinyDB architectural constraints (stdlib only in tinydb/, sound Query hashvals, no upward imports).\n"
        "5. If a newly generated test in `tests/test_issue_*_pbt.py` has a buggy Hypothesis strategy (e.g., invalid test assumption), "
        "you may fix that test file ONLY if the test itself contradicts `spec.md`; never delete or weaken real acceptance tests."
    )

    feedback_block = ""
    if review_feedback:
        feedback_block += f"\n\n## Independent Reviewer Feedback (Round 2)\n{review_feedback}\n"
    if error_feedback:
        feedback_block += f"\n\n## Previous Attempt Failure Trace (Attempt {attempt - 1})\n```\n{error_feedback[-3500:]}\n```\n"

    user_prompt = (
        f"Implement the fix/feature for this issue (Attempt {attempt}, tier={tier}).\n\n"
        f"## spec.md\n{spec_text}\n\n"
        f"## design.md\n{design_text}\n\n"
        f"## ARCHITECTURE.md Constraints\n{arch_text}\n\n"
        f"## Current File Contents (copy SEARCH blocks verbatim)\n"
        + "\n\n".join(code_sections)
        + feedback_block
    )

    llm_out = llm.call_gemini(
        stage=f"stage3_coder_attempt_{attempt}_{tier}",
        models=models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )

    modified, errors = apply_search_replace_blocks(repo_root, llm_out)
    if errors:
        err_msg = "SEARCH/REPLACE patch failed:\n" + "\n".join(errors)
        (artifacts_dir / "diff.patch").write_text(f"# Stage 3 Patch Error (Attempt {attempt})\n{err_msg}\n", encoding="utf-8")
        return False, err_msg, tier

    # Deterministic Stage 3 Build Gate: compileall + import tinydb + non-empty diff
    comp = run_cmd([sys.executable, "-m", "compileall", "-q", "tinydb"], cwd=repo_root, timeout=30)
    if comp.returncode != 0:
        err_msg = f"compileall failed:\n{comp.stdout}\n{comp.stderr}"
        (artifacts_dir / "diff.patch").write_text(f"# Stage 3 Build Error\n{err_msg}\n", encoding="utf-8")
        return False, err_msg, tier

    imp = run_cmd(
        [sys.executable, "-c", "import tinydb; from tinydb import TinyDB, Query, where; import tinydb.operations"],
        cwd=repo_root,
        timeout=30,
    )
    if imp.returncode != 0:
        err_msg = f"Import check failed:\n{imp.stderr}"
        (artifacts_dir / "diff.patch").write_text(f"# Stage 3 Import Error\n{err_msg}\n", encoding="utf-8")
        return False, err_msg, tier

    # Include untracked new PBT test file in diff.patch via intent-to-add
    run_cmd(["git", "add", "-N", "--", test_rel], cwd=repo_root, timeout=15)
    diff_proc = run_cmd(["git", "diff", "--", "tinydb", "tests"], cwd=repo_root, timeout=30)
    diff_text = diff_proc.stdout
    if not diff_text.strip():
        return False, "git diff produced no changes under tinydb/ or tests/.", tier

    (artifacts_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    return True, f"Applied SEARCH/REPLACE to {modified}; compileall & import checks passed.", tier

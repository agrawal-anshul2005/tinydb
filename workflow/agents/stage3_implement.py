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

# Patterns that reliably cause Hypothesis/TinyDB test-harness bugs rather than real SUT bugs
_FORBIDDEN_TEST_PATTERNS: list[tuple[str, str]] = [
    (r"\bmax_depth\s*=", "st.recursive() does not accept `max_depth` (avoid st.recursive altogether)."),
    (r"st\.text\([^)]*\)\.filter\([^)]*isidentifier", "Do not use st.text().filter(isidentifier); use st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8)."),
    (r"getattr\(\s*Query\(\)", "Do not use getattr(Query(), field) because field names can collide with Query methods like 'test'/'any'/'all'; use Query()[field] instead."),
    (r"def\s+test_[^(]*\(\s*(?:tmp_path|tmpdir)\b", "Do not pass pytest fixtures like tmp_path into @given tests; instantiate TinyDB(storage=MemoryStorage) inside the test body."),
]

_HARNESS_ERROR_MARKERS = (
    "hypothesis.errors.FailedHealthCheck",
    "hypothesis.errors.InvalidArgument",
    "hypothesis.errors.Unsatisfiable",
    "FailedHealthCheck",
    "unexpected keyword argument",
    "NoSuchExample",
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


def _replace_settings_decorators(code: str, replacement: str) -> str:
    """Replace @settings(...) decorators safely even when arguments contain nested parentheses."""
    out: list[str] = []
    i = 0
    n = len(code)
    marker = "@settings("
    while i < n:
        idx = code.find(marker, i)
        if idx == -1:
            out.append(code[i:])
            break
        out.append(code[i:idx])
        depth = 0
        j = idx + len("@settings")
        while j < n:
            ch = code[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        out.append(replacement)
        i = j
    return "".join(out)


def _harden_hypothesis_settings(code: str) -> str:
    """Deterministically fix common Hypothesis/TinyDB pitfalls before running pytest.

    Auto-fixes that are 100% deterministic:
    - Replace `getattr(Query(), expr)` with `Query()[expr]` (avoids method name collisions).
    - Replace `st.text(...).filter(lambda s: s.isidentifier())` with bounded ASCII alphabet strategy.
    - Replace `st.recursive(..., max_depth=N)` with `max_leaves=N`.
    - Inject deterministic `autose_pbt` profile + normalize `@settings(...)` with `suppress_health_check=list(HealthCheck)`.
    """
    # Deterministic auto-fixes (applied even before invoking any LLM retry!)
    code = re.sub(r"getattr\(\s*Query\(\)\s*,\s*([^)]+)\)", r"Query()[\1]", code)
    code = re.sub(
        r"st\.text\([^)]*\)\.filter\(\s*lambda\s+[a-zA-Z_]\w*\s*:\s*[a-zA-Z_]\w*\.isidentifier\(\)\s*\)",
        "st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8)",
        code,
    )
    code = re.sub(r"\bmax_depth\s*=", "max_leaves=", code)

    if "hypothesis" not in code or "@given" not in code:
        return code

    profile_snippet = (
        "\nfrom hypothesis import HealthCheck as _AutoSEHealthCheck, settings as _autose_settings\n"
        "_autose_settings.register_profile(\n"
        "    'autose_pbt',\n"
        "    max_examples=50,\n"
        "    derandomize=True,\n"
        "    deadline=None,\n"
        "    suppress_health_check=list(_AutoSEHealthCheck),\n"
        ")\n"
        "_autose_settings.load_profile('autose_pbt')\n"
    )

    lines = code.splitlines()
    insert_at = 0
    try:
        import ast as _ast
        tree = _ast.parse(code)
        for node in tree.body:
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                insert_at = max(insert_at, node.end_lineno or node.lineno)
            elif (
                isinstance(node, _ast.Expr)
                and isinstance(node.value, _ast.Constant)
                and isinstance(node.value.value, str)
                and insert_at == 0
            ):
                # Module docstring before imports
                insert_at = node.end_lineno or node.lineno
            else:
                break
    except SyntaxError:
        insert_at = 0

    combined = "\n".join(lines[:insert_at]) + profile_snippet + "\n" + "\n".join(lines[insert_at:])
    normalized = _replace_settings_decorators(
        combined,
        "@_autose_settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(_AutoSEHealthCheck))",
    )
    return normalized.strip() + "\n"


def _lint_generated_pbt(code: str) -> list[str]:
    """Static check for known LLM + Hypothesis + TinyDB test-harness pitfalls."""
    issues: list[str] = []
    for pattern, reason in _FORBIDDEN_TEST_PATTERNS:
        if re.search(pattern, code):
            issues.append(reason)
    if "@given" not in code or "hypothesis" not in code:
        issues.append("Missing Hypothesis @given property-based tests (required by ADR-007).")
    return issues


def run_repro_agent(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    issue_number: int,
    spec_text: str,
    design_text: str,
    target_files: list[str],
) -> tuple[bool, Path, str]:
    """Generate PBT-first (Hypothesis) + boundary pytest tests with deterministic hygiene & self-repair."""
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
        "STRICT HYPOTHESIS & TINYDB SAFETY RULES (MUST OBEY EVERY ONE):\n"
        "1. Import `from hypothesis import given, settings, HealthCheck, strategies as st`.\n"
        "2. Decorate EVERY `@given` test with `@settings(max_examples=50, derandomize=True, deadline=None, suppress_health_check=list(HealthCheck))`.\n"
        "3. NEVER use pytest fixtures (like `tmp_path`) in `@given` tests; always create a fresh `TinyDB(storage=MemoryStorage)` INSIDE the test body.\n"
        "4. Generate field/key names ONLY with `st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=1, max_size=8)` — "
        "NEVER use `.filter(lambda s: s.isidentifier())` or `st.characters(whitelist_categories=...)`.\n"
        "5. ALWAYS index dynamic field names via `Query()[field_name]` — NEVER `getattr(Query(), field_name)` "
        "(dynamic names can collide with Query methods like `test`, `any`, `all`, `search`, `map`).\n"
        "6. Avoid `st.recursive(...)` completely (never pass `max_depth=`). Use flat strategies: "
        "`st.integers(min_value=-1000, max_value=1000)`, `st.floats(allow_nan=False, allow_infinity=False)`, "
        "`st.text(alphabet='abcdef012345', max_size=12)`, `st.booleans()`, `st.none()`, `st.lists(..., max_size=8)`, `st.dictionaries(..., max_size=5)`.\n"
        "7. NEVER pass `unique=True` to `st.lists(...)` when elements are dicts/lists (unhashable).\n"
        "8. Watch out for Python `True == 1` / `False == 0`: do NOT mix `st.booleans()` and `st.integers()` in the same equality/membership assertion.\n"
        "9. For range bounds `(low, high)`, generate two integers `a, b` and compute `low, high = min(a, b), max(a, b)` instead of `assume(a < b)`.\n"
        "10. For generator tests, pass `st.lists(...)` into `@given` and construct the generator `(x for x in items)` INSIDE the test body (never in the decorator!).\n"
        "11. If testing a brand-new function/symbol that does not exist yet (e.g., `from tinydb.operations import rename`), "
        "import it INSIDE each test function rather than at module top-level so `pytest --collect-only` succeeds.\n"
        "12. Cover EVERY Acceptance Criterion (`AC-*`) in `spec.md` with PBT invariants + boundary tests.\n"
        "13. Output ONLY a single ```python ... ``` code block containing the complete test file."
    )

    user_prompt = (
        f"Create `{test_rel}` for Issue #{issue_number}.\n\n"
        f"## spec.md\n{spec_text}\n\n"
        f"## design.md\n{design_text}\n\n"
        f"## Current Target Code\n{target_excerpts}"
    )

    import os

    max_repro_attempts = int(os.environ.get("MAX_REPRO_ATTEMPTS", "3"))  # 2 primary + 1 escalated
    primary_models = get_model_chain("GEMINI_CODER_PRIMARY_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite,gemma-4-31b-it")
    escalated_models = get_model_chain("GEMINI_CODER_ESCALATION_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemma-4-31b-it")

    repro_history: list[str] = []
    code = ""
    harness_err = ""
    repro_run = None

    # Symmetric Evaluator-Optimizer loop for ReproAgent (ADR-002 v4):
    # Attempts 1-2 use primary model; Attempt 3 escalates to gemini-3.7-flash.
    for attempt in range(1, max_repro_attempts + 1):
        is_escalated = attempt >= 3
        tier = "escalated" if is_escalated else "primary"
        models = escalated_models if is_escalated else primary_models

        if attempt == 1:
            prompt = user_prompt
            stage_label = "stage3_repro_pbt_attempt_1_primary"
        else:
            prompt = (
                f"ReproAgent Attempt {attempt}/{max_repro_attempts} (tier={tier}): "
                f"The generated PBT file `{test_rel}` failed pre-flight validation even after deterministic sanitization:\n"
                f"```\n{harness_err}\n```\n\n"
                f"Previous file:\n```python\n{code}\n```\n\n"
                "Fix the Hypothesis strategy/collection/harness issue while preserving all PBT `@given` invariants "
                "and AC boundary tests. Return ONLY the complete corrected ```python ... ``` code block."
            )
            stage_label = f"stage3_repro_pbt_attempt_{attempt}_{tier}"

        raw = llm.call_gemini(
            stage=stage_label,
            models=models,
            system_prompt=system_prompt,
            user_prompt=prompt,
            temperature=0.15 if attempt == 1 else 0.1,
        )
        # Apply deterministic auto-corrections first
        code = _harden_hypothesis_settings(_extract_python_code(raw))
        test_path.write_text(code, encoding="utf-8")

        lint_errors = _lint_generated_pbt(code)
        comp = run_cmd([sys.executable, "-m", "py_compile", str(test_path)], cwd=repo_root, timeout=30)
        collect = (
            run_cmd([sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", str(test_rel)], cwd=repo_root, timeout=30)
            if comp.returncode == 0
            else comp
        )

        harness_err = ""
        if lint_errors:
            harness_err = "Static PBT lint errors:\n- " + "\n- ".join(lint_errors)
        elif comp.returncode != 0:
            harness_err = f"Syntax error:\n{comp.stderr}"
        elif collect.returncode != 0:
            harness_err = f"pytest --collect-only failed (rc={collect.returncode}):\n{(collect.stdout + collect.stderr)[-2000:]}"
        else:
            repro_run = run_cmd([sys.executable, "-m", "pytest", "-o", "addopts=", str(test_rel), "-v", "--tb=short"], cwd=repo_root, timeout=60)
            combined = repro_run.stdout + "\n" + repro_run.stderr
            if any(marker in combined for marker in _HARNESS_ERROR_MARKERS):
                harness_err = f"Hypothesis test-harness error detected during pre-fix run:\n{combined[-2000:]}"

        if not harness_err:
            repro_history.append(f"| {attempt} | {tier} | PASS | collect=OK, pre-fix rc={repro_run.returncode} |")
            break

        repro_history.append(f"| {attempt} | {tier} | FAIL | {harness_err.splitlines()[0][:100]} |")
        print(f"[stage3_repro] Attempt {attempt}/{max_repro_attempts} ({tier}) failed pre-flight PBT check; looping...")

    if harness_err or repro_run is None:
        return False, test_path, f"ReproAgent failed pre-flight validation after {max_repro_attempts} attempts:\n{harness_err}"

    has_pbt = "@given" in code and "hypothesis" in code
    history_table = "\n".join(repro_history)
    note = (
        f"\n## Pre-Implementation TDD / Repro Check (`{test_rel}`)\n"
        f"- **Hypothesis PBT Present:** `{has_pbt}`\n"
        f"- **Pre-Flight Collection & Harness Gate:** `PASS`\n"
        f"- **Pre-Fix Exit Code:** `{repro_run.returncode}` (1 confirms bug/feature fails before patch)\n\n"
        "### ReproAgent Attempt History\n\n"
        "| Attempt | Model Tier | Pre-Flight | Notes |\n"
        "|---|---|---|---|\n"
        f"{history_table}\n\n"
        f"```\n{(repro_run.stdout + repro_run.stderr)[-2000:]}\n```\n"
    )
    status_path = artifacts_dir / "status.md"
    status_path.write_text(status_path.read_text(encoding="utf-8") + note, encoding="utf-8")
    return True, test_path, f"Created {test_rel} (PBT={has_pbt}, preflight=OK, attempts={len(repro_history)}, pre-fix rc={repro_run.returncode})"


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
            raw_content = p.read_text(encoding="utf-8")
            code_sections.append(f"### FILE: {rel}\n```python\n{raw_content}\n```")

    arch_text = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")

    system_prompt = (
        "You are Stage 3 (CoderAgent) for TinyDB (Python >=3.10, ZERO third-party runtime dependencies in tinydb/).\n"
        "You MUST output edits strictly as exact SEARCH/REPLACE blocks — NEVER rewrite entire files.\n\n"
        "EXACT OUTPUT FORMAT (repeat for each edit):\n"
        "FILE: tinydb/queries.py\n"
        "<<<<<<< SEARCH\n"
        "<exact verbatim existing lines from the file, including indentation>\n"
        "=======\n"
        "<replacement lines>\n"
        ">>>>>>> REPLACE\n\n"
        "RULES:\n"
        "1. Only edit files under `tinydb/` or `tests/`.\n"
        "2. Copy SEARCH lines character-for-character from the Current File Contents provided below.\n"
        "3. Include 3-6 surrounding context lines so each SEARCH block matches uniquely.\n"
        "4. Respect all TinyDB architectural constraints (stdlib only in tinydb/, sound Query hashvals, no upward imports).\n"
        "5. If the failure trace shows a Hypothesis strategy/harness bug in `tests/test_issue_*_pbt.py` "
        "(e.g., `FailedHealthCheck`, `NaN != NaN`, `True == 1` bool/int mix, or `getattr(Query(), ...)`), "
        "fix the buggy strategy in `tests/test_issue_*_pbt.py` while keeping all real acceptance assertions intact."
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

"""Stage 4: Evaluator — runs PBT-first new tests + full TinyDB regression suite."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .tools import run_cmd


def run_stage4_eval(
    repo_root: Path,
    artifacts_dir: Path,
    test_rel: str,
    attempt_history: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    """Run new PBT/AC test suite and full TinyDB regression suite; write test_report.md."""
    pbt_code = (repo_root / test_rel).read_text(encoding="utf-8") if (repo_root / test_rel).exists() else ""
    has_pbt = "@given" in pbt_code and "hypothesis" in pbt_code

    new_proc = run_cmd(
        [sys.executable, "-m", "pytest", "-o", "addopts=", test_rel, "-v", "--tb=short"],
        cwd=repo_root,
        timeout=60,
    )
    full_proc = run_cmd(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-v", "--tb=short"],
        cwd=repo_root,
        timeout=90,
    )

    new_ok = new_proc.returncode == 0
    full_ok = full_proc.returncode == 0
    passed = new_ok and full_ok

    attempt_rows = "\n".join(
        f"| {a['attempt']} | {a['tier']} | {a['build_ok']} | {a['tests_ok']} | {a['note']} |"
        for a in attempt_history
    )

    report = (
        "# Test Report (`test_report.md`)\n\n"
        f"- **Testing Strategy:** Property-Based Testing (`hypothesis` `@given`, `max_examples=50`, `derandomize=True`) + Boundary Tests + Full Regression Suite\n"
        f"- **Hypothesis PBT Verified in `{test_rel}`:** `{has_pbt}`\n"
        f"- **New AC/PBT Suite Passed:** `{new_ok}` (exit code `{new_proc.returncode}`)\n"
        f"- **Full Regression Suite Passed:** `{full_ok}` (exit code `{full_proc.returncode}`)\n"
        f"- **Stage 4 Gate Verdict:** `{'PASS' if passed else 'FAIL'}`\n\n"
        "## Evaluator-Optimizer Attempt History\n\n"
        "| Attempt | Model Tier | Build OK | Tests OK | Notes |\n"
        "|---|---|---|---|---|\n"
        f"{attempt_rows}\n\n"
        f"## New PBT & Acceptance Tests Output (`{test_rel}`)\n"
        f"```\n{(new_proc.stdout + new_proc.stderr)[-3000:]}\n```\n\n"
        "## Full Regression Suite Output\n"
        f"```\n{(full_proc.stdout + full_proc.stderr)[-3000:]}\n```\n"
    )
    (artifacts_dir / "test_report.md").write_text(report, encoding="utf-8")

    if passed:
        return True, "All new PBT/AC tests and full TinyDB regression suite passed.", ""

    stderr_feedback = ""
    if not new_ok:
        stderr_feedback += f"=== New PBT/AC Tests Failed ({test_rel}) ===\n{new_proc.stdout}\n{new_proc.stderr}\n"
    if not full_ok:
        stderr_feedback += f"=== Full Regression Suite Failed ===\n{full_proc.stdout}\n{full_proc.stderr}\n"
    return False, f"Tests failed (new_ok={new_ok}, full_ok={full_ok}).", stderr_feedback

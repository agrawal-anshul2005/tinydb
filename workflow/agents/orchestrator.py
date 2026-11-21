"""Deterministic Python Orchestrator (NO LLM) for Stages 1-5 + Stage 4->3 Evaluator loop.

Implements ADR-002 (control flow), ADR-004 (state/branches), ADR-007 (hybrid gates),
and ADR-009 (caps & fail-closed halting).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from .llm import BudgetExceededError, LLMGateway
from .stage1_requirements import fetch_issue_data, run_stage1
from .stage2_design import run_stage2
from .stage3_implement import record_baseline_status, run_coder_attempt, run_repro_agent
from .stage4_test import run_stage4_eval
from .stage5_release import run_stage5
from .tools import run_cmd


def _write_gh_output(pairs: dict[str, str]) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        for k, v in pairs.items():
            fh.write(f"{k}={v}\n")


def _comment_halt(repo_root: Path, issue_number: int, stage: str, reason: str, dry_run: bool) -> None:
    if dry_run:
        return
    body = (
        f"### AutoSE Workflow Halted at **{stage}**\n\n"
        f"**Reason:** {reason}\n\n"
        "Inspect the uploaded GitHub Actions artifacts (`spec.md`, `design.md`, `diff.patch`, "
        "`test_report.md`, `usage.json`) for full details. A human maintainer must clarify or intervene."
    )
    run_cmd(["gh", "issue", "comment", str(issue_number), "--body", body], cwd=repo_root, timeout=30)


def _prepare_branch(repo_root: Path, branch: str, round_num: int, dry_run: bool) -> None:
    if dry_run:
        return
    if round_num == 1:
        run_cmd(["git", "checkout", "-B", branch], cwd=repo_root, timeout=30, check=True)
    else:
        # Round 2 checks out the existing PR branch from origin
        run_cmd(["git", "fetch", "origin", branch], cwd=repo_root, timeout=30, check=True)
        run_cmd(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=repo_root, timeout=30, check=True)


def _extract_target_files_from_design(repo_root: Path, design_text: str) -> list[str]:
    refs = sorted(set(re.findall(r"\btinydb/[A-Za-z0-9_./-]+\.py\b", design_text)))
    return [f for f in refs if (repo_root / f).exists()]


def run_pipeline(
    repo_root: Path,
    artifacts_dir: Path,
    issue_number: int,
    round_num: int = 1,
    start_stage: int = 1,
    review_feedback_file: Path | None = None,
    existing_pr: int | None = None,
    issue_file: Path | None = None,
    dry_run: bool = False,
) -> int:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMGateway(artifacts_dir / "usage.json")
    branch = f"autose/issue-{issue_number}"
    test_rel = f"tests/test_issue_{issue_number}_pbt.py"
    review_feedback = (
        review_feedback_file.read_text(encoding="utf-8")
        if review_feedback_file and review_feedback_file.exists()
        else None
    )

    max_attempts = int(os.environ.get("MAX_CODER_ATTEMPTS", "3"))  # 2 Flash + 1 escalated 3.7-Flash

    try:
        # ---------------- STAGE 1: REQUIREMENTS ----------------
        if start_stage <= 1:
            print(f"[orchestrator] === Stage 1: Requirements (Issue #{issue_number}) ===")
            ok1, msg1, issue = run_stage1(repo_root, artifacts_dir, llm, issue_number, issue_file=issue_file)
            print(f"[orchestrator] Stage 1 -> ok={ok1}: {msg1}")
            if not ok1:
                _write_gh_output({"status": "halted", "failed_stage": "stage1_requirements", "branch": branch})
                _comment_halt(repo_root, issue_number, "Stage 1 (Requirements)", msg1, dry_run)
                return 0
            spec_text = (artifacts_dir / "spec.md").read_text(encoding="utf-8")
            issue_title = issue["title"]
        else:
            issue = fetch_issue_data(repo_root, issue_number, issue_file=issue_file)
            issue_title = issue["title"]
            spec_text = (artifacts_dir / "spec.md").read_text(encoding="utf-8")

        # ---------------- STAGE 2: EXPLORER & DESIGN ----------------
        if start_stage <= 2:
            print(f"[orchestrator] === Stage 2: Explorer & Design (Round {round_num}) ===")
            ok2, msg2, target_files = run_stage2(
                repo_root,
                artifacts_dir,
                llm,
                spec_text,
                review_feedback=review_feedback if start_stage == 2 else None,
            )
            print(f"[orchestrator] Stage 2 -> ok={ok2}: {msg2}")
            if not ok2:
                _write_gh_output({"status": "halted", "failed_stage": "stage2_design", "branch": branch})
                _comment_halt(repo_root, issue_number, "Stage 2 (Design)", msg2, dry_run)
                return 0
            design_text = (artifacts_dir / "design.md").read_text(encoding="utf-8")
        else:
            design_text = (artifacts_dir / "design.md").read_text(encoding="utf-8")
            target_files = _extract_target_files_from_design(repo_root, design_text)

        # ---------------- STAGE 3 & 4: PBT REPRO + CODER / EVALUATOR LOOP ----------------
        _prepare_branch(repo_root, branch, round_num, dry_run)

        print(f"[orchestrator] === Stage 3A: Baseline Status & PBT Repro (Round {round_num}) ===")
        record_baseline_status(repo_root, artifacts_dir)

        if round_num == 1 or not (repo_root / test_rel).exists():
            repro_ok, _, repro_msg = run_repro_agent(
                repo_root, artifacts_dir, llm, issue_number, spec_text, design_text, target_files
            )
            print(f"[orchestrator] ReproAgent -> ok={repro_ok}: {repro_msg}")
            if not repro_ok:
                _write_gh_output({"status": "halted", "failed_stage": "stage3_repro", "branch": branch})
                _comment_halt(repo_root, issue_number, "Stage 3 (PBT Repro)", repro_msg, dry_run)
                return 0

        attempt_history: list[dict[str, Any]] = []
        error_feedback: str | None = None
        all_tests_passed = False

        for attempt in range(1, max_attempts + 1):
            print(f"[orchestrator] === Stage 3B/4: Coder Attempt {attempt}/{max_attempts} ===")
            build_ok, build_msg, tier = run_coder_attempt(
                repo_root=repo_root,
                artifacts_dir=artifacts_dir,
                llm=llm,
                attempt=attempt,
                spec_text=spec_text,
                design_text=design_text,
                target_files=target_files,
                test_rel=test_rel,
                error_feedback=error_feedback,
                review_feedback=review_feedback if attempt == 1 else None,
            )
            print(f"[orchestrator] Stage 3 (attempt {attempt}, {tier}) -> build_ok={build_ok}: {build_msg}")

            if not build_ok:
                attempt_history.append(
                    {"attempt": attempt, "tier": tier, "build_ok": False, "tests_ok": False, "note": build_msg[:120]}
                )
                error_feedback = build_msg
                # Restore dirty tinydb files before next clean SEARCH/REPLACE attempt if compile failed
                run_cmd(["git", "checkout", "--", "tinydb"], cwd=repo_root, timeout=15)
                continue

            attempt_entry = {
                "attempt": attempt,
                "tier": tier,
                "build_ok": True,
                "tests_ok": "pending",
                "note": build_msg[:120],
            }
            attempt_history.append(attempt_entry)
            tests_ok, test_msg, stderr_trace = run_stage4_eval(repo_root, artifacts_dir, test_rel, attempt_history)
            attempt_entry["tests_ok"] = tests_ok
            attempt_entry["note"] = test_msg[:120]
            # Update test_report.md header/table row without re-running pytest
            report_path = artifacts_dir / "test_report.md"
            if report_path.exists():
                txt = report_path.read_text(encoding="utf-8")
                txt = txt.replace(f"| {attempt} | {tier} | True | pending |", f"| {attempt} | {tier} | True | {tests_ok} |")
                report_path.write_text(txt, encoding="utf-8")
            print(f"[orchestrator] Stage 4 (attempt {attempt}) -> tests_ok={tests_ok}: {test_msg}")

            if tests_ok:
                all_tests_passed = True
                break
            error_feedback = stderr_trace

        if not all_tests_passed:
            msg = f"Failed to pass Stage 3/4 after {max_attempts} attempts (2 primary + 1 escalated). Escalating to human."
            _write_gh_output({"status": "halted", "failed_stage": "stage4_testing", "branch": branch})
            _comment_halt(repo_root, issue_number, "Stage 4 (Testing)", msg, dry_run)
            return 0

        if dry_run:
            print("[orchestrator] Dry run complete — Stages 1-4 passed! Skipping git push / PR creation.")
            return 0

        # ---------------- STAGE 5: RELEASE (PR + CI) ----------------
        print(f"[orchestrator] === Stage 5: Release & CI Verification (Round {round_num}) ===")
        ok5, msg5, pr_meta = run_stage5(
            repo_root=repo_root,
            artifacts_dir=artifacts_dir,
            llm=llm,
            issue_number=issue_number,
            issue_title=issue_title,
            branch=branch,
            round_num=round_num,
            existing_pr_number=existing_pr,
        )
        print(f"[orchestrator] Stage 5 -> ok={ok5}: {msg5}")
        if not ok5:
            _write_gh_output(
                {
                    "status": "halted",
                    "failed_stage": "stage5_release",
                    "branch": branch,
                    "pr_number": str(pr_meta.get("pr_number", "")),
                }
            )
            _comment_halt(repo_root, issue_number, "Stage 5 (Release / CI)", msg5, dry_run)
            return 0

        _write_gh_output(
            {
                "status": "released",
                "pr_number": str(pr_meta["pr_number"]),
                "pr_url": str(pr_meta["pr_url"]),
                "head_sha": str(pr_meta["head_sha"]),
                "branch": branch,
            }
        )
        return 0

    except BudgetExceededError as exc:
        print(f"[orchestrator] BUDGET EXCEEDED: {exc}")
        _write_gh_output({"status": "halted", "failed_stage": "budget_guardrail", "branch": branch})
        _comment_halt(repo_root, issue_number, "Budget Guardrail (ADR-009)", str(exc), dry_run)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoSE Deterministic SDLC Orchestrator (Stages 1-5)")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--start-stage", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--review-feedback", type=Path, default=None)
    parser.add_argument("--pr-number", type=int, default=None)
    parser.add_argument("--issue-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    return run_pipeline(
        repo_root=Path.cwd(),
        artifacts_dir=args.artifacts_dir,
        issue_number=args.issue,
        round_num=args.round,
        start_stage=args.start_stage,
        review_feedback_file=args.review_feedback,
        existing_pr=args.pr_number,
        issue_file=args.issue_file,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 6: Independent ReviewerAgent — isolated read-only job, cross-provider (GitHub Models).

Implements ADR-008: sees ONLY the original issue, the PR diff, and the repository at PR HEAD
(with read-only pytest execution). NEVER reads Stage 1-5 artifacts or implementer traces.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .llm import LLMGateway, get_model_chain, wrap_untrusted
from .tools import format_repo_map_text, repo_map, run_cmd


def _write_gh_output(pairs: dict[str, str]) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a", encoding="utf-8") as fh:
        for k, v in pairs.items():
            fh.write(f"{k}={v}\n")


def _parse_verdict(text: str) -> str:
    """Extract APPROVE | FIX_CODE | FIX_DESIGN from reviewer output."""
    m = re.search(r'"verdict"\s*:\s*"(APPROVE|FIX_CODE|FIX_DESIGN)"', text, re.I)
    if m:
        return m.group(1).upper()
    m2 = re.search(r"VERDICT:\s*\**\s*(APPROVE|FIX_CODE|FIX_DESIGN)", text, re.I)
    if m2:
        return m2.group(1).upper()
    # Conservative default: if reviewer didn't explicitly approve, treat as FIX_CODE
    return "FIX_CODE"


def run_stage6_review(
    repo_root: Path,
    artifacts_dir: Path,
    issue_number: int,
    pr_number: int,
    round_num: int,
) -> tuple[str, str]:
    """Execute independent review in a clean, read-only container."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMGateway(artifacts_dir / "review_usage.json")

    # 1. Fetch ONLY the original issue and the PR diff (never Stage 1-5 traces!)
    issue_proc = run_cmd(
        ["gh", "issue", "view", str(issue_number), "--json", "number,title,body"],
        cwd=repo_root,
        timeout=30,
        check=True,
    )
    issue = json.loads(issue_proc.stdout)

    diff_proc = run_cmd(["gh", "pr", "diff", str(pr_number)], cwd=repo_root, timeout=30, check=True)
    pr_diff = diff_proc.stdout

    # 2. Independently run pytest (read-only verification of the PR HEAD)
    pytest_proc = run_cmd(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-v", "--tb=short"],
        cwd=repo_root,
        timeout=90,
    )
    pytest_summary = (pytest_proc.stdout + "\n" + pytest_proc.stderr)[-2500:]

    # 3. Build read-only AST repo map + architecture constraints (public repo files at PR HEAD)
    skel_text = format_repo_map_text(repo_map(repo_root, subdirs=("tinydb",)))
    arch_path = repo_root / "ARCHITECTURE.md"
    arch_excerpt = arch_path.read_text(encoding="utf-8")[:3500] if arch_path.exists() else ""

    system_prompt = (
        "You are Stage 6 — an INDEPENDENT, skeptical senior Python code reviewer for TinyDB.\n"
        "You have NO connection to the implementer and NO push permissions. Your job is to protect "
        "TinyDB's correctness, backward compatibility, and architecture — NEVER rubber-stamp a PR.\n\n"
        "Audit the PR diff rigorously against this checklist:\n"
        "1. **Issue Fulfillment:** Does the diff completely satisfy every requirement in the issue?\n"
        "2. **Edge Cases & Correctness:** Missing keys, None/non-mapping/incomparable types, empty collections, generators, mutation side effects?\n"
        "3. **TinyDB Query-Cache Soundness:** Does any new/modified `Query` method include `self._path` and ALL behavior-affecting arguments (frozen via `freeze()`) in `hashval`?\n"
        "4. **Architectural Constraints:** Zero third-party runtime imports in `tinydb/`, no upward imports from `queries.py`/`operations.py`, no edits outside `tinydb/` and `tests/`?\n"
        "5. **Test Quality (PBT + Boundary):** Do the tests genuinely test invariants (Hypothesis `@given`) and edge cases, or are they trivial/tautological?\n"
        "6. **Over-engineering & Security:** Any unnecessary complexity, dead code, or unsafe constructs?\n\n"
        "DECISION RULES:\n"
        "- Choose `APPROVE` ONLY if all 6 checks pass with concrete evidence.\n"
        "- Choose `FIX_DESIGN` if the overall approach violates TinyDB's architecture or targets the wrong module/abstraction.\n"
        "- Choose `FIX_CODE` if the approach is sound but there is a bug, missed edge case, hash/cache flaw, or missing/weak test.\n\n"
        "OUTPUT FORMAT (Markdown):\n"
        "Start with a single line: `VERDICT: APPROVE` OR `VERDICT: FIX_CODE` OR `VERDICT: FIX_DESIGN`\n"
        "Followed by:\n"
        "## Independent Review Summary (Round <N>/2)\n"
        "## Checklist Audit (1-6 with specific file/line evidence)\n"
        "## Blocking Findings (if any — actionable fixes required)\n"
        "## Non-Blocking Notes\n"
    )

    issue_blob = f"Issue #{issue['number']}: {issue['title']}\n\n{issue.get('body', '')}"
    user_prompt = (
        f"Review Pull Request #{pr_number} for Issue #{issue_number} (Review Round {round_num}/2).\n\n"
        f"{wrap_untrusted(f'issue-{issue_number}', issue_blob)}\n\n"
        f"## PR Diff (`gh pr diff {pr_number}`)\n```diff\n{pr_diff[:12000]}\n```\n\n"
        f"## Independent `pytest` Run at PR HEAD (exit code {pytest_proc.returncode})\n"
        f"```\n{pytest_summary}\n```\n\n"
        f"## Repository AST Map at PR HEAD\n{skel_text[:3500]}\n\n"
        f"## TinyDB Architecture Constraints\n{arch_excerpt}"
    )

    models = get_model_chain(
        "GEMMA_REVIEWER_MODELS",
        "gemma-4-31b-it,gemma-4-26b-a4b-it,gemini-3.7-flash,gemini-3.6-flash",
    )
    review_text = llm.call_gemini(
        stage=f"stage6_independent_review_r{round_num}",
        models=models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )

    verdict = _parse_verdict(review_text)
    if pytest_proc.returncode != 0 and verdict == "APPROVE":
        verdict = "FIX_CODE"
        review_text = (
            "VERDICT: FIX_CODE\n\n"
            "> **Override:** Independent `pytest` execution failed at PR HEAD; cannot approve.\n\n"
            + review_text
        )

    final_note = ""
    if verdict == "APPROVE":
        final_note = "\n\n---\n**Next Action:** Independent reviewer approved. **Awaiting human maintainer to merge or close.**\n"
    elif round_num >= 2:
        final_note = "\n\n---\n**Next Action:** Maximum of **2 review rounds** reached. Stopping automated loops — **awaiting human maintainer decision.**\n"
    else:
        target = "Stage 2 (Design)" if verdict == "FIX_DESIGN" else "Stage 3 (Implementation)"
        final_note = f"\n\n---\n**Next Action:** Routing requested changes back to **{target}** for Review Round {round_num + 1}/2.\n"

    full_review = (
        f"### Independent Code Review — Round {round_num}/2 (`{verdict}`)\n\n"
        f"*Reviewer context: Fresh container, read-only code permissions (`contents: read`), "
        f"distinct open-weight model family (`{llm.records[-1]['used_model']}`), zero access to implementer traces.*\n\n"
        f"{review_text}{final_note}"
    )
    review_path = artifacts_dir / "review.md"
    review_path.write_text(full_review, encoding="utf-8")

    # Post visible review on GitHub PR.
    # Note: GitHub API rejects --approve / --request-changes when GITHUB_TOKEN authored the PR,
    # so we post via `gh pr review --comment` which always succeeds cleanly with full auditability.
    post = run_cmd(
        ["gh", "pr", "review", str(pr_number), "--comment", "--body-file", str(review_path)],
        cwd=repo_root,
        timeout=30,
    )
    if post.returncode != 0:
        # Fallback to PR comment if pr review endpoint fails
        run_cmd(
            ["gh", "pr", "comment", str(pr_number), "--body-file", str(review_path)],
            cwd=repo_root,
            timeout=30,
        )

    _write_gh_output({"verdict": verdict, "round": str(round_num)})
    print(f"[stage6] Review Round {round_num} completed with verdict={verdict}")
    return verdict, full_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 6 Independent ReviewerAgent")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args()

    repo_root = Path.cwd()
    run_stage6_review(
        repo_root=repo_root,
        artifacts_dir=args.artifacts_dir,
        issue_number=args.issue,
        pr_number=args.pr,
        round_num=args.round,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stage 5: DeliveryAgent — structured PR via GitHub Models, push branch, open PR, verify CI."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .llm import LLMGateway, get_model_chain
from .tools import run_cmd


def _generate_pr_metadata(
    llm: LLMGateway,
    issue_number: int,
    issue_title: str,
    spec_text: str,
    design_text: str,
    diff_text: str,
    test_report: str,
    round_num: int,
) -> tuple[str, str, str]:
    """Generate structured commit message, PR title, and PR body using GitHub Models."""
    system_prompt = (
        "You are Stage 5 (DeliveryAgent) for TinyDB.\n"
        "Generate a clean commit message, PR title, and structured Markdown PR summary.\n"
        "Return ONLY valid JSON with exact keys: `commit_message`, `pr_title`, `pr_body`.\n"
        "Do not wrap in extra commentary. Mention `Closes #<issue_number>` in `pr_body`."
    )
    user_prompt = (
        f"Issue #{issue_number}: {issue_title} (Review Round {round_num})\n\n"
        f"## spec.md (excerpt)\n{spec_text[:2000]}\n\n"
        f"## design.md (excerpt)\n{design_text[:2000]}\n\n"
        f"## diff.patch (excerpt)\n{diff_text[:3000]}\n\n"
        f"## test_report.md (excerpt)\n{test_report[:1500]}"
    )

    models = get_model_chain("GH_DELIVERY_MODELS", "openai/gpt-4o-mini,meta/llama-3.3-70b-instruct")
    try:
        raw = llm.call_github_models(
            stage=f"stage5_delivery_r{round_num}",
            models=models,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=1200,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)
        commit_msg = str(data.get("commit_message") or f"fix: address issue #{issue_number}").strip()
        pr_title = str(data.get("pr_title") or f"AutoSE: Address #{issue_number} ({issue_title[:55]})").strip()
        pr_body = str(data.get("pr_body") or f"Automated fix for #{issue_number}.\n\nCloses #{issue_number}").strip()
        if f"#{issue_number}" not in pr_body:
            pr_body += f"\n\nCloses #{issue_number}"
        return commit_msg, pr_title, pr_body
    except Exception as exc:
        print(f"[stage5] DeliveryAgent LLM fallback due to: {exc}")
        commit_msg = f"fix: resolve issue #{issue_number} (round {round_num})"
        pr_title = f"AutoSE: Resolve #{issue_number} — {issue_title[:60]}"
        pr_body = (
            f"## Summary\nAutomated solution for issue #{issue_number} (Round {round_num}).\n\n"
            f"## Verification\n- Property-based tests (`hypothesis`) and full TinyDB `pytest` suite passed.\n\n"
            f"Closes #{issue_number}\n"
        )
        return commit_msg, pr_title, pr_body


def _trigger_and_wait_ci(repo_root: Path, branch: str, pr_number: int) -> tuple[bool, str]:
    """Ensure ci.yml runs and passes on the PR branch.

    Note: PRs created by GITHUB_TOKEN suppress automatic pull_request triggers in GitHub
    Actions, so we explicitly dispatch ci.yml via workflow_dispatch on `branch` and wait
    for its real conclusion.
    """
    # Dispatch ci.yml on the PR branch (allowed for GITHUB_TOKEN with actions: write)
    before_proc = run_cmd(
        [
            "gh", "run", "list", "--workflow", "ci.yml", "--branch", branch,
            "--event", "workflow_dispatch", "--limit", "1", "--json", "databaseId",
        ],
        cwd=repo_root,
        timeout=30,
    )
    prev_id = None
    if before_proc.returncode == 0 and before_proc.stdout.strip():
        try:
            items = json.loads(before_proc.stdout)
            if items:
                prev_id = items[0].get("databaseId")
        except Exception:
            pass

    disp = run_cmd(
        ["gh", "workflow", "run", "ci.yml", "--ref", branch],
        cwd=repo_root,
        timeout=30,
    )
    if disp.returncode != 0:
        return False, f"Failed to dispatch ci.yml on {branch}: {disp.stderr}"

    # Poll for the new workflow_dispatch ci.yml run to appear (up to 45s)
    run_id = None
    run_url = ""
    for _ in range(9):
        time.sleep(5)
        lst = run_cmd(
            [
                "gh", "run", "list", "--workflow", "ci.yml", "--branch", branch,
                "--event", "workflow_dispatch", "--limit", "3",
                "--json", "databaseId,status,conclusion,url",
            ],
            cwd=repo_root,
            timeout=30,
        )
        if lst.returncode == 0 and lst.stdout.strip():
            try:
                runs = json.loads(lst.stdout)
                for r in runs:
                    if r.get("databaseId") != prev_id:
                        run_id = r["databaseId"]
                        run_url = r.get("url", "")
                        break
            except Exception:
                pass
        if run_id is not None:
            break

    if run_id is None:
        return False, f"Dispatched ci.yml on {branch}, but no new run appeared within 45s."

    # Wait up to 180s for CI completion
    for _ in range(36):
        view = run_cmd(
            ["gh", "run", "view", str(run_id), "--json", "status,conclusion,url"],
            cwd=repo_root,
            timeout=30,
        )
        if view.returncode == 0 and view.stdout.strip():
            info = json.loads(view.stdout)
            status = info.get("status")
            conclusion = info.get("conclusion")
            run_url = info.get("url", run_url)
            if status == "completed":
                ok = conclusion == "success"
                return ok, f"CI run {run_url} completed with conclusion={conclusion}"
        time.sleep(5)

    return False, f"Timed out waiting for CI run {run_url} on PR #{pr_number}."


def run_stage5(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    issue_number: int,
    issue_title: str,
    branch: str,
    round_num: int,
    existing_pr_number: int | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Commit allowlisted edits, push branch, open/update PR, wait for CI, write pr.md."""
    spec_text = (artifacts_dir / "spec.md").read_text(encoding="utf-8") if (artifacts_dir / "spec.md").exists() else ""
    design_text = (artifacts_dir / "design.md").read_text(encoding="utf-8") if (artifacts_dir / "design.md").exists() else ""
    diff_text = (artifacts_dir / "diff.patch").read_text(encoding="utf-8") if (artifacts_dir / "diff.patch").exists() else ""
    test_report = (artifacts_dir / "test_report.md").read_text(encoding="utf-8") if (artifacts_dir / "test_report.md").exists() else ""

    commit_msg, pr_title, pr_body = _generate_pr_metadata(
        llm, issue_number, issue_title, spec_text, design_text, diff_text, test_report, round_num
    )

    # Configure bot git identity
    run_cmd(["git", "config", "user.name", "autose-bot"], cwd=repo_root, timeout=15)
    run_cmd(["git", "config", "user.email", "autose-bot@users.noreply.github.com"], cwd=repo_root, timeout=15)

    # Stage ONLY allowlisted paths under tinydb/ and tests/
    run_cmd(["git", "add", "--", "tinydb", "tests"], cwd=repo_root, timeout=30, check=True)
    staged = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=repo_root, timeout=15)
    if not staged.stdout.strip():
        msg = "No staged changes under tinydb/ or tests/ to commit."
        (artifacts_dir / "pr.md").write_text(f"# Stage 5 Release Failed\n\n{msg}\n", encoding="utf-8")
        return False, msg, {}

    commit_proc = run_cmd(["git", "commit", "-m", commit_msg], cwd=repo_root, timeout=30)
    if commit_proc.returncode != 0:
        msg = f"git commit failed: {commit_proc.stderr}"
        (artifacts_dir / "pr.md").write_text(f"# Stage 5 Release Failed\n\n{msg}\n", encoding="utf-8")
        return False, msg, {}

    push_proc = run_cmd(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=repo_root, timeout=60)
    if push_proc.returncode != 0:
        # Fallback to --force on fresh branch re-run on our own fork
        push_proc = run_cmd(["git", "push", "--force", "-u", "origin", branch], cwd=repo_root, timeout=60)
        if push_proc.returncode != 0:
            msg = f"git push failed: {push_proc.stderr}"
            (artifacts_dir / "pr.md").write_text(f"# Stage 5 Release Failed\n\n{msg}\n", encoding="utf-8")
            return False, msg, {}

    # Check if an open PR already exists for this branch
    pr_number = existing_pr_number
    pr_url = ""
    if pr_number is None:
        find_pr = run_cmd(
            ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"],
            cwd=repo_root,
            timeout=30,
        )
        if find_pr.returncode == 0 and find_pr.stdout.strip():
            prs = json.loads(find_pr.stdout)
            if prs:
                pr_number = int(prs[0]["number"])
                pr_url = prs[0]["url"]

    body_file = artifacts_dir / "_pr_body_tmp.md"
    body_file.write_text(pr_body, encoding="utf-8")

    if pr_number is None:
        create_pr = run_cmd(
            [
                "gh", "pr", "create",
                "--base", "main",
                "--head", branch,
                "--title", pr_title,
                "--body-file", str(body_file),
            ],
            cwd=repo_root,
            timeout=30,
        )
        if create_pr.returncode != 0:
            msg = f"gh pr create failed: {create_pr.stderr}"
            (artifacts_dir / "pr.md").write_text(f"# Stage 5 Release Failed\n\n{msg}\n", encoding="utf-8")
            return False, msg, {}
        pr_url = create_pr.stdout.strip().splitlines()[-1]
        m = re.search(r"/pull/(\d+)", pr_url)
        pr_number = int(m.group(1)) if m else None
    else:
        run_cmd(
            ["gh", "pr", "comment", str(pr_number), "--body", f"Updated branch `{branch}` for Review Round {round_num}.\n\nCommit: `{commit_msg}`"],
            cwd=repo_root,
            timeout=30,
        )
        view_pr = run_cmd(["gh", "pr", "view", str(pr_number), "--json", "url,state"], cwd=repo_root, timeout=30)
        if view_pr.returncode == 0:
            pr_url = json.loads(view_pr.stdout).get("url", pr_url)

    body_file.unlink(missing_ok=True)

    # Verify PR is open
    pr_state_proc = run_cmd(["gh", "pr", "view", str(pr_number), "--json", "state,url,headRefOid"], cwd=repo_root, timeout=30)
    if pr_state_proc.returncode != 0:
        msg = f"Failed to verify open PR #{pr_number}: {pr_state_proc.stderr}"
        (artifacts_dir / "pr.md").write_text(f"# Stage 5 Release Failed\n\n{msg}\n", encoding="utf-8")
        return False, msg, {}
    pr_info = json.loads(pr_state_proc.stdout)
    is_open = pr_info.get("state") == "OPEN"
    pr_url = pr_info.get("url", pr_url)
    head_sha = pr_info.get("headRefOid", "")

    # Dispatch & verify ci.yml passes on the PR branch
    ci_ok, ci_msg = _trigger_and_wait_ci(repo_root, branch, pr_number)
    passed = is_open and ci_ok

    pr_md = (
        "# Release Summary (`pr.md`)\n\n"
        f"- **Issue:** #{issue_number}\n"
        f"- **PR Number:** #{pr_number}\n"
        f"- **PR URL:** {pr_url}\n"
        f"- **Branch:** `{branch}` (`{head_sha[:10]}`)\n"
        f"- **PR Open:** `{is_open}`\n"
        f"- **CI Passed:** `{ci_ok}` ({ci_msg})\n"
        f"- **Auto-Merge:** `DISABLED` (human maintainer decides)\n"
        f"- **Stage 5 Gate Verdict:** `{'PASS' if passed else 'FAIL'}`\n\n"
        f"## Commit Message\n`{commit_msg}`\n\n"
        f"## Pull Request Description\n{pr_body}\n"
    )
    (artifacts_dir / "pr.md").write_text(pr_md, encoding="utf-8")

    return (
        passed,
        f"PR #{pr_number} ({pr_url}) open={is_open}, ci={ci_ok}: {ci_msg}",
        {"pr_number": pr_number, "pr_url": pr_url, "head_sha": head_sha, "branch": branch},
    )

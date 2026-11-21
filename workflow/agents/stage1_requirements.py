"""Stage 1: RequirementsAgent — turns a GitHub issue into spec.md using skill.md."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm import LLMGateway, get_model_chain, wrap_untrusted
from .tools import run_cmd


def fetch_issue_data(repo_root: Path, issue_number: int, issue_file: Path | None = None) -> dict[str, Any]:
    """Safely retrieve issue data via gh CLI (never shell-interpolating untrusted text)."""
    if issue_file is not None:
        return {
            "number": issue_number,
            "title": f"Local issue #{issue_number}",
            "body": issue_file.read_text(encoding="utf-8"),
            "comments": [],
        }
    proc = run_cmd(
        ["gh", "issue", "view", str(issue_number), "--json", "number,title,body,labels,comments"],
        cwd=repo_root,
        timeout=30,
        check=True,
    )
    return json.loads(proc.stdout)


def validate_spec_gate(spec_text: str) -> tuple[bool, str]:
    """Deterministic Stage 1 gate check: concrete, traceable, testable ACs + PASS verdict."""
    reasons: list[str] = []

    if not re.search(r"\bFR-\d+\b", spec_text):
        reasons.append("Missing unique Functional Requirement IDs (FR-1, ...).")

    ac_matches = re.findall(r"\bAC-\d+\b", spec_text)
    if not ac_matches:
        reasons.append("Missing unique Acceptance Criteria IDs (AC-1, ...).")

    if not (
        re.search(r"\bGiven\b", spec_text, re.I)
        and re.search(r"\bWhen\b", spec_text, re.I)
        and re.search(r"\bThen\b", spec_text, re.I)
    ):
        reasons.append("Acceptance criteria are not written in testable Given/When/Then format.")

    if re.search(r"Blocking:\s*Yes", spec_text, re.I):
        reasons.append("Specification contains blocking [UNRESOLVED] open questions requiring human input.")

    if re.search(r"Testability:\s*\**\s*FAIL", spec_text, re.I):
        reasons.append("Validation Summary reported Testability: FAIL.")

    gate_fail = re.search(r"(?:Gate Status|Readiness Verdict):\s*\**\s*FAIL", spec_text, re.I)
    gate_pass = re.search(r"(?:Gate Status|Readiness Verdict):\s*\**\s*PASS", spec_text, re.I)
    if gate_fail or not gate_pass:
        reasons.append("Specification Gate Status / Readiness Verdict is not PASS.")

    if reasons:
        return False, "; ".join(reasons)
    return True, f"Verified {len(set(ac_matches))} testable acceptance criteria and Gate Status: PASS."


def run_stage1(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    issue_number: int,
    issue_file: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run Stage 1 (Requirements) and write artifacts_dir/spec.md."""
    issue = fetch_issue_data(repo_root, issue_number, issue_file=issue_file)
    skill_text = (repo_root / "workflow" / "prompts" / "skill.md").read_text(encoding="utf-8")

    system_prompt = (
        "You are Stage 1 (RequirementsAgent) of an automated SDLC workflow for TinyDB (Python).\n"
        "Follow the Requirements Specification Skill below strictly.\n"
        "For vague or underspecified issues: you MUST NOT guess breaking public API changes.\n"
        "If an issue mixes safe, clear requirements with risky/ambiguous breaking changes, either:\n"
        "  (a) mark the ambiguous part as Blocking: Yes and set Gate Status: FAIL so a human clarifies, OR\n"
        "  (b) only if every in-scope behavior is clearly non-breaking and objectively testable, scope it cleanly.\n\n"
        f"{skill_text}"
    )

    issue_payload = f"Issue #{issue['number']}: {issue['title']}\n\n{issue.get('body', '')}"
    user_prompt = (
        "Produce the complete `spec.md` for the following GitHub issue on the TinyDB Python library.\n"
        "Ensure every Acceptance Criterion (AC-1, AC-2, ...) is written in concrete Given/When/Then format "
        "suitable for Property-Based Testing (Hypothesis) and example-based pytest assertions.\n\n"
        f"{wrap_untrusted(f'issue-{issue_number}', issue_payload)}"
    )

    models = get_model_chain("GEMINI_STAGE1_MODELS", "gemini-3.5-flash-lite,gemini-3.5-flash,gemma-4-31b-it")
    spec_text = llm.call_gemini(
        stage="stage1_requirements",
        models=models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
    )

    passed, msg = validate_spec_gate(spec_text)
    spec_path = artifacts_dir / "spec.md"
    if not passed:
        spec_text += f"\n\n---\n**Orchestrator Stage 1 Gate Check:** FAIL — {msg}\n"
    else:
        spec_text += f"\n\n---\n**Orchestrator Stage 1 Gate Check:** PASS — {msg}\n"
    spec_path.write_text(spec_text, encoding="utf-8")
    return passed, msg, issue

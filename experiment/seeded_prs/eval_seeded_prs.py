"""Evaluate Stage 6 Independent ReviewerAgent on the 5 seeded PR diffs.

Uses the exact adversarial checklist prompt, diff prioritization, verdict parser,
and disjoint Reviewer model pool from workflow/agents/stage6_review.py.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from workflow.agents.llm import LLMGateway, get_model_chain, wrap_untrusted
from workflow.agents.stage6_review import _parse_verdict, _prioritize_source_diff
from workflow.agents.tools import format_repo_map_text, repo_map

ISSUE_FILE_MAP = {
    "SPR-1": "experiment/issues/issue-4.md",
    "SPR-2": "experiment/issues/issue-3.md",
    "SPR-3": "experiment/issues/issue-1.md",
    "SPR-4": "experiment/issues/issue-2.md",
    "SPR-5": "experiment/issues/issue-3.md",
}

SYSTEM_PROMPT = (
    "You are Stage 6 — an INDEPENDENT, skeptical senior Python code reviewer for TinyDB.\n"
    "You have NO connection to the implementer and NO push permissions. Your job is to protect "
    "TinyDB's correctness, backward compatibility, and architecture — NEVER rubber-stamp a PR.\n\n"
    "Audit the PR diff rigorously against this checklist:\n"
    "1. Issue Fulfillment: Does the diff completely satisfy every requirement in the issue?\n"
    "2. Edge Cases & Correctness: Missing keys, None/non-mapping/incomparable types, generators, mutation?\n"
    "3. TinyDB Query-Cache Soundness: Does any new/modified Query method include self._path and ALL behavior-affecting arguments (frozen via freeze()) in hashval?\n"
    "4. Architectural Constraints: Zero third-party runtime imports in tinydb/, no upward imports from queries.py/operations.py, no edits outside tinydb/ and tests/?\n"
    "5. Test Quality (PBT + Boundary): Do tests verify invariants (Hypothesis @given) and multi-doc edge cases?\n"
    "6. Over-engineering & Security: Any unnecessary complexity or unsafe constructs?\n\n"
    "DECISION RULES:\n"
    "- Choose APPROVE ONLY if all 6 checks pass with concrete evidence.\n"
    "- Choose FIX_DESIGN if the approach violates TinyDB's architecture (e.g., upward imports or third-party runtime deps).\n"
    "- Choose FIX_CODE if the approach is sound but there is a bug, missed edge case, cache-hash flaw, or weak test.\n\n"
    "Start your response with a single line: `VERDICT: APPROVE` OR `VERDICT: FIX_CODE` OR `VERDICT: FIX_DESIGN`."
)


def main() -> int:
    seeded_dir = Path(__file__).resolve().parent
    labels_path = seeded_dir / "labels.csv"
    out_csv = seeded_dir / "eval_results.csv"
    usage_path = seeded_dir / "eval_usage.json"

    llm = LLMGateway(usage_path)
    skel_text = format_repo_map_text(repo_map(REPO_ROOT, subdirs=("tinydb",)))
    arch_excerpt = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")[:3500]

    models = get_model_chain("REVIEWER_PRIMARY_MODELS", "gemma-4-26b-a4b-it,gemma-4-31b-it")
    groq_reviewer_models = get_model_chain("GROQ_REVIEWER_FALLBACK_MODELS", "llama-3.3-70b-versatile,openai/gpt-oss-120b")

    rows_out: list[dict[str, str]] = []
    exact_matches = 0
    binary_matches = 0

    with labels_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pr_id = row["pr_id"]
            expected = row["expected_verdict"].strip().upper()
            diff_text = (seeded_dir / row["diff_file"]).read_text(encoding="utf-8")
            issue_path = REPO_ROOT / ISSUE_FILE_MAP[pr_id]
            issue_body = issue_path.read_text(encoding="utf-8") if issue_path.exists() else row["issue_ref"]

            user_prompt = (
                f"Review Seeded Pull Request {pr_id} ({row['issue_ref']}).\n\n"
                f"{wrap_untrusted(pr_id, issue_body)}\n\n"
                f"## PR Diff (production code prioritized first)\n```diff\n{_prioritize_source_diff(diff_text, 18000)}\n```\n\n"
                f"## Repository AST Map\n{skel_text[:3000]}\n\n"
                f"## TinyDB Architecture Constraints\n{arch_excerpt}"
            )

            review_out = llm.call_gemini(
                stage=f"seeded_review_{pr_id}",
                models=models,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                groq_fallback_models=groq_reviewer_models,
            )
            predicted = _parse_verdict(review_out)
            used_model = llm.records[-1]["used_model"] if llm.records else "unknown"
            used_provider = llm.records[-1]["provider"] if llm.records else "unknown"
            tokens = str(llm.records[-1]["total_tokens"]) if llm.records else "0"

            exact_ok = predicted == expected
            binary_ok = (predicted == "APPROVE") == (expected == "APPROVE")
            exact_matches += int(exact_ok)
            binary_matches += int(binary_ok)

            # Save individual review output for auditability
            (seeded_dir / f"{pr_id.lower()}_review.md").write_text(review_out, encoding="utf-8")

            first_summary = next((ln.strip() for ln in review_out.splitlines()[1:] if ln.strip()), "")[:160]
            rows_out.append(
                {
                    "pr_id": pr_id,
                    "expected_verdict": expected,
                    "predicted_verdict": predicted,
                    "exact_match": str(exact_ok),
                    "approve_vs_reject_match": str(binary_ok),
                    "provider": used_provider,
                    "model": used_model,
                    "tokens": tokens,
                    "summary_excerpt": first_summary,
                }
            )
            print(f"[{pr_id}] expected={expected:10s} predicted={predicted:10s} exact={exact_ok} ({used_provider}/{used_model}, {tokens} tok)")

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\nSeeded PR Reviewer Summary: exact={exact_matches}/{len(rows_out)}, approve-vs-reject={binary_matches}/{len(rows_out)}")
    print(f"Saved results to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

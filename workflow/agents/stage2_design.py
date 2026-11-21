"""Stage 2: ExplorerDesignAgent — AST repo exploration + ARCHITECTURE.md -> design.md."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm import LLMGateway, get_model_chain
from .tools import (
    all_symbols_in_map,
    format_repo_map_text,
    list_directory,
    read_file_lines,
    repo_map,
    search_symbol,
)


def build_context_bundle(repo_root: Path, spec_text: str) -> dict[str, Any]:
    """Use context-saving AST tools (ADR-005) to gather minimal relevant TinyDB slices."""
    skel = repo_map(repo_root, subdirs=("tinydb",))
    known_symbols = all_symbols_in_map(skel)

    # Extract identifiers mentioned in spec.md that match real TinyDB symbols
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", spec_text))
    matched_symbols = sorted(tokens & known_symbols)[:12]

    symbol_hits: dict[str, list[str]] = {}
    candidate_slices: dict[str, str] = {}

    for sym in matched_symbols:
        hits = search_symbol(repo_root, rf"\b{re.escape(sym)}\b", subdirs=("tinydb",), max_hits=10)
        if hits:
            symbol_hits[sym] = hits

    # Read targeted slices around matched methods/functions from the AST map
    for rel_path, entries in skel.items():
        if not isinstance(entries, list):
            continue
        file_mentioned = Path(rel_path).name in spec_text or rel_path in spec_text
        for e in entries:
            if e["kind"] == "class":
                for m in e.get("methods", []):
                    if m["name"] in matched_symbols:
                        s, end = m["lines"]
                        key = f"{rel_path}:{s}-{end} ({e['name']}.{m['name']})"
                        candidate_slices[key] = read_file_lines(repo_root, rel_path, max(1, s - 3), end + 3)
            elif e["name"] in matched_symbols or file_mentioned:
                s, end = e["lines"]
                key = f"{rel_path}:{s}-{end} ({e['name']})"
                candidate_slices[key] = read_file_lines(repo_root, rel_path, max(1, s - 3), end + 3)

    # Fallback: if no specific symbol matched, include queries.py and operations.py signatures
    return {
        "files": list_directory(repo_root, subdirs=("tinydb", "tests")),
        "repo_map_text": format_repo_map_text(skel),
        "matched_symbols": matched_symbols,
        "symbol_hits": symbol_hits,
        "targeted_slices": candidate_slices,
    }


def validate_design_gate(repo_root: Path, design_text: str, skel: dict[str, Any]) -> tuple[bool, str, list[str]]:
    """Deterministic Stage 2 gate: verify design.md names valid TinyDB files & functions."""
    file_refs = sorted(set(re.findall(r"\b(?:tinydb|tests)/[A-Za-z0-9_./-]+\.py\b", design_text)))
    tinydb_files = [f for f in file_refs if f.startswith("tinydb/") and (repo_root / f).exists()]

    if not tinydb_files:
        return (
            False,
            "design.md does not name any existing target Python file under tinydb/.",
            [],
        )

    known_symbols = all_symbols_in_map(skel)
    # Check for named symbols (existing in AST map or explicitly marked [NEW])
    mentioned_existing = [s for s in known_symbols if re.search(rf"\b{re.escape(s)}\b", design_text)]
    has_new_symbol = bool(re.search(r"\[NEW\]|def\s+[a-zA-Z_][a-zA-Z0-9_]*", design_text))

    if not mentioned_existing and not has_new_symbol:
        return (
            False,
            "design.md does not identify specific functions/methods/classes to modify or add.",
            tinydb_files,
        )

    return (
        True,
        f"Verified target files {tinydb_files} and {len(mentioned_existing)} existing AST symbol references.",
        tinydb_files,
    )


def run_stage2(
    repo_root: Path,
    artifacts_dir: Path,
    llm: LLMGateway,
    spec_text: str,
    review_feedback: str | None = None,
) -> tuple[bool, str, list[str]]:
    """Run Stage 2 (Explorer + Design) and write design.md + context.json."""
    arch_text = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
    skel = repo_map(repo_root, subdirs=("tinydb",))
    ctx = build_context_bundle(repo_root, spec_text)
    (artifacts_dir / "context.json").write_text(json.dumps(ctx, indent=2), encoding="utf-8")

    system_prompt = (
        "You are Stage 2 (ExplorerDesignAgent) of an automated SDLC workflow for TinyDB.\n"
        "You MUST obey every architectural constraint in ARCHITECTURE.md:\n"
        "  1. Zero third-party runtime dependencies in tinydb/ (stdlib only).\n"
        "  2. queries.py and operations.py must NOT import table.py, database.py, storages.py, or middlewares.py.\n"
        "  3. Every Query method must use _generate_test and include self._path + frozen behavior-affecting args in hashval.\n"
        "  4. Never propose edits outside tinydb/ and tests/.\n\n"
        "Output a clear `design.md` with these sections:\n"
        "## 1. Files and Functions to Change\n"
        "List exact file paths (`tinydb/...py`, `tests/...py`) and exact existing or `[NEW]` function/method names.\n"
        "## 2. Detailed Implementation Plan\n"
        "Step-by-step logic changes and edge cases.\n"
        "## 3. Architectural Constraint Check\n"
        "Confirm compliance with each TinyDB constraint in ARCHITECTURE.md.\n"
        "## 4. Property-Based Testing (PBT) Invariants & Boundary Tests Plan\n"
        "Specify 2-4 Hypothesis `@given` invariants (with domain strategies avoiding NaN/uncomparable traps) "
        "plus targeted example-based edge cases."
    )

    slices_text = "\n\n".join(f"### {k}\n```python\n{v}\n```" for k, v in ctx["targeted_slices"].items())
    feedback_section = ""
    if review_feedback:
        feedback_section = (
            "\n\n## Independent Reviewer Feedback (Round 2 — FIX_DESIGN)\n"
            "Address every architectural/approach flaw identified below:\n"
            f"{review_feedback}\n"
        )

    user_prompt = (
        f"## Requirements Specification (spec.md)\n{spec_text}\n\n"
        f"## Repository Architecture (ARCHITECTURE.md)\n{arch_text}\n\n"
        f"## AST Repo Map (tinydb/)\n{ctx['repo_map_text']}\n\n"
        f"## Relevant Code Slices\n{slices_text or '(inspect via repo map above)'}"
        f"{feedback_section}"
    )

    models = get_model_chain("GEMINI_STAGE2_MODELS", "gemini-3.5-flash-lite,gemini-3.5-flash,gemma-4-31b-it")
    design_text = llm.call_gemini(
        stage="stage2_design",
        models=models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.15,
    )

    passed, msg, target_files = validate_design_gate(repo_root, design_text, skel)
    if not passed:
        design_text += f"\n\n---\n**Orchestrator Stage 2 Gate Check:** FAIL — {msg}\n"
    else:
        design_text += f"\n\n---\n**Orchestrator Stage 2 Gate Check:** PASS — {msg}\n"
    (artifacts_dir / "design.md").write_text(design_text, encoding="utf-8")
    return passed, msg, target_files

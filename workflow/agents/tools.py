"""Context-saving local AST repository tools and allowlisted SEARCH/REPLACE patcher.

Implements ADR-005 (list_directory, ast repo_map, read_file_lines, search_symbol,
SEARCH/REPLACE diff editing) and ADR-009 (path allowlist & subprocess timeouts).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

ALLOWED_WRITE_PREFIXES = ("tinydb/", "tests/")


def validate_allowed_path(repo_root: Path, rel_path: str) -> Path:
    """Enforce ADR-009 strict write allowlist: only tinydb/ and tests/ may be edited."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    if ".." in Path(norm).parts or Path(norm).is_absolute():
        raise PermissionError(f"Path traversal blocked: {rel_path}")
    if not norm.startswith(ALLOWED_WRITE_PREFIXES):
        raise PermissionError(
            f"Write blocked outside allowlist {ALLOWED_WRITE_PREFIXES}: {norm}"
        )
    full = (repo_root / norm).resolve()
    if repo_root.resolve() not in full.parents:
        raise PermissionError(f"Resolved path escapes repository: {rel_path}")
    return full


def list_directory(repo_root: Path, subdirs: tuple[str, ...] = ("tinydb", "tests")) -> list[str]:
    """List repository source/test files cleanly."""
    files: list[str] = []
    for sub in subdirs:
        base = repo_root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            files.append(p.relative_to(repo_root).as_posix())
    return files


def _format_args(args: ast.arguments) -> str:
    parts: list[str] = []
    for a in args.args:
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        parts.append(f"{a.arg}{ann}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for a in args.kwonlyargs:
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        parts.append(f"{a.arg}{ann}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


def repo_map(repo_root: Path, subdirs: tuple[str, ...] = ("tinydb",)) -> dict[str, Any]:
    """Generate a Python AST skeleton (classes, functions, signatures, line ranges)."""
    skeleton: dict[str, Any] = {}
    for rel in list_directory(repo_root, subdirs=subdirs):
        src = (repo_root / rel).read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            skeleton[rel] = {"error": "SyntaxError"}
            continue
        entries: list[dict[str, Any]] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(
                            {
                                "name": item.name,
                                "sig": f"def {item.name}({_format_args(item.args)})",
                                "lines": [item.lineno, item.end_lineno],
                            }
                        )
                entries.append(
                    {
                        "kind": "class",
                        "name": node.name,
                        "lines": [node.lineno, node.end_lineno],
                        "methods": methods,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entries.append(
                    {
                        "kind": "function",
                        "name": node.name,
                        "sig": f"def {node.name}({_format_args(node.args)})",
                        "lines": [node.lineno, node.end_lineno],
                    }
                )
        skeleton[rel] = entries
    return skeleton


def format_repo_map_text(skel: dict[str, Any]) -> str:
    """Compact human/LLM-readable rendering of the AST repo map."""
    lines: list[str] = []
    for rel, entries in skel.items():
        lines.append(f"## {rel}")
        if isinstance(entries, dict) and "error" in entries:
            lines.append(f"  (parse error: {entries['error']})")
            continue
        for e in entries:
            if e["kind"] == "class":
                lines.append(f"  class {e['name']} (L{e['lines'][0]}-L{e['lines'][1]}):")
                for m in e["methods"]:
                    lines.append(f"    {m['sig']}  # L{m['lines'][0]}-L{m['lines'][1]}")
            else:
                lines.append(f"  {e['sig']}  # L{e['lines'][0]}-L{e['lines'][1]}")
    return "\n".join(lines)


def read_file_lines(repo_root: Path, rel_path: str, start_line: int = 1, end_line: int = 200) -> str:
    """Read only lines start_line..end_line (1-indexed, inclusive) with line numbers."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    p = (repo_root / norm).resolve()
    if repo_root.resolve() not in p.parents or not p.exists():
        raise FileNotFoundError(f"File not found in repo: {rel_path}")
    all_lines = p.read_text(encoding="utf-8").splitlines()
    s = max(1, start_line)
    e = min(len(all_lines), end_line)
    return "\n".join(f"{i:4d}: {all_lines[i - 1]}" for i in range(s, e + 1))


def search_symbol(
    repo_root: Path, pattern: str, subdirs: tuple[str, ...] = ("tinydb", "tests"), max_hits: int = 30
) -> list[str]:
    """Find references to a symbol or regex across source/test files."""
    hits: list[str] = []
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    for rel in list_directory(repo_root, subdirs=subdirs):
        for idx, line in enumerate((repo_root / rel).read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{idx}: {line.strip()}")
                if len(hits) >= max_hits:
                    return hits
    return hits


def all_symbols_in_map(skel: dict[str, Any]) -> set[str]:
    """Return every class, function, and method name present in the AST repo map."""
    syms: set[str] = set()
    for entries in skel.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            syms.add(e["name"])
            for m in e.get("methods", []):
                syms.add(m["name"])
                syms.add(f"{e['name']}.{m['name']}")
    return syms


_SR_BLOCK_RE = re.compile(
    r"FILE:\s*([^\r\n]+)\r?\n"
    r"<<<<<<< SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> REPLACE",
    re.DOTALL,
)

_NEW_FILE_RE = re.compile(
    r"NEW_FILE:\s*([^\r\n]+)\r?\n```(?:python)?\r?\n(.*?)\r?\n```",
    re.DOTALL,
)


def apply_search_replace_blocks(repo_root: Path, llm_output: str) -> tuple[list[str], list[str]]:
    """Parse and apply allowlisted SEARCH/REPLACE blocks (and optional NEW_FILE blocks).

    Returns (modified_files, errors). Applies atomically per file after checking matches.
    """
    sr_matches = list(_SR_BLOCK_RE.finditer(llm_output))
    nf_matches = list(_NEW_FILE_RE.finditer(llm_output))

    if not sr_matches and not nf_matches:
        return [], ["No valid FILE:/SEARCH/REPLACE or NEW_FILE blocks found in LLM output."]

    modified: list[str] = []
    errors: list[str] = []
    staged_contents: dict[Path, str] = {}

    for m in sr_matches:
        rel_path = m.group(1).strip().strip("`")
        search_txt = m.group(2)
        replace_txt = m.group(3)
        try:
            full = validate_allowed_path(repo_root, rel_path)
        except PermissionError as exc:
            errors.append(str(exc))
            continue
        if not full.exists():
            errors.append(f"Target file does not exist: {rel_path}")
            continue

        current = staged_contents.get(full)
        if current is None:
            current = full.read_text(encoding="utf-8").replace("\r\n", "\n")

        norm_search = search_txt.replace("\r\n", "\n")
        norm_replace = replace_txt.replace("\r\n", "\n")

        count = current.count(norm_search)
        if count == 0:
            errors.append(
                f"SEARCH block not found verbatim in {rel_path}:\n{norm_search[:200]}"
            )
            continue
        if count > 1:
            errors.append(
                f"SEARCH block matched {count} times in {rel_path}; add more surrounding lines."
            )
            continue

        staged_contents[full] = current.replace(norm_search, norm_replace, 1)
        if rel_path not in modified:
            modified.append(rel_path)

    for m in nf_matches:
        rel_path = m.group(1).strip().strip("`")
        content = m.group(2).replace("\r\n", "\n") + "\n"
        try:
            full = validate_allowed_path(repo_root, rel_path)
        except PermissionError as exc:
            errors.append(str(exc))
            continue
        staged_contents[full] = content
        if rel_path not in modified:
            modified.append(rel_path)

    if errors:
        return [], errors

    for full, content in staged_contents.items():
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    return modified, []


def run_cmd(
    cmd: list[str], cwd: Path, timeout: int = 60, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess safely (list argv, no shell=True) with an explicit timeout."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )

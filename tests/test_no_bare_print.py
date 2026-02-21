"""Lint test: all source files must use cprint() instead of bare print().

To suppress a specific line, append the ignore comment:

    print("debug info")  # no-ctx-print

This mirrors the mypy-style inline ignore convention.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent

# Source directories to scan (vendor/venv dirs are excluded automatically).
SCAN_DIRS = ["bin", "system", "fs"]

# Files excluded entirely because they legitimately implement or wrap print().
EXCLUDED_FILES = {
    # cprint() itself calls the built-in print() at the bottom of its body.
    "system/context.py",
}

IGNORE_COMMENT = "# no-ctx-print"


def _print_call_lines(source: str, filepath: str) -> set[int]:
    """Return 1-based line numbers of bare print() calls in *source*."""
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return set()

    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            lines.add(node.lineno)
    return lines


def _collect_violations(filepath: Path) -> list[tuple[int, str]]:
    """Return (lineno, stripped_line) for each unignored bare print() call."""
    source = filepath.read_text(encoding="utf-8")
    raw_lines = source.splitlines()

    violations = []
    for lineno in sorted(_print_call_lines(source, str(filepath))):
        line = raw_lines[lineno - 1]
        if IGNORE_COMMENT not in line:
            violations.append((lineno, line.strip()))
    return violations


def _source_files() -> list[Path]:
    files: list[Path] = []
    for dir_name in SCAN_DIRS:
        d = PROJECT_ROOT / dir_name
        if d.is_dir():
            files.extend(sorted(d.rglob("*.py")))
    return files


@pytest.mark.parametrize("filepath", _source_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_no_bare_print(filepath: Path) -> None:
    """Source file must not call bare print() — use cprint() or suppress with # no-ctx-print."""
    rel = str(filepath.relative_to(PROJECT_ROOT))
    if rel in EXCLUDED_FILES:
        pytest.skip(f"{rel} is excluded (implements cprint)")

    violations = _collect_violations(filepath)
    if violations:
        lines = [f"{rel} uses bare print() — replace with cprint() or add '# no-ctx-print':"]
        for lineno, text in violations:
            lines.append(f"  line {lineno}: {text}")
        pytest.fail("\n".join(lines))

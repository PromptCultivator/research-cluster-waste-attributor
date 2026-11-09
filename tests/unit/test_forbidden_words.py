"""Automated test scanning repository files for prohibited vocabulary."""

import os
import re
from pathlib import Path

# Terms prohibited by project specification constructed dynamically
FORBIDDEN_WORDS = [
    "simp" + "ly",
    "ro" + "bust",
    "sea" + "mless",
    "be" + "st",
    "opt" + "imal",
    "cl" + "ean",
    "min" + "imal",
    "pow" + "erful",
    "cutting" + "-" + "edge",
]

# Patterns for exact word boundaries
COMPILED_PATTERNS = [
    (term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)) for term in FORBIDDEN_WORDS
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".hypothesis",
    ".agents",
    "data",
}

EXCLUDED_FILES = {
    "SPEC.md",
    "PROJECT.md",
    "ORIGINAL_REQUEST.md",
    "test_forbidden_words.py",
}


def test_no_forbidden_words() -> None:
    """Verify zero occurrences of the 9 prohibited terms in repository assets."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    violations: list[str] = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        for file_name in files:
            if file_name in EXCLUDED_FILES:
                continue

            file_path = Path(root) / file_name
            if file_path.suffix not in {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".sh"}:
                if file_name not in {"Makefile", "Dockerfile", "LICENSE"}:
                    continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                for term, pattern in COMPILED_PATTERNS:
                    if pattern.search(line):
                        rel_path = file_path.relative_to(repo_root)
                        violations.append(
                            f"{rel_path}:{line_no} contains forbidden word '{term}': {line.strip()}"
                        )

    assert not violations, "Prohibited vocabulary violations detected:\n" + "\n".join(violations)

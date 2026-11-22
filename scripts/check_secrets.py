#!/usr/bin/env python3.14
"""Scan the files git would track for token-shaped strings and literal secrets in recipe JSON.

    scripts/check_secrets.py

It reads every tracked or untracked-but-not-ignored file (so tmp/ is skipped) and reports the
file, the line and the kind of match. The matched value itself is never printed. A dedicated
scanner (gitleaks, trufflehog) knows many more formats; this is the check that runs everywhere
without installing anything.

Exit status: 0 when nothing is found, 1 otherwise.
"""

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
PATTERNS = {
    "Slack token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "Slack webhook": re.compile(r"hooks\.slack\.com/services/[A-Z0-9/]{10,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "bearer token": re.compile(r"(?i:bearer)\s+[A-Za-z0-9._-]{25,}"),
    # A webhook address starts a recipe without any credential: it is a secret of its own.
    "Workato webhook address": re.compile(
        r"webhooks\.(?:[a-z]+\.)?workato(?:app)?\.(?:com|cn)/webhooks/rest/[0-9A-Fa-f-]{20,}"
    ),
    "secret assigned in text": re.compile(
        r"(?i)\b(?:token|secret|api[_-]?key|password)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{20,}"
    ),
    "Workato API token": re.compile(r"\bwrk[A-Za-z0-9]*_[A-Za-z0-9_-]{30,}"),
    "API key (sk-)": re.compile(r"(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{32,}"),
}
SECRET_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
NOT_VALUES = {
    "hint", "label", "title", "description", "name", "type", "control_type", "help", "placeholder",
}  # fmt: skip
MIN_SECRET_LENGTH = 12
SHOWN_PATH_LENGTH = 60


def candidate_files() -> list[Path]:
    """Return every file git tracks or would track."""
    return [ROOT / path for path in wkrepo.tracked_files()]


def is_literal(value: str) -> bool:
    """Tell a literal value from a datapill, a formula or a sentence."""
    dynamic = "_dp(" in value or "#{" in value or value.startswith("=") or " " in value.strip()
    return not dynamic and len(value) >= MIN_SECRET_LENGTH and not value.startswith("{")


def literal_secrets(node: Any, path: str = "") -> Iterator[str]:
    """Yield the JSON path of every secret-looking key that holds a literal value."""
    if isinstance(node, dict):
        for key, value in node.items():
            named_secret = SECRET_KEY.search(key) and key not in NOT_VALUES
            if isinstance(value, str) and named_secret and is_literal(value):
                yield f"{path}/{key}"
            yield from literal_secrets(value, f"{path}/{key}")
    elif isinstance(node, list):
        for item in node:
            yield from literal_secrets(item, path)


def findings(file: Path) -> Iterator[str]:
    """Yield one report line per finding in a file; a file that is not text yields nothing."""
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return
    relative = file.relative_to(ROOT).as_posix()
    for number, line in enumerate(text.split("\n"), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                yield f"{relative}:{number}: {kind}"
    if relative.endswith(".recipe.json"):
        try:
            recipe = json.loads(text)
        except ValueError:
            return
        for where in literal_secrets(recipe):
            yield f"{relative}: literal value under {where[-SHOWN_PATH_LENGTH:]}"


def main(argv: list[str] | None = None) -> int:
    """Scan every candidate file; return the exit status."""
    cli.parser(__doc__).parse_args(argv)
    files = candidate_files()
    this_script = Path(__file__).resolve()
    found = 0
    for file in files:
        if file.resolve() == this_script or not file.is_file():
            continue
        for line in findings(file):
            print(line)
            found += 1
    print(f"scanned {len(files)} files, {found} finding(s)")
    return cli.EXIT_FINDINGS if found else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

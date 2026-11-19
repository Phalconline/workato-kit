#!/usr/bin/env python3.14
"""Run every offline check of the repository. `make check` and CI call this script.

    scripts/check.py

In order: Ruff lint, Ruff format, mypy, the unit tests, the JSON files and the registry, the
generated harness files, the Markdown links, the secret patterns, the files of the kit (they may
hold nothing of a workspace) and the ignore rules. A failed check does not stop the ones after
it. Nothing is written except temporary test fixtures.

No Workato access, no credentials and no network are needed. Ruff and mypy are taken from .venv;
`make dev` installs them there.

Exit status: 0 every check passed; 1 at least one failed; 2 Ruff and mypy are not installed, or
the interpreter is not Python 3.14.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
TOOLS = ROOT / ".venv" / "bin"
PYTHON_SERIES = (3, 14)  # any patch release; .python-version and pyproject.toml say the same
SOURCES = ("scripts", "tests")
# Paths that git must ignore: personal caches and the files that hold credentials.
MUST_BE_IGNORED = (
    "tmp/example",
    "profiles.env",
    "master.key",
    ".env",
    ".claude/settings.local.json",
    ".venv/bin/python",
)
type Step = tuple[str, list[str]]  # what is checked, the command that checks it


def steps(python: str) -> list[Step]:
    """Return every check as a label and the command to run from the repository root."""
    script = [python, "-I", "-B"]
    return [
        ("Lint (ruff check)", [str(TOOLS / "ruff"), "check", *SOURCES]),
        ("Format (ruff format)", [str(TOOLS / "ruff"), "format", "--check", *SOURCES]),
        ("Types (mypy)", [str(TOOLS / "mypy")]),
        ("Unit tests", [*script, "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
        ("JSON files and registry", [*script, "scripts/check_data.py"]),
        ("Generated harness files", [*script, "scripts/sync_harness.py", "--check"]),
        ("Markdown links", [*script, "scripts/check_links.py"]),
        ("Secret patterns", [*script, "scripts/check_secrets.py"]),
        ("Kit files hold no workspace data", [*script, "scripts/check_kit_files.py"]),
    ]


def not_ignored() -> list[str]:
    """Return the paths of MUST_BE_IGNORED that git would not ignore."""
    git = wkrepo.executable("git")
    return [
        path
        for path in MUST_BE_IGNORED
        if subprocess.run([git, "check-ignore", "-q", path], cwd=ROOT, check=False).returncode
    ]


def main(argv: list[str] | None = None) -> int:
    """Run every check and name the ones that failed; return the exit status."""
    cli.parser(__doc__).parse_args(argv)
    version = ".".join(str(part) for part in sys.version_info[:3])
    if tuple(sys.version_info[:2]) != PYTHON_SERIES:
        wanted = ".".join(str(part) for part in PYTHON_SERIES)
        raise cli.Error(
            f"the tooling runs on Python {wanted}; this is {version} (docs/setup/README.md)"
        )
    missing = [tool for tool in ("ruff", "mypy") if not (TOOLS / tool).is_file()]
    if missing:
        raise cli.Error(f"{' and '.join(missing)} not found in .venv: run `make dev` first")

    print(f"Offline repository checks, Python {version}", flush=True)
    (ROOT / "tmp").mkdir(exist_ok=True)
    # Scripts started by the tests find the same interpreter first on PATH.
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    failed = []
    for label, command in steps(sys.executable):
        print(f"\n== {label} ==", flush=True)
        if subprocess.run(command, cwd=ROOT, env=env, check=False).returncode != 0:
            failed.append(label)
    print("\n== Ignore rules ==", flush=True)
    failed += [f"Ignore rule: {path}" for path in not_ignored()]

    if failed:
        print("\nFAILED: " + ", ".join(failed), file=sys.stderr)
        return cli.EXIT_FINDINGS
    print("\nAll offline checks passed. Access to Workato and the harness hooks were not tested.")
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

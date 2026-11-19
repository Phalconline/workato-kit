"""Helpers shared by the test modules. Test modules never import one another."""

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import patch

from lib import cli, wkrepo

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKSPACE = "acme"
# The registry of the workspace the tests invent. No test reads the workspace of the repository.
REGISTRY: dict[str, Any] = {
    "description": "A workspace for the tests.",
    "maintainer": "the maintainer",
    "app_url": "https://app.workato.com",
    "company_domains": ["acme.example"],
    "environments": {
        "dev": {"profile": "acme-dev", "workspace": "Acme (Dev)"},
        "prod": {"profile": "acme-prod", "workspace": "Acme"},
    },
    "projects": {
        "sales-orders": {
            "name": "Sales Orders",
            "snapshots": True,
            "dev": {"project_id": 1001, "folder_id": 2001},
            "prod": {"project_id": 1002, "folder_id": 2002},
        },
        "common": {
            "name": "Common",
            "snapshots": True,
            "shared_connections": True,
            "dev": {"project_id": 1003, "folder_id": 2003},
            "prod": {"project_id": 1004, "folder_id": 2004},
        },
        "sandbox": {
            "name": "Sandbox",
            "snapshots": False,
            "dev": {"project_id": 1005, "folder_id": 2005},
        },
    },
}


class Result(NamedTuple):
    """What one call of a script's main() produced."""

    code: int
    out: str
    err: str


def run_main(main: cli.Main, *argv: str, stdin: str | None = None) -> Result:
    """Call main(argv) the way `cli.run` does and capture what it prints.

    A `cli.Error` becomes exit status 2 with its message on stderr, and so does a bad argument;
    any other exception is a bug and propagates to the test.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        if stdin is not None:
            stack.enter_context(patch.object(sys, "stdin", io.StringIO(stdin)))
        try:
            code = cli.invoke(main, list(argv))
        except SystemExit as stop:  # argparse: a bad argument (2) or --help (0)
            code = stop.code if isinstance(stop.code, int) else 1
    return Result(code, out.getvalue(), err.getvalue())


def run_script(name: str, *args: str, **options: Any) -> subprocess.CompletedProcess[str]:
    """Run scripts/<name>.py in a new process with the interpreter that runs the tests."""
    command = [sys.executable, "-I", "-B", str(SCRIPTS / f"{name}.py"), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False, **options)


def temp_dir(test: unittest.TestCase, prefix: str = "test-") -> Path:
    """Return a new empty folder that is removed when the test ends."""
    folder = tempfile.TemporaryDirectory(prefix=prefix)
    test.addCleanup(folder.cleanup)
    return Path(folder.name).resolve()


def write_json(path: Path, data: Any) -> Path:
    """Write a JSON fixture, creating the folders above it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def start(test: unittest.TestCase, *patches: Any) -> None:
    """Start every patch and stop it when the test ends."""
    for item in patches:
        item.start()
        test.addCleanup(item.stop)


def fake_repository(test: unittest.TestCase) -> Path:
    """Point `wkrepo` at a new, empty repository root that has no workspace yet."""
    root = temp_dir(test, "repo-")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("WK_")}
    start(
        test,
        patch.object(wkrepo, "ROOT", root),
        patch.object(wkrepo, "WORKSPACES", root / "workato" / "workspaces"),
        patch.object(wkrepo, "DEV_CACHE", root / "tmp" / "wk" / "dev"),
        patch.dict(os.environ, environment, clear=True),
    )
    return root


def fake_workspace(test: unittest.TestCase, registry: dict[str, Any] | None = None) -> Path:
    """Point `wkrepo` at a new repository root with one workspace; return that root.

    The workspace is `acme` with the registry above, or with the one given.
    """
    root = fake_repository(test)
    folder = root / "workato" / "workspaces" / WORKSPACE
    write_json(folder / wkrepo.REGISTRY_NAME, registry or copy.deepcopy(REGISTRY))
    return root

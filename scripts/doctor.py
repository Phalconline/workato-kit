#!/usr/bin/env python3.14
"""Check your personal setup: the offline checks, then read-only access to Workato.

    scripts/doctor.py

First the offline checks (`scripts/check.py`, the same as `make check`). Then, with `wk`: is it
installed, is the lint plugin registered, and for the Dev and the Prod profile of the registry:
does the profile exist, does it reach the workspace the registry names, and may its API client
read what the scripts read (recipes, folders, connections, project properties). It starts no
recipe and no job and changes nothing in Workato. No token and no property value is printed.

Without a workspace folder it checks the tools only and says how to create one.

Not covered: the MCP sign-ins and the guard hook of your harness (docs/setup/README.md).

Exit status: 0 everything works; 1 a check failed or something is missing.
"""

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
PLUGIN = re.compile(r"^recipe-lint\b", re.MULTILINE)
OK, FAIL, NOTE = "ok  ", "FAIL", "note"
type Check = tuple[str, str]  # OK, FAIL or NOTE, and what was checked or how to fix it


def offline_checks() -> bool:
    """Run scripts/check.py with this interpreter; True when every check passed."""
    command = [sys.executable, "-I", "-B", str(ROOT / "scripts" / "check.py")]
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def plugin_check() -> Check:
    """Check that the recipe-lint plugin is registered with `wk`."""
    try:
        registered = bool(PLUGIN.search(wkrepo.run_wk("plugins", "list")))
    except cli.Error as error:
        return FAIL, f"wk plugins list failed: {error}"
    if registered:
        return OK, "recipe-lint plugin"
    return FAIL, "recipe-lint is not registered with wk; run: wk plugins install recipe-lint"


def profile_checks(env: str) -> list[Check]:
    """Check that the profile of an environment exists and reaches the registry's workspace."""
    profile = wkrepo.profile(env)
    label = f"{env} profile ({profile})"
    try:
        known = wkrepo.wk_profile(profile)
        status = wkrepo.wk_json(profile, "auth", "status")
    except cli.Error as error:
        return [(FAIL, f"{label}: {error}")]
    if not status.get("connected"):
        return [(FAIL, f"{label} cannot reach Workato; sign in again: docs/setup/workato.md")]
    checks = [(OK, f"{label} reaches Workato")]
    signed_in = str(known.get("environment") or "").lower()
    if signed_in in wkrepo.ENVIRONMENTS and signed_in != env:
        swapped = (
            f"{label} is signed in to {signed_in} according to wk: the two profiles of the "
            "registry look swapped"
        )
        checks.append((FAIL, swapped))
    expected = wkrepo.environment(env).get("workspace")
    reached = status.get("workspace") or known.get("workspace")
    if reached != expected:
        checks.append(
            (FAIL, f"{label} reaches the workspace '{reached}'; the registry says '{expected}'")
        )
    if known.get("store_type") == "file":
        checks.append(
            (
                NOTE,
                f"{label} keeps its token as plain text in profiles.env; keep that file private",
            )
        )
    return checks


def probe(label: str, read: Callable[[], object]) -> Check:
    """Run one read and say whether the API client may do it."""
    try:
        read()
    except cli.Error as error:
        return FAIL, f"{label}: {error}"
    return OK, label


def privilege_checks(env: str) -> list[Check]:
    """Check that the API client of an environment may read what the scripts read."""
    profile = wkrepo.profile(env)
    projects = [entry[env] for entry in wkrepo.registry()["projects"].values() if env in entry]
    checks = [
        probe(
            f"{env}: reads recipes",
            lambda: wkrepo.wk_json(profile, "recipes", "list", "--per-page", "1"),
        ),
        probe(f"{env}: reads projects and folders", lambda: wkrepo.list_projects(profile)),
        probe(
            f"{env}: reads connections",
            lambda: wkrepo.wk_json(profile, "connections", "list", "--per-page", "1"),
        ),
    ]
    if projects:
        project_id = projects[0]["project_id"]
        # The values come back with the names; only the fact that the read worked is used.
        checks.append(
            probe(
                f"{env}: reads project properties",
                lambda: wkrepo.property_names(env, project_id),
            )
        )
    return checks


def workspace_checks() -> list[Check]:
    """Return the checks of both profiles of the workspace, or a note when there is none yet."""
    if not wkrepo.workspaces():
        return [(NOTE, wkrepo.NO_WORKSPACE)]
    checks: list[Check] = []
    for env in wkrepo.ENVIRONMENTS:
        of_profile = profile_checks(env)
        checks += of_profile
        if of_profile[0][0] == OK:
            checks += privilege_checks(env)
    dev, prod = (wkrepo.profile(env) for env in wkrepo.ENVIRONMENTS)
    try:
        if wkrepo.base_url(dev) != wkrepo.base_url(prod):
            checks.append((FAIL, f"{dev} and {prod} are in different data centers"))
        active = [item.get("name") for item in wkrepo.profiles() if item.get("active")]
        if active == [prod]:
            checks.append(
                (NOTE, f"wk's default profile is the Prod one; make Dev the default: {dev}")
            )
    except cli.Error as error:
        checks.append((FAIL, str(error)))
    return checks


def main(argv: list[str] | None = None) -> int:
    """Run every check and print one line per result; return the exit status."""
    cli.parser(__doc__).parse_args(argv)
    offline = offline_checks()

    print("\nWorkato CLI access (read-only)")
    if shutil.which("wk") is None:
        checks = [(FAIL, "wk is not installed; see docs/setup/workato.md")]
    else:
        try:
            checks = [plugin_check(), *workspace_checks()]
        except cli.Error as error:
            checks = [(FAIL, str(error))]
    for status, text in checks:
        print(f"  {status}  {text}")
    if not offline:
        print("\nThe offline checks failed: see their output above.")
    failed = not offline or any(status == FAIL for status, _ in checks)
    return cli.EXIT_FINDINGS if failed else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

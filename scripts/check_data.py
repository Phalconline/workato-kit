#!/usr/bin/env python3.14
"""Check that every JSON file git would track parses, and that the registry is well formed.

    scripts/check_data.py

Offline: it only reads files. A duplicate key or a non-standard number (NaN, Infinity) counts as
invalid. Document contents are never printed, because a malformed file could hold a credential;
for a registry the script names the field that is wrong, never its value.

A repository without a workspace yet passes: the registry is checked once
scripts/init_workspace.py has written one.

Exit status: 0 when every file is valid, 1 otherwise.
"""

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
WORKSPACES = wkrepo.WORKSPACES.relative_to(ROOT).as_posix()
ENVIRONMENTS = set(wkrepo.ENVIRONMENTS)
ID_FIELDS = ("project_id", "folder_id")
# Every key a registry may hold. An unknown key is an error: a typo must not pass silently.
REGISTRY_KEYS = {
    "description", "maintainer", "app_url", "company_domains", "lint_literal_patterns",
    "environments", "projects", "notes",
}  # fmt: skip
ENVIRONMENT_KEYS = {"profile", "workspace", "notes"}
PROJECT_KEYS = {
    "name", "snapshots", "dev", "prod", "shared_connections", "dev_only_properties",
    "lint_checks", "lint_guard_property", "lint_guard_parameter", "lint_guard_exempt",
    "tables",
    "confluence_main_page", "jira", "notes",
}  # fmt: skip
NAME_LISTS = ("dev_only_properties", "lint_checks", "lint_guard_exempt")
TEXT_FIELDS = (
    "lint_guard_property", "lint_guard_parameter", "confluence_main_page", "jira", "notes",
)  # fmt: skip
GUARD_CHECK = "NO_GUARD_PROPERTY"


class RegistryError(ValueError):
    """The registry lacks the structure the scripts rely on. Its text holds no value of a field."""


def known_keys(where: str, data: dict[str, Any], allowed: set[str]) -> None:
    """Refuse a key that no script reads."""
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RegistryError(f"{where}: unknown key {', '.join(unknown)}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object, refusing a key that appears twice."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> Any:
    """Refuse NaN and Infinity, which are not JSON."""
    raise ValueError(f"Invalid JSON constant: {value}")


def read_json(path: Path) -> Any:
    """Parse a JSON file strictly: no duplicate keys, no non-standard numbers."""
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )


def validate_environments(environments: Any) -> None:
    """Check the environments table: exactly dev and prod, each with a profile and a workspace."""
    if not isinstance(environments, dict) or set(environments) != ENVIRONMENTS:
        raise RegistryError("environments must be exactly dev and prod")
    for name, env in environments.items():
        if not isinstance(env, dict):
            raise RegistryError(f"{name}: must be an object")
        known_keys(name, env, ENVIRONMENT_KEYS)
        for key in ("profile", "workspace"):
            if not isinstance(env.get(key), str) or not env[key].strip():
                raise RegistryError(f"{name}: {key} must be non-empty text")
        if not wkrepo.PROFILE_NAME.fullmatch(env["profile"]):
            raise RegistryError(f"{name}: profile may hold letters, digits, . _ - only")


def validate_workspace_settings(data: dict[str, Any]) -> None:
    """Check the settings of the workspace itself."""
    known_keys("registry", data, REGISTRY_KEYS)
    for key in ("description", "maintainer", "notes"):
        if not isinstance(data.get(key, ""), str):
            raise RegistryError(f"{key} must be text")
    app_url = data.get("app_url", wkrepo.US_APP_HOST)
    if not isinstance(app_url, str) or not wkrepo.workato_address(app_url):
        # The harness files send every person's MCP sign-in to this address.
        raise RegistryError("app_url must be the https address of a Workato web app, alone")
    domains = data.get("company_domains", [])
    if not isinstance(domains, list) or not all(
        isinstance(domain, str) and wkrepo.DOMAIN.fullmatch(domain) for domain in domains
    ):
        raise RegistryError("company_domains must be a list of lower-case domains")
    patterns = data.get("lint_literal_patterns", {})
    if not isinstance(patterns, dict) or not all(
        isinstance(label, str) and expression_compiles(expression)
        for label, expression in patterns.items()
    ):
        raise RegistryError("lint_literal_patterns must map a label to a regular expression")


def expression_compiles(expression: Any) -> bool:
    """Tell whether a value is a regular expression that is not empty."""
    if not isinstance(expression, str) or not expression:
        return False
    try:
        re.compile(expression)
    except re.error:
        return False
    return True


def validate_options(slug: str, project: dict[str, Any]) -> None:
    """Check the optional settings of a project entry."""
    if type(project.get("shared_connections", False)) is not bool:
        raise RegistryError(f"{slug}: shared_connections must be boolean")
    for name in NAME_LISTS:
        value = project.get(name, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise RegistryError(f"{slug}: {name} must be a list of names")
    for name in TEXT_FIELDS:
        if not isinstance(project.get(name, ""), str):
            raise RegistryError(f"{slug}: {name} must be text")
    checks = set(project.get("lint_checks", []))
    if checks - set(wkrepo.LINT_CHECKS):
        raise RegistryError(f"{slug}: lint_checks knows {', '.join(wkrepo.LINT_CHECKS)} only")
    guard = (project.get("lint_guard_property"), project.get("lint_guard_parameter"))
    if GUARD_CHECK in checks and not all(guard):
        raise RegistryError(
            f"{slug}: {GUARD_CHECK} needs lint_guard_property and lint_guard_parameter"
        )
    if guard[1] and not expression_compiles(guard[1]):
        raise RegistryError(f"{slug}: lint_guard_parameter must be a regular expression")
    tables = project.get("tables", {})
    named = isinstance(tables, dict) and all(
        isinstance(table_id, str) and table_id.isdigit() and isinstance(name, str) and name
        for table_id, name in tables.items()
    )
    if not named:
        raise RegistryError(f"{slug}: tables must map a table id to its name")


def validate_project(slug: str, project: Any, used: dict[str, dict[str, set[int]]]) -> None:
    """Check one project entry; `used` collects the ids seen so far in each environment."""
    if not wkrepo.SLUG.fullmatch(slug) or slug in wkrepo.RESERVED_SLUGS:
        raise RegistryError(
            f"{slug}: a slug is lower-case words joined by dashes, and not reserved"
        )
    if not isinstance(project, dict):
        raise RegistryError(f"{slug}: must be an object")
    known_keys(slug, project, PROJECT_KEYS)
    if not isinstance(project.get("name"), str) or not project["name"]:
        raise RegistryError(f"{slug}: project needs a name")
    if type(project.get("snapshots")) is not bool:
        raise RegistryError(f"{slug}: snapshots must be boolean")
    if "dev" not in project or (project["snapshots"] and "prod" not in project):
        raise RegistryError(f"{slug}: needs dev ids, and prod ids when snapshots is true")
    validate_options(slug, project)
    for env in sorted(ENVIRONMENTS & set(project)):
        if not isinstance(project[env], dict):
            raise RegistryError(f"{slug}/{env}: must be an object")
        known_keys(f"{slug}/{env}", project[env], set(ID_FIELDS))
        for id_field in ID_FIELDS:
            value = project[env].get(id_field)
            if type(value) is not int or value <= 0 or value in used[env][id_field]:
                raise RegistryError(
                    f"{slug}/{env}: {id_field} must be positive and unique in that environment"
                )
            used[env][id_field].add(value)


def validate_registry(data: Any) -> None:
    """Raise RegistryError when the registry lacks the structure the scripts rely on."""
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        raise RegistryError("the registry needs a projects object")
    validate_workspace_settings(data)
    validate_environments(data.get("environments"))
    used: dict[str, dict[str, set[int]]] = {
        env: {id_field: set() for id_field in ID_FIELDS} for env in ENVIRONMENTS
    }
    for slug, project in data["projects"].items():
        validate_project(slug, project, used)


def tracked_json_files() -> list[str]:
    """Return the JSON files git tracks or would track, relative to the repository root."""
    git = wkrepo.executable("git")
    listed = subprocess.run(
        [git, "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted({path for path in listed.stdout.split("\0") if path.endswith(".json")})


def is_registry(relative: str) -> bool:
    """Tell whether a path is the registry of a workspace folder."""
    path = PurePosixPath(relative)
    return path.name == wkrepo.REGISTRY_NAME and path.parent.parent.as_posix() == WORKSPACES


def missing_copies(relative: str, registry: dict[str, Any]) -> list[str]:
    """Return the snapshot projects of a registry whose Prod copy is not in the repository yet."""
    projects = (ROOT / relative).parent / "projects"
    return [
        slug
        for slug, entry in registry["projects"].items()
        if entry.get("snapshots") and not (projects / slug / "index.json").is_file()
    ]


def main(argv: list[str] | None = None) -> int:
    """Validate every JSON file and each registry; return the exit status."""
    cli.parser(__doc__).parse_args(argv)
    paths = tracked_json_files()
    failed = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():  # a tracked removal is not a malformed document
            continue
        try:
            data = read_json(path)
            if is_registry(relative):
                validate_registry(data)
                missing = missing_copies(relative, data)
                if missing:
                    print(
                        f"note: no Prod copy yet of {', '.join(missing)}: "
                        "run scripts/sync_recipes.py prod"
                    )
        except RegistryError as error:
            failed.append(relative)
            print(f"Invalid registry: {relative}: {error}", file=sys.stderr)
        except (OSError, ValueError, TypeError) as error:
            failed.append(relative)
            # Never print an excerpt or a duplicate key's value: it can be a credential.
            print(f"Invalid JSON: {relative} ({type(error).__name__})", file=sys.stderr)
    if not any(is_registry(relative) for relative in paths):
        print("No workspace yet: scripts/init_workspace.py creates one.")
    print(f"Checked {len(paths)} JSON files; {len(failed)} failure(s).")
    return cli.EXIT_FINDINGS if failed else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

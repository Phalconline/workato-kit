#!/usr/bin/env python3.14
"""Sync recipe JSON from Workato into the repository. Read-only towards Workato.

    scripts/sync_recipes.py prod                        every snapshot project in Prod
    scripts/sync_recipes.py prod --check                write nothing; exit 1 if the copy is stale
    scripts/sync_recipes.py dev sales-orders            one Dev project, into your personal cache
    scripts/sync_recipes.py dev --recipe <id> ...       only these recipes (after a push)

Only the Prod copy is kept in git (workato/workspaces/<workspace>/projects/<project>/). Dev changes
at every push, so its copy goes to the git-ignored cache tmp/wk/dev/<project>/, where the lint and
the index scripts read it. Which projects are synced, with which wk profile and into which folder
comes from the registry.

It uses `wk recipes pull <id>` only: one GET per recipe and no export manifest. Never use the
package commands for this: `wk pull`, `wk diff` and `wk clone` each leave an export manifest
behind in Workato, and `wk push` imports a whole package.

Without a project argument it syncs every managed project (`"snapshots": true` in the registry).
Name a project to copy a Dev-only one into your cache. A project that the registry does not have
in the environment is skipped, and the script says so.

Layout of a project folder: <workato folders>/<recipe id>-<name>.recipe.json, plus index.json
with the folders, the recipes (id, name, folder, file, match_key, version, running), the
connections in the project's folders (id, name, application, folder, authorized) and the names of
the project properties. Property values and credentials are never read into the repository.
`match_key` (folder plus name, without ids) is the same for the Dev and the Prod copy of a recipe.

Each project is fetched and checked before its first file is written: a failed pull leaves that
project and the ones after it unchanged, while projects synced earlier in the same run stay
refreshed. If a run dies while writing, run it again. A full sync removes the files of deleted
recipes. `--recipe` pulls only those recipes: the files and index entries of the others stay as
they are, while the folders, connections and property names in index.json are refreshed. A
difference found by --check means the copy is stale, not that Prod was edited directly.

Exit status: 0 done, or with --check nothing differs; 1 with --check when the copy is stale;
2 when Workato could not be read or a recipe id is unknown.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
PROJECT_ROOT = "(project root)"
UNNAMED = "unnamed"  # stands in for a name without a letter or a digit: a path never gets empty
type State = tuple[list[Json], list[Json]]  # the folders and the recipes of one project


def remote_state(prof: str, entry: Json) -> State:
    """Return the folders and the recipes of one project as they are in Workato now."""
    folders: list[Json] = []
    recipes: list[Json] = []
    for folder_id, names in wkrepo.walk_folders(prof, entry["folder_id"]):
        rel = "/".join(wkrepo.slug(name) or UNNAMED for name in names)
        label = " / ".join(names) or PROJECT_ROOT
        folders.append({"id": folder_id, "name": label, "path": rel or "."})
        for recipe in wkrepo.list_recipes(prof, folder_id):
            name_slug = wkrepo.slug(recipe["name"]) or UNNAMED
            file = f"{recipe['id']}-{name_slug}.recipe.json"
            recipes.append(
                {
                    "id": recipe["id"],
                    "name": recipe["name"],
                    "folder": label,
                    "file": f"{rel}/{file}" if rel else file,
                    "match_key": f"{rel}/{name_slug}" if rel else name_slug,
                    "running": bool(recipe.get("running")),
                }
            )
    return folders, sorted(recipes, key=lambda recipe: recipe["file"])


def pull(prof: str, recipe_id: int, scratch: Path) -> bytes:
    """Return the JSON of one recipe exactly as `wk recipes pull` writes it."""
    target = scratch / f"{recipe_id}.json"
    wkrepo.wk(prof, "recipes", "pull", str(recipe_id), "-o", str(target))
    return target.read_bytes()


def recipe_version(data: bytes) -> int | None:
    """Return the version of a pulled recipe; refuse an answer that is not a recipe document."""
    try:
        recipe = json.loads(data)
    except ValueError:
        recipe = None
    if not isinstance(recipe, dict) or not isinstance(recipe.get("code"), dict):
        raise cli.Error("a recipe pull did not return a recipe document with a code object")
    version: int | None = recipe.get("version")
    return version


def apply(base: Path, payloads: dict[str, bytes], removed: list[str], index_text: str) -> None:
    """Write a fetched project. Every read has succeeded before this is called."""
    base.mkdir(parents=True, exist_ok=True)
    for rel in removed:
        (base / rel).unlink()
    for rel, data in payloads.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # index.json last: it never lists a file that was not written.
    (base / "index.json").write_text(index_text, encoding="utf-8")
    for folder in sorted((path for path in base.rglob("*") if path.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()


def pull_selected(prof: str, base: Path, selected: list[Json]) -> tuple[dict[str, bytes], Json]:
    """Pull the selected recipes; return their bytes by file and which files are new or changed."""
    payloads: dict[str, bytes] = {}
    changes: Json = {"new": [], "changed": [], "removed": []}
    with tempfile.TemporaryDirectory(prefix="sync-pull-") as scratch:
        for recipe in selected:
            data = pull(prof, recipe["id"], Path(scratch))
            recipe["version"] = recipe_version(data)
            payloads[recipe["file"]] = data
            path = base / recipe["file"]
            if not path.exists():
                changes["new"].append(recipe["file"])
            elif path.read_bytes() != data:
                changes["changed"].append(recipe["file"])
    return payloads, changes


def project_index(
    env: str, entry: Json, prof: str, folders: list[Json], recipes: list[Json]
) -> Json:
    """Build index.json of a project from what Workato returned."""
    folder_names = {folder["id"]: folder["name"] for folder in folders}
    connections = sorted(
        (
            {
                "id": connection["id"],
                "name": connection["name"],
                "application": connection.get("application"),
                "folder": folder_names[connection["folder_id"]],
                "authorized": connection.get("authorization_status") == "success",
            }
            for connection in wkrepo.list_connections(prof)
            if connection.get("folder_id") in folder_names
        ),
        key=lambda connection: connection["name"],
    )
    try:
        properties = wkrepo.property_names(env, entry[env]["project_id"])
    except cli.Error as error:
        hint = ""
        if "HTTP 401" in str(error) or "HTTP 403" in str(error):
            hint = (
                f". The API client of the {env} profile must be allowed to read project "
                "properties: see docs/setup/workato.md"
            )
        raise cli.Error(f"{error}{hint}") from None
    return {
        "project": entry["name"],
        "environment": env,
        "project_id": entry[env]["project_id"],
        "folders": folders,
        "recipes": recipes,
        "connections": connections,
        "properties": properties,
    }


def warnings(env: str, index: Json) -> list[str]:
    """Return what a person should know about the synced project."""
    keys = [recipe["match_key"] for recipe in index["recipes"]]
    found = [
        f"two recipes share the folder and name '{key}': they cannot be paired across environments"
        for key in sorted({key for key in keys if keys.count(key) > 1})
    ]
    found += [
        f"connection not authorized in {env}: {connection['name']}"
        for connection in index["connections"]
        if not connection["authorized"]
    ]
    return found


def shown(path: Path) -> str:
    """Return a path relative to the repository where possible, for messages."""
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def sync_project(
    env: str, slug: str, only: set[int], check: bool, state: State | None = None
) -> int:
    """Sync one project and return how many things differed (files plus the index)."""
    entry = wkrepo.project(slug)
    if env not in entry:
        print(f"{env} {slug}: not deployed to this environment, skipped")
        return 0
    prof = wkrepo.profile(env)
    base = wkrepo.snapshot_dir(env, slug)
    folders, recipes = state if state is not None else remote_state(prof, entry[env])
    recipes = [dict(recipe) for recipe in recipes]
    selected = [recipe for recipe in recipes if not only or recipe["id"] in only]
    missing = only - {recipe["id"] for recipe in selected}
    if missing:
        raise cli.Error(f"recipe ids not found in {env} {slug}: {sorted(missing)}")
    index_path = base / "index.json"
    old_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else None
    if only and old_index is None:
        print(f"{env} {slug}: no local copy yet, pulling the whole project")
        only, selected = set(), recipes

    # Connections and property names first: a missing privilege then fails in seconds, not after
    # every recipe was pulled. The pull fills in the versions of the same recipe entries.
    index = project_index(env, entry, prof, folders, recipes)
    payloads, changes = pull_selected(prof, base, selected)
    if only and old_index is not None:
        # Only the selected recipes were pulled: the others keep the file and version on disk.
        kept = [recipe for recipe in old_index["recipes"] if recipe["id"] not in only]
        index["recipes"] = sorted(kept + selected, key=lambda recipe: recipe["file"])
        candidates = {recipe["file"] for recipe in old_index["recipes"] if recipe["id"] in only}
    else:
        candidates = {path.relative_to(base).as_posix() for path in base.rglob("*.recipe.json")}
    wanted = {recipe["file"] for recipe in index["recipes"]}
    changes["removed"] = sorted(rel for rel in candidates - wanted if (base / rel).exists())

    text = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
    index_stale = not index_path.exists() or index_path.read_text(encoding="utf-8") != text
    total = sum(len(files) for files in changes.values())
    if not check and (index_stale or total):
        apply(base, payloads, changes["removed"], text)

    scope = f"{len(selected)} of {len(recipes)}" if only else str(len(recipes))
    print(
        f"{env} {slug}: {scope} recipes pulled | new {len(changes['new'])}, "
        f"changed {len(changes['changed'])}, removed {len(changes['removed'])}"
        + (", index.json differs" if index_stale and not total else "")
    )
    for kind, files in changes.items():
        for file in files:
            print(f"   {kind:8s} {shown(base)}/{file}")
    for warning in warnings(env, index):
        print(f"   WARNING  {warning}")
    return total + (1 if index_stale else 0)


def plan(env: str, slugs: list[str], requested: set[int]) -> list[tuple[str, set[int], State]]:
    """Read each project once and decide which recipe ids belong to which project."""
    plans = []
    found: set[int] = set()
    for slug in slugs:
        entry = wkrepo.project(slug)
        if env not in entry:
            print(
                f"{env} {slug}: the registry has no {env} ids for this project, skipped (after "
                "its first deployment run scripts/init_workspace.py again)"
            )
            continue
        state = remote_state(wkrepo.profile(env), entry[env])
        ids = requested & {recipe["id"] for recipe in state[1]}
        found |= ids
        if not requested or ids:
            plans.append((slug, ids, state))
    if requested - found:
        raise cli.Error(
            f"recipe ids not found in the selected {env} projects: {sorted(requested - found)} "
            "(without a project argument only the managed projects are searched)"
        )
    return plans


def main(argv: list[str] | None = None) -> int:
    """Sync the selected projects; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("env", choices=wkrepo.ENVIRONMENTS)
    parser.add_argument(
        "projects",
        nargs="*",
        metavar="project",
        help="project slugs (default: every managed project)",
    )
    parser.add_argument(
        "--recipe", nargs="+", type=int, default=[], metavar="ID", help="only these recipes"
    )
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)

    slugs = args.projects or wkrepo.snapshot_projects(args.env)
    if not slugs:
        print(
            f"No managed project has {args.env} ids in the registry: nothing to sync. Name a "
            "project to sync a Dev-only one."
        )
    plans = plan(args.env, slugs, set(args.recipe))
    differences = sum(
        sync_project(args.env, slug, ids, args.check, state) for slug, ids, state in plans
    )
    if not args.check:
        return cli.EXIT_OK
    if differences:
        print("The copy differs from Workato: refresh it and read what changed.")
        return cli.EXIT_FINDINGS
    print("The copy is up to date.")
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

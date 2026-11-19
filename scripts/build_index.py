#!/usr/bin/env python3.14
"""Rebuild the recipe index: recipes-index.json of the workspace and docs/recipe-index.md.

    scripts/build_index.py            rewrite both files
    scripts/build_index.py --check    write nothing; exit 1 if a file would change

One entry per documented recipe. Where it comes from:

1. The frontmatter of the recipe doc in docs/<project>/recipes/: name, path, severity, owner,
   last_job and verdict. When the workspace keeps a sheet of its recipes as
   inventory/recipes.json (a list of objects with recipe_id and any of name, path, severity,
   owner), its values fill what a doc leaves empty.
2. The Dev recipe JSON in tmp/wk/dev/<project>/ of every managed project that has a copy there:
   trigger, step count, connectors and forward calls, and two lists: `tables`, the tables the
   registry names under `tables` whose id the recipe holds, and `properties`, the names of the
   project properties it reads. Refresh the copy first with
   `scripts/sync_recipes.py dev`. The docs carry Dev ids, so the Prod copy cannot be used for
   this. A project without a Dev copy keeps these values from the current index, and the script
   says so.
3. The current index: the callers of a recipe (`called_by`) are kept and the forward calls of
   step 2 are added to them. A key the script does not write itself is carried over untouched,
   so a workspace can keep facts of its own in an entry.

Exit status: 0 done, or with --check nothing would change; 1 with --check otherwise.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
DOCS = ROOT / "docs"
INDEX_MD = DOCS / "recipe-index.md"
# The kind of trigger by its provider. Any other trigger is told apart by its name.
TRIGGER_PROVIDERS = {
    "workato_recipe_function": "callable",
    "clock": "schedule",
    "workato_api_platform": "api endpoint",
    "workato_webhooks": "webhook",
}
# What is recomputed from the Dev JSON of a recipe, and kept from the current index without one.
COMPUTED = ("trigger_type", "step_count", "connectors", "calls", "tables", "properties")
VERDICT_ORDER = {"Decommission": 0, "Rewrite": 1, "Merge": 2, "Investigate": 3, "Keep": 4}
PROPERTY_NAME = re.compile(r'property_name\\+"\s*:\s*\\+"([A-Za-z0-9_\-]+)')
NUMBERED_ITEM = re.compile(r"^\d+\.\s", re.MULTILINE)
QUOTES = "\"'"


def index_json() -> Path:
    """Return the path of the machine-readable index in the workspace folder."""
    return wkrepo.inventory() / "recipes-index.json"


def sheet() -> dict[int, Json]:
    """Return the optional inventory sheet of the workspace by recipe id; empty without one."""
    path = wkrepo.inventory() / "recipes.json"
    if not path.exists():
        return {}
    return {row["recipe_id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}


def steps(step: Json) -> list[Json]:
    """Return a step and every step nested in it, in order."""
    found = [step]
    for child in step.get("block") or []:
        found += steps(child)
    return found


def registry_tables() -> dict[str, str]:
    """Return the tables the registry names, as {table id: label in the index}."""
    return {
        table_id: f"{name} ({table_id})"
        for entry in wkrepo.registry()["projects"].values()
        for table_id, name in entry.get("tables", {}).items()
    }


def dev_recipes() -> dict[int, Path]:
    """Return {recipe id: file} for the Dev copy of every managed project that has one."""
    found: dict[int, Path] = {}
    for slug in wkrepo.snapshot_projects("dev"):
        for path in sorted(wkrepo.snapshot_dir("dev", slug).rglob("*.recipe.json")):
            found[int(path.name.split("-")[0])] = path
    return found


def recipe_code(path: Path) -> tuple[str, Json]:
    """Return the name and the step tree of a recipe file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    code = raw["code"] if isinstance(raw["code"], dict) else json.loads(raw["code"])
    return raw["name"], code


def trigger_type(code: Json) -> str:
    """Return the kind of trigger: callable, schedule, api endpoint, webhook or other."""
    known = TRIGGER_PROVIDERS.get(str(code.get("provider")))
    if known:
        return known
    return "webhook" if "hook" in str(code.get("name")) else "other"


def calls(all_steps: list[Json], names: dict[int, Any]) -> list[Json]:
    """Return the recipes a recipe calls. A call whose target is not set yet has no recipe id."""
    found = []
    for step in all_steps:
        name = step.get("name", "")
        if step.get("provider") != "workato_recipe_function" or not name.startswith("call_recipe"):
            continue
        step_input = step.get("input") or {}
        flow_id = str(step_input.get("flow_id") or "")
        target = int(flow_id) if flow_id.isdigit() else None  # unfinished, or a datapill
        found.append(
            {
                "recipe_id": target,
                "name": names.get(target) if target is not None else None,
                "mode": "async" if name.endswith("async") else "sync",
                "fields": sorted((step_input.get("parameters") or {}).keys()),
            }
        )
    return found


def live_record(code: Json, names: dict[int, Any], tables: dict[str, str]) -> Json:
    """Return what the Dev JSON of one recipe says about it.

    Args:
        code: Its step tree.
        names: Recipe names by id, to name the recipes it calls.
        tables: The tables to look for, as {table id: label}.
    """
    all_steps = steps(code)
    connectors: list[str] = []
    for step in all_steps:
        provider = step.get("provider")
        if provider and provider not in connectors:
            connectors.append(provider)
    blob = json.dumps(code)
    return {
        "trigger_type": trigger_type(code),
        "step_count": len(all_steps),
        "connectors": connectors,
        "calls": calls(all_steps, names),
        "tables": [
            name for table, name in tables.items() if re.search(rf"(?<!\d){table}(?!\d)", blob)
        ],
        "properties": sorted(set(PROPERTY_NAME.findall(blob))),
    }


def live_records(old: dict[int, Json], documented: set[int]) -> dict[int, Json]:
    """Return fresh values for every documented recipe that has a Dev copy on this machine."""
    files = dev_recipes()
    parsed = {recipe_id: recipe_code(path) for recipe_id, path in files.items()}
    names: dict[int, Any] = {recipe_id: entry.get("name") for recipe_id, entry in old.items()}
    for recipe_id, (name, _code) in parsed.items():  # the name in Workato now wins
        names[recipe_id] = name
    tables = registry_tables()
    return {
        recipe_id: {"name": name, **live_record(code, names, tables)}
        for recipe_id, (name, code) in sorted(parsed.items())
        if recipe_id in documented
    }


def frontmatter(text: str) -> dict[str, str]:
    """Return the frontmatter of a doc as a flat dict of strings."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    found = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        quoted = len(value) > 1 and value[0] == value[-1] and value[0] in QUOTES
        if not quoted:  # a comment after the value, as the template has it, is no value
            value = "" if value.startswith("#") else value.split(" #", 1)[0].rstrip()
        found[key.strip()] = value[1:-1] if quoted else value
    return found


def numbered_items(text: str, heading: str) -> int:
    """Count the numbered items under a `## <heading>` section."""
    section = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    return len(NUMBERED_ITEM.findall(section.group(1))) if section else 0


def recipe_docs() -> dict[int, Json]:
    """Return {recipe id: doc metadata} for every recipe doc on disk."""
    names = {slug: entry["name"] for slug, entry in wkrepo.registry()["projects"].items()}
    docs: dict[int, Json] = {}
    for folder in sorted(path for path in DOCS.iterdir() if (path / "recipes").is_dir()):
        for path in sorted((folder / "recipes").glob("[0-9]*.md")):
            text = path.read_text(encoding="utf-8")
            meta = frontmatter(text)
            try:
                recipe_id = int(meta.get("recipe_id") or path.name.split("-")[0])
            except ValueError:
                continue
            docs[recipe_id] = {
                "doc_path": path.relative_to(ROOT).as_posix(),
                "project": names.get(folder.name, folder.name),
                "frontmatter": meta,
                "findings_count": numbered_items(text, "Findings"),
            }
    return docs


def build(old_index: list[Json]) -> list[Json]:
    """Return the new index, one entry per documented or recorded recipe."""
    docs = recipe_docs()
    old = {entry["recipe_id"]: entry for entry in old_index}
    live = live_records(old, set(docs))
    rows = sheet()

    index: dict[int, Json] = {}
    for recipe_id in sorted(set(docs) | set(old)):
        before = old.get(recipe_id, {})
        doc = docs.get(recipe_id, {})
        meta = doc.get("frontmatter", {})
        row = rows.get(recipe_id, {})
        fresh = live.get(recipe_id, {})
        computed = {key: fresh[key] if fresh else before.get(key) for key in COMPUTED}
        entry = {
            "recipe_id": recipe_id,
            "name": meta.get("name") or fresh.get("name") or before.get("name") or row.get("name"),
            "url": wkrepo.recipe_url(recipe_id),
            "doc": doc.get("doc_path"),
            "project": doc.get("project") or meta.get("project") or before.get("project"),
            "path": meta.get("path") or row.get("path"),
            "severity": meta.get("severity") or row.get("severity"),
            "owner": meta.get("owner") or row.get("owner"),
            "trigger_type": computed["trigger_type"],
            "step_count": computed["step_count"],
            "connectors": computed["connectors"] or [],
            "calls": computed["calls"] or [],
            "called_by": sorted({int(caller) for caller in before.get("called_by") or []}),
            "tables": computed["tables"] or [],
            "properties": computed["properties"] or [],
            "last_job": meta.get("last_job") or before.get("last_job"),
            "findings_count": doc.get("findings_count", 0),
            "verdict": meta.get("verdict") or before.get("verdict"),
        }
        # A key this script does not write is the workspace's own: it stays as it is.
        index[recipe_id] = {**entry, **{k: v for k, v in before.items() if k not in entry}}

    # Fold the forward call edges into called_by, so the graph reads the same both ways.
    for recipe_id, entry in index.items():
        for call in entry["calls"]:
            target = call.get("recipe_id")
            if target in index and recipe_id not in index[target]["called_by"]:
                index[target]["called_by"].append(recipe_id)
    for entry in index.values():
        entry["called_by"] = sorted(set(entry["called_by"]))
    return list(index.values())


def index_markdown(index: list[Json]) -> str:
    """Return docs/recipe-index.md: one table of documented recipes per Workato project."""
    groups: dict[str, list[Json]] = {}
    for entry in index:
        if entry["doc"]:
            groups.setdefault(entry["project"] or "(no project)", []).append(entry)
    json_link = index_json().relative_to(DOCS, walk_up=True).as_posix()
    lines = [
        "# Recipe documentation index",
        "",
        "Generated by `scripts/build_index.py`: do not edit it by hand. One row per documented",
        "recipe, grouped by its Workato project. `Last job` and `Verdict` come from the",
        "frontmatter of the doc.",
        "",
        f"Machine-readable form: [recipes-index.json]({json_link}).",
        "",
    ]
    for project in sorted(groups):
        entries = sorted(
            groups[project],
            key=lambda entry: (VERDICT_ORDER.get(entry["verdict"], 5), str(entry["name"] or "")),
        )
        lines += [
            f"## {project} ({len(entries)})",
            "",
            "| Recipe | Trigger | Last job | Verdict |",
            "|---|---|---|---|",
        ]
        for entry in entries:
            # A pipe in a name would split the table row.
            name = str(entry["name"] or entry["recipe_id"]).strip('"').replace("|", "\\|")
            doc = (ROOT / entry["doc"]).relative_to(DOCS).as_posix()
            lines.append(
                f"| [{name}]({doc}) | {entry['trigger_type'] or '—'} | "
                f"{entry['last_job'] or '—'} | {entry['verdict'] or '—'} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Rebuild or check the two index files; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)

    target = index_json()
    old_index = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    without_copy = [
        slug
        for slug in wkrepo.snapshot_projects("dev")
        if not any(wkrepo.snapshot_dir("dev", slug).rglob("*.recipe.json"))
    ]
    if without_copy:
        print(
            f"note: no Dev copy of {', '.join(without_copy)}: their records are carried over, "
            "not recomputed (scripts/sync_recipes.py dev)"
        )
    index = build(old_index)
    files = {
        target: json.dumps(index, indent=1, ensure_ascii=False) + "\n",
        INDEX_MD: index_markdown(index),
    }
    stale = [
        path for path, text in files.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    ]  # fmt: skip
    for path in stale:
        print(("out of date: " if args.check else "written: ") + path.relative_to(ROOT).as_posix())
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(files[path], encoding="utf-8")
    documented = sum(1 for entry in index if entry["doc"])
    edges = sum(len(entry["calls"]) for entry in index)
    print(f"{len(index)} recipes indexed, {documented} with a doc, {edges} call edges")
    return cli.EXIT_FINDINGS if args.check and stale else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

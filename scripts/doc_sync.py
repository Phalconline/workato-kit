#!/usr/bin/env python3.14
"""Plan which docs to refresh around a Workato asset, and record when each was last synced.

    scripts/doc_sync.py plan <asset>                  what to check before and after working on it
    scripts/doc_sync.py plan <asset> --json           the same as JSON
    scripts/doc_sync.py stamp <asset> [<asset> ...]   record that the docs were just checked
    scripts/doc_sync.py status [project]              recipe docs that may be out of date

An <asset> is a Dev recipe id (`3001` or `recipe:3001`), or `connection:<id>`,
`lookup_table:<id>` or `data_table:<id>`.

`plan` reads the whole Dev workspace once (every recipe with its code, and the connections) and
lists the asset, what it depends on one level down (the recipes it calls, its connections, its
lookup and data tables) and what shares those with it (the recipes that call it, and the recipes
that use one of the same tables). For a connection or a table the list is the recipes that use it.
A table that a step names by a datapill, or a lookup table that a formula reads by name, is not
found. Each row names its doc and says whether it is stale: never synced, changed in Workato
since the last sync, a connection renamed, or last synced more than --max-age-hours ago. More
than --limit assets means: do not refresh them all on your own; say which ones matter, or ask
the person.

`stamp` records "checked now" in workato/workspaces/<workspace>/inventory/doc-sync.json: for a
recipe the `updated_at` Workato shows now, for a connection its name. Run it after the doc was
compared with the live asset (changed, or found right), never before. That file is generated:
never edit it by hand. `plan` and `status` compare an `updated_at` as a moment in time, not as
text: `wk recipes list` writes `.36` where the API a stamp is read from writes `.360`.

`status` audits every recipe doc: no stamp, changed in Workato since its stamp, or the recipe is
gone from Dev (unless the doc says `deleted: true` in its frontmatter: a record of a recipe that
was deleted on purpose). It ignores age.

Nothing is written to Workato. Only `stamp` writes, and only doc-sync.json. No table rows are
read, and an e-mail address in a connection name is never stored or printed.

Exit status: 0 nothing is stale (plan, status) or the stamps are written; 1 something is stale;
2 when Workato could not be read, there is no workspace yet, or an asset or an argument is wrong.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
DOCS = ROOT / "docs"
STATE_NAME = "doc-sync.json"
MAX_AGE_HOURS = 24
ASSET_LIMIT = 15
HOURS_AS_DAYS = 48  # from this age on, an age is told in days
HOURS_PER_DAY = 24
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RECIPE, CONNECTION, LOOKUP_TABLE, DATA_TABLE = "recipe", "connection", "lookup_table", "data_table"
KINDS = (RECIPE, CONNECTION, LOOKUP_TABLE, DATA_TABLE)  # also the order inside the state file
TABLE_KINDS = (LOOKUP_TABLE, DATA_TABLE)
NEEDS_DOC = (RECIPE, LOOKUP_TABLE)
MARKER_FIELD = {RECIPE: "updated_at", CONNECTION: "name"}  # what a stamp keeps to spot a change
SPEC = re.compile(rf"^(?:({'|'.join(KINDS)}):)?(\d+)$")
STATE_KEY = re.compile(rf"^({'|'.join(KINDS)}):(\d+)$")
DELETED_RECORD = re.compile(r"^deleted: true$", re.MULTILINE)  # frontmatter of a record doc
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DESCRIPTION = (
    "When the doc of each asset was last checked against Workato. Written by "
    "`scripts/doc_sync.py stamp`; never edit by hand. synced_at is UTC. A recipe also keeps the "
    "updated_at Workato showed, a connection its name without the account in brackets."
)
HOW_TO_REFRESH = {
    RECIPE: "recipe: compare its doc with the live recipe (scripts/sync_recipes.py dev --recipe "
    "<id>, scripts/render_recipe.py), fix the doc, set last_reviewed",
    CONNECTION: "connection: check the Connections line of every doc that names it",
    LOOKUP_TABLE: "lookup table: scripts/sync_lookup_tables.py (fields only, never rows)",
    DATA_TABLE: "data table: check the doc that names it (fields only, never rows)",
}


class Asset(NamedTuple):
    """One thing a doc may describe: a recipe, a connection or a table."""

    kind: str
    asset_id: int

    @property
    def key(self) -> str:
        """Return the form used on the command line and in the state file: `recipe:123`."""
        return f"{self.kind}:{self.asset_id}"

    @property
    def label(self) -> str:
        """Return the asset as words: `lookup table 123`."""
        return f"{self.kind.replace('_', ' ')} {self.asset_id}"


@dataclass
class Recipe:
    """What this script needs to know of one live Dev recipe."""

    recipe_id: int
    name: str
    updated_at: str
    calls: set[int] = field(default_factory=set)
    connections: set[int] = field(default_factory=set)
    lookup_tables: set[int] = field(default_factory=set)
    data_tables: set[int] = field(default_factory=set)
    readable: bool = True


def state_path() -> Path:
    """Return the file that holds the stamps, in the inventory folder of the workspace."""
    return wkrepo.inventory() / STATE_NAME


def now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


def parse_asset(text: str) -> Asset:
    """Turn `3001` or `connection:6001` into an Asset."""
    match = SPEC.match(text)
    if not match:
        raise cli.Error(
            f"'{text}' is not an asset: write a recipe id, or recipe:ID, connection:ID, "
            "lookup_table:ID or data_table:ID"
        )
    return Asset(match.group(1) or RECIPE, int(match.group(2)))


def base_name(name: str) -> str:
    """Return a connection name without the account in brackets after it and without e-mails."""
    return EMAIL.sub("<user>", name.partition(" (")[0]).strip()


def steps(step: Json) -> list[Json]:
    """Return a step and every step nested in it, in order."""
    found = [step]
    for child in step.get("block") or []:
        found += steps(child)
    return found


def keep_id(found: set[int], value: object) -> None:
    """Add an id written as a number or as digits; a datapill or a formula is ignored."""
    text = str(value)
    if text.isdigit():
        found.add(int(text))


def parse_recipe(item: Json) -> Recipe:
    """Read the dependencies of one recipe of `wk recipes list` from its code and config."""
    recipe = Recipe(item["id"], item["name"], str(item.get("updated_at") or ""))
    code = item.get("code")
    try:
        tree = json.loads(code) if isinstance(code, str) else code or {}
    except ValueError:
        recipe.readable = False
        return recipe
    for step in steps(tree):
        provider, name = step.get("provider"), str(step.get("name", ""))
        step_input = step.get("input")
        step_input = step_input if isinstance(step_input, dict) else {}
        if provider == "workato_recipe_function" and name.startswith("call_recipe"):
            keep_id(recipe.calls, step_input.get("flow_id"))
        elif provider == "workato_db_table":
            keep_id(recipe.data_tables, step_input.get("table_id"))
        elif provider == "lookup_table":
            keep_id(recipe.lookup_tables, step_input.get("lookup_table_id"))
    for entry in item.get("config") or []:
        keep_id(recipe.connections, entry.get("account_id"))
    return recipe


def dependencies(recipe: Recipe) -> list[Asset]:
    """Return what a recipe uses: called recipes, connections, lookup tables, data tables."""
    return [
        *(Asset(RECIPE, asset_id) for asset_id in sorted(recipe.calls)),
        *(Asset(CONNECTION, asset_id) for asset_id in sorted(recipe.connections)),
        *(Asset(LOOKUP_TABLE, asset_id) for asset_id in sorted(recipe.lookup_tables)),
        *(Asset(DATA_TABLE, asset_id) for asset_id in sorted(recipe.data_tables)),
    ]


def uses(recipe: Recipe, asset: Asset) -> bool:
    """Say whether a recipe calls, is bound to or reads the asset."""
    users = {
        RECIPE: recipe.calls,
        CONNECTION: recipe.connections,
        LOOKUP_TABLE: recipe.lookup_tables,
        DATA_TABLE: recipe.data_tables,
    }
    return asset.asset_id in users[asset.kind]


def note(found: dict[Asset, list[str]], asset: Asset, reason: str) -> None:
    """Add an asset to the plan, or one more reason to an asset already in it."""
    reasons = found.setdefault(asset, [])
    if reason not in reasons:
        reasons.append(reason)


def related(target: Asset, recipes: dict[int, Recipe]) -> dict[Asset, list[str]]:
    """Return the target and what to check with it, each with its reasons, in plan order.

    For a recipe: the recipes it calls, the recipes that call it or use one of its tables, then
    its connections and tables. For any other asset: the recipes that use it. One level only.
    """
    found: dict[Asset, list[str]] = {target: ["target"]}
    recipe = recipes.get(target.asset_id) if target.kind == RECIPE else None
    if recipe is None:
        for other in sorted(recipes):
            if uses(recipes[other], target):
                note(found, Asset(RECIPE, other), "uses the target")
        return found
    for callee in sorted(recipe.calls):
        note(found, Asset(RECIPE, callee), "called by the target")
    tables = [asset for asset in dependencies(recipe) if asset.kind in TABLE_KINDS]
    for other in sorted(recipes):
        if other == recipe.recipe_id:
            continue
        if recipe.recipe_id in recipes[other].calls:
            note(found, Asset(RECIPE, other), "calls the target")
        for table in tables:
            if uses(recipes[other], table):
                note(found, Asset(RECIPE, other), f"also uses {table.label}")
    for asset in dependencies(recipe):
        if asset.kind != RECIPE:
            note(found, asset, "used by the target")
    return found


def doc_path(asset: Asset) -> Path | None:
    """Return the repository doc of a recipe or a lookup table, or None."""
    if asset.kind == RECIPE:
        found = sorted(DOCS.glob(f"*/recipes/{asset.asset_id}-*.md"))
    elif asset.kind == LOOKUP_TABLE:
        found = sorted(wkrepo.lookup_tables().glob(f"{asset.asset_id}-*.md"))
    else:
        found = []
    return found[0] if found else None


def table_names() -> dict[str, str]:
    """Return the tables the registry names under `tables`, as {table id: name}."""
    return {
        table_id: name
        for entry in wkrepo.registry()["projects"].values()
        for table_id, name in entry.get("tables", {}).items()
    }


def asset_name(asset: Asset, recipes: dict[int, Recipe], connections: dict[int, str]) -> str:
    """Return the name of an asset as far as it is known."""
    if asset.kind == RECIPE:
        return recipes[asset.asset_id].name if asset.asset_id in recipes else "(not in Dev)"
    if asset.kind == CONNECTION:
        return connections.get(asset.asset_id, "(not in Dev)")
    named = table_names().get(str(asset.asset_id), "")
    if asset.kind == LOOKUP_TABLE and not named:
        path = doc_path(asset)
        return path.stem.partition("-")[2] if path else ""
    return named


def live_marker(
    asset: Asset, recipes: dict[int, Recipe], connections: dict[int, str]
) -> str | None:
    """Return what Workato shows now for the field a stamp keeps: updated_at or the name."""
    if asset.kind == RECIPE and asset.asset_id in recipes:
        return recipes[asset.asset_id].updated_at
    if asset.kind == CONNECTION:
        return connections.get(asset.asset_id)
    return None


def existing(asset: Asset, recipes: dict[int, Recipe], connections: dict[int, str]) -> bool:
    """Say whether Dev still has the asset; a table cannot be checked from the lists."""
    if asset.kind == RECIPE:
        return asset.asset_id in recipes
    if asset.kind == CONNECTION:
        return asset.asset_id in connections
    return True


def ago(age: timedelta) -> str:
    """Tell an age in hours, or in days from two days on."""
    hours = age // timedelta(hours=1)
    return f"{hours} h" if hours < HOURS_AS_DAYS else f"{hours // HOURS_PER_DAY} days"


def instant(text: str) -> datetime | None:
    """Read a timestamp with any number of fraction digits; None when the text is not one."""
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def marker_kept(asset: Asset, kept: object, live: str) -> bool:
    """Say whether the marker a stamp kept is still what Workato shows.

    `wk recipes list` drops the trailing zeros of the fraction of `updated_at` (`.36`), while the
    API a stamp is read from keeps them (`.360`): two spellings of one moment are the same marker.
    """
    if asset.kind == RECIPE and isinstance(kept, str):
        before, now_shown = instant(kept), instant(live)
        if before and now_shown:
            return before == now_shown
    return kept == live


def stale_reason(
    asset: Asset, entry: Json | None, marker: str | None, moment: datetime, max_age: int | None
) -> str | None:
    """Say why a stamp no longer vouches for the doc, or None when it still does."""
    if entry is None:
        return "never synced"
    changed = MARKER_FIELD.get(asset.kind)
    if changed and marker is not None and not marker_kept(asset, entry.get(changed), marker):
        if asset.kind == RECIPE:
            return "changed in Workato since the last sync"
        return f"renamed since the last sync (was {entry.get('name')})"
    if max_age is not None:
        age = moment - datetime.fromisoformat(entry["synced_at"])
        if age > timedelta(hours=max_age):
            return f"last synced {ago(age)} ago"
    return None


def read_state() -> dict[str, Json]:
    """Return the stamps of doc-sync.json by asset key; an absent file holds none."""
    state = state_path()
    if not state.exists():
        return {}
    name = state.relative_to(ROOT).as_posix()
    try:
        assets: dict[str, Json] = json.loads(state.read_text(encoding="utf-8"))["assets"]
        for key, entry in assets.items():
            if not STATE_KEY.match(key):
                raise ValueError(key)
            datetime.fromisoformat(entry["synced_at"])
    except ValueError, KeyError, TypeError, AttributeError:
        raise cli.Error(f"{name} is not a valid doc-sync file; restore it from git") from None
    return assets


def write_state(assets: dict[str, Json]) -> None:
    """Write the stamps: one line per asset, in a fixed order, so that merges stay clean."""

    def order(key: str) -> tuple[int, int]:
        kind, _, number = key.partition(":")
        return KINDS.index(kind), int(number)

    rows = [
        f"  {json.dumps(key)}: {json.dumps(assets[key], sort_keys=True)}"
        for key in sorted(assets, key=order)
    ]
    body = "{\n" + ",\n".join(rows) + "\n }" if rows else "{}"
    text = f'{{\n "description": {json.dumps(DESCRIPTION)},\n "assets": {body}\n}}\n'
    state = state_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    temp = state.with_name(state.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(state)


def load_workspace() -> tuple[dict[int, Recipe], dict[int, str]]:
    """Read every Dev recipe and connection; return {id: Recipe} and {id: connection name}."""
    prof = wkrepo.profile("dev")
    recipes = {item["id"]: parse_recipe(item) for item in wkrepo.list_recipes(prof)}
    connections = {item["id"]: base_name(item["name"]) for item in wkrepo.list_connections(prof)}
    unreadable = sorted(recipe.recipe_id for recipe in recipes.values() if not recipe.readable)
    if unreadable:
        print(
            f"warning: the code of {len(unreadable)} recipe(s) could not be read; what they "
            f"use is missing from this result: {', '.join(map(str, unreadable))}",
            file=sys.stderr,
        )
    return recipes, connections


def plan_rows(
    target: Asset, workspace: tuple[dict[int, Recipe], dict[int, str]], max_age: int
) -> list[Json]:
    """Return one row per asset of the plan: its names, doc, relations and staleness."""
    recipes, connections = workspace
    if not existing(target, recipes, connections):
        raise cli.Error(f"{target.label} is not in Dev")
    state, moment = read_state(), now()
    target_doc = doc_path(target) if target.kind == RECIPE else None
    target_text = target_doc.read_text(encoding="utf-8") if target_doc else None
    rows: list[Json] = []
    for asset, relations in related(target, recipes).items():
        path = doc_path(asset)
        name = asset_name(asset, recipes, connections)
        entry = state.get(asset.key)
        if not existing(asset, recipes, connections):
            reason: str | None = "not in Dev (deleted?)"
        elif asset.kind in NEEDS_DOC and path is None:
            reason = "has no doc"
        else:
            marker = live_marker(asset, recipes, connections)
            reason = stale_reason(asset, entry, marker, moment, max_age)
        hint = None
        if asset.kind == CONNECTION and target_text is not None and name not in target_text:
            hint = "its name is not in the doc of the target"
        age = ago(moment - datetime.fromisoformat(entry["synced_at"])) if entry else None
        rows.append(
            {
                "asset": asset.key,
                "name": name,
                "relations": relations,
                "doc": path.relative_to(ROOT).as_posix() if path else None,
                "stale": reason,
                "synced_ago": age,
                "hint": hint,
            }
        )
    return rows


def render_plan(target: Asset, rows: list[Json], max_age: int, limit: int) -> list[str]:
    """Return the text of a plan."""
    stale = [row for row in rows if row["stale"]]
    lines = [
        f"Plan for {target.label}: {rows[0]['name']}",
        (
            f"Dev, {now().strftime(TIME_FORMAT)}. Fresh means synced within {max_age} h and not "
            "changed in Workato since."
        ),
        "",
    ]
    if len(rows) > limit:
        lines += [
            (
                f"{len(rows)} assets: over the limit of {limit}. Do not refresh them all on your "
                "own: pick the ones the change touches, or ask the person."
            ),
            "",
        ]
    for row in rows:
        kind, _, number = str(row["asset"]).partition(":")
        head = f"{'STALE' if row['stale'] else 'fresh':5}  {kind.replace('_', ' ')} {number}"
        lines.append(f"{head}  {row['name']}  ({', '.join(row['relations'])})")
        if row["stale"]:
            lines.append(f"       why: {row['stale']}")
        else:
            lines.append(f"       synced {row['synced_ago']} ago")
        if row["doc"]:
            lines.append(f"       doc: {row['doc']}")
        if row["hint"]:
            lines.append(f"       note: {row['hint']}")
    lines += ["", f"{len(rows)} asset(s), {len(stale)} stale."]
    if stale:
        kinds = [
            kind for kind in KINDS if any(str(r["asset"]).startswith(f"{kind}:") for r in stale)
        ]
        lines += ["How to refresh:", *(f"  {HOW_TO_REFRESH[kind]}" for kind in kinds)]
        lines += [
            "Then record what you checked (only what you really checked):",
            "  scripts/doc_sync.py stamp " + " ".join(str(row["asset"]) for row in stale),
        ]
    return lines


def plan(target: Asset, max_age: int, limit: int, as_json: bool) -> int:
    """Print the plan for one asset; return 1 when something in it is stale."""
    rows = plan_rows(target, load_workspace(), max_age)
    if as_json:
        report = {
            "target": target.key,
            "limit": limit,
            "over_limit": len(rows) > limit,
            "assets": rows,
        }
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(render_plan(target, rows, max_age, limit)))
    return cli.EXIT_FINDINGS if any(row["stale"] for row in rows) else cli.EXIT_OK


def stamp(specs: list[str]) -> int:
    """Record that the docs of these assets were just checked against the live assets."""
    assets = [parse_asset(spec) for spec in specs]
    prof = wkrepo.profile("dev")
    connections = (
        {item["id"]: base_name(item["name"]) for item in wkrepo.list_connections(prof)}
        if any(asset.kind == CONNECTION for asset in assets)
        else {}
    )
    api = wkrepo.api("dev", prof) if any(asset.kind == RECIPE for asset in assets) else None
    moment = now().strftime(TIME_FORMAT)
    stamps: dict[str, Json] = {}
    for asset in assets:
        entry: Json = {"synced_at": moment}
        if asset.kind == RECIPE:
            if doc_path(asset) is None:
                raise cli.Error(f"{asset.label} has no doc in docs/*/recipes/: write it first")
            if api is not None:
                entry["updated_at"] = api.get(f"/recipes/{asset.asset_id}")["updated_at"]
        elif asset.kind == CONNECTION:
            if asset.asset_id not in connections:
                raise cli.Error(f"{asset.label} is not in Dev")
            entry["name"] = connections[asset.asset_id]
        stamps[asset.key] = entry
    state = read_state()
    state.update(stamps)
    write_state(state)
    print(f"stamped {len(stamps)} asset(s) at {moment}")
    return cli.EXIT_OK


def audit_reason(
    doc: Path, recipes: dict[int, Recipe], state: dict[str, Json], moment: datetime
) -> str | None:
    """Say why the stamp of a recipe doc does not vouch for it; None when it does."""
    asset = Asset(RECIPE, int(doc.name.partition("-")[0]))
    live = recipes.get(asset.asset_id)
    if live is None:
        if DELETED_RECORD.search(doc.read_text(encoding="utf-8")):
            return None  # kept on purpose as the record of a recipe that was deleted
        return "the recipe is no longer in Dev"
    return stale_reason(asset, state.get(asset.key), live.updated_at, moment, None)


def status(project: str | None) -> int:
    """List the recipe docs whose stamp is missing, outdated or whose recipe is gone."""
    if project:
        wkrepo.project(project)  # an unknown slug is an error, not an empty answer
    recipes, _connections = load_workspace()
    state, moment = read_state(), now()
    docs = [
        doc
        for doc in sorted(DOCS.glob("*/recipes/[0-9]*.md"))
        if not project or doc.parent.parent.name == project
    ]
    found = []
    for doc in docs:
        reason = audit_reason(doc, recipes, state, moment)
        if reason:
            found.append(
                f"{doc.parent.parent.name}  {doc.name.partition('-')[0]}  {doc.name}  {reason}"
            )
    if found:
        print("\n".join(found))
    print(f"{len(found)} of {len(docs)} recipe doc(s) may be out of date.")
    return cli.EXIT_FINDINGS if found else cli.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the chosen command; return the exit status."""
    parser = cli.parser(__doc__)
    commands = parser.add_subparsers(dest="command", required=True, metavar="{plan,stamp,status}")
    plan_parser = commands.add_parser(
        "plan", help="what to check around an asset", allow_abbrev=False
    )
    plan_parser.add_argument("asset", help="a Dev recipe id, or kind:id")
    plan_parser.add_argument("--max-age-hours", type=int, default=MAX_AGE_HOURS, help="default 24")
    plan_parser.add_argument("--limit", type=int, default=ASSET_LIMIT, help="default 15")
    plan_parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    stamp_parser = commands.add_parser(
        "stamp", help="record that docs were checked", allow_abbrev=False
    )
    stamp_parser.add_argument("assets", nargs="+", help="Dev recipe ids, or kind:id")
    status_parser = commands.add_parser(
        "status", help="recipe docs that may be stale", allow_abbrev=False
    )
    status_parser.add_argument("project", nargs="?", help="a project slug; default: every project")
    args = parser.parse_args(argv)
    if args.command == "plan":
        return plan(parse_asset(args.asset), args.max_age_hours, args.limit, args.json)
    if args.command == "stamp":
        return stamp(args.assets)
    return status(args.project)


if __name__ == "__main__":
    cli.run(main)

#!/usr/bin/env python3.14
"""Compare the Dev recipes of the managed projects with their Prod copies. Read-only.

    scripts/prod_drift.py                          every project that exists in Dev and in Prod
    scripts/prod_drift.py sales-orders             only this project
    scripts/prod_drift.py --recipe <id> ...        only these Dev recipes (the ones to deploy)
    scripts/prod_drift.py --pair 3001:4001         a reviewed rename or move: Dev 3001 is Prod 4001

Run it before a deployment: it shows what the deployment would overwrite in Prod and which
recipes have changes to deploy. It uses `wk recipes list/get`, `wk folders list`,
`wk connections list` and GET calls to the public API. Projects, ids and profiles come from the
registry.

Recipes are paired by exact folder path and name inside one project. A rename or a move needs
--pair DEV_ID:PROD_ID (or DEV_ID=PROD_ID); there is no pairing by name alone. A duplicate
identity, a conflicting pair and a result from outside the project stop the run (exit 2).

The comparison ignores only what a deployment remaps, and checks each of those instead of
masking it:
- the id of a called recipe function (`flow_id`): equal when it is the paired recipe, in this
  project or in another managed one;
- data table, message template and schema ids: equal when the asset name the builder stored next
  to the id is the same. The Dev-to-Prod map of each kind must stay one-to-one (IDMAP otherwise).
  A step that stores no name is accepted and listed at the end as not confirmed;
- the numeric suffix of a custom-connector provider, on a step and inside a datapill;
- known UI caches.
Every other value is compared exactly, including numbers, formulas and UUIDs.

What is reported, per recipe:
- CODE: a step that differs (UI step number, field, a short window of Dev and of Prod). A
  difference that exists only in Prod is overwritten by a deployment of that recipe.
- COMMENT: a step comment that differs. People write them; never overwrite one by accident.
- NAME, DESCRIPTION: differs.
- BINDING: a connection slot that is empty in Prod, or a Dev binding to a connection outside the
  project and outside the project marked `shared_connections` in the registry: observed, a
  deployment leaves the Prod slot of such a connection empty.
- MISSING: no exact Prod counterpart (new, renamed or moved; not proof that it is new).
- PROD_ONLY: a Prod recipe without a Dev counterpart (whole-project checks only).
- FOLDER: the folder paths of an explicit pair differ.
- IDMAP: one Dev table, template or schema is used where Prod uses two, or the reverse.
And per project, its properties: missing in Prod, only in Prod, blank in Prod, or a different
value. Values are never printed. Observed: a deployment does not carry them, so each
environment keeps its own. A property listed under `dev_only_properties` in the registry may be
missing in Prod.

Step numbers are Workato UI numbers (the JSON indexes the trigger as 0, so +1). E-mail addresses
in the output are shortened. The full result is written to tmp/wk/prod-drift/drift-<time>.json.

Exit status: 0 nothing differs; 1 something differs; 2 the pairing is invalid or ambiguous, or
Workato could not be read.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
OUT_DIR = ROOT / "tmp" / "wk" / "prod-drift"
# UI caches that a builder push or the UI rewrites on its own; dynamicPickListSelection holds
# picklist labels. A comment is compared separately.
COSMETIC_KEYS = {
    "block",
    "extended_input_schema",
    "extended_output_schema",
    "visible_config_fields",
    "comment",
    "dynamicPickListSelection",
}
CUSTOM_PROVIDER = re.compile(r"[a-z0-9_]+_connector_\d+_\d+")
# A datapill names the step it reads by provider; a custom connector's provider ends in a suffix
# that differs between environments.
PILL_PROVIDER = re.compile(r'("provider":)\s*("[a-z0-9_]+_connector)_\d+_\d+(")')
# Assets a deployment recreates under another id: step provider -> the input field with the id.
ENV_IDS = {
    "workato_recipe_function": "flow_id",
    "workato_db_table": "table_id",
    "workato_template": "template_id",
    "workato_mapper": "workato_schema_id",
}
EMAIL = re.compile(r"([A-Za-z0-9._%+-]+)@")
WINDOW_BEFORE = 40
WINDOW_WIDTH = 110

type Pair = tuple[Json, Json | None]  # a Dev recipe and its Prod counterpart, if it has one
type IdPairs = dict[str, dict[tuple[str, str], bool]]  # id field -> {(Dev id, Prod id): named}


@dataclass(frozen=True)
class Listing:
    """The recipes of one project in both environments, paired."""

    slug: str
    entry: Json  # the registry entry of the project
    pairs: list[Pair]
    prod_only: list[Json]
    dev_folders: frozenset[int]
    explicit: frozenset[int]  # the Dev ids that were paired with --pair


@dataclass
class Run:
    """What the comparisons of one run share."""

    dev_profile: str
    prod_profile: str
    recipe_ids: dict[int, int]  # Dev recipe id -> paired Prod recipe id, across all projects
    dev_connections: dict[int, Json]
    prod_connections: dict[int, Json]
    id_pairs: IdPairs = field(default_factory=dict)  # filled while the recipes are compared


def project_recipes(prof: str, location: Json) -> tuple[list[Json], frozenset[int]]:
    """Read the recipes of one project, folder by folder.

    Args:
        prof: The wk profile to read with.
        location: The project's `project_id` and `folder_id` in that environment.

    Returns:
        The recipes, each with its `folder_id` and `folder_path` (exact names, not slugs), and
        the ids of all folders of the project.
    """
    records = []
    folders = wkrepo.walk_folders(prof, location["folder_id"])
    for folder_id, names in folders:
        for recipe in wkrepo.list_recipes(prof, folder_id):
            if str(recipe.get("folder_id", folder_id)) != str(folder_id):
                raise cli.Error(f"recipe {recipe['id']} came back outside folder {folder_id}")
            project_id = location["project_id"]
            if str(recipe.get("project_id", project_id)) != str(project_id):
                raise cli.Error(f"recipe {recipe['id']} came back outside project {project_id}")
            records.append({**recipe, "folder_id": folder_id, "folder_path": list(names)})
    return records, frozenset(folder_id for folder_id, _ in folders)


def recipe_indexes(
    records: list[Json], environment: str
) -> tuple[dict[int, Json], dict[tuple[str, ...], Json]]:
    """Index recipes by id and by (folder path, name); refuse a duplicate of either."""
    by_id: dict[int, Json] = {}
    by_path: dict[tuple[str, ...], Json] = {}
    for record in records:
        recipe_id, name = record["id"], record.get("name")
        if type(recipe_id) is not int or recipe_id <= 0 or not isinstance(name, str) or not name:
            raise cli.Error(f"invalid recipe identity in {environment}")
        if recipe_id in by_id:
            raise cli.Error(f"duplicate recipe id {recipe_id} in {environment}")
        key = (*record["folder_path"], name)
        if key in by_path:
            raise cli.Error(f"ambiguous recipe path and name in {environment}: {' / '.join(key)}")
        by_id[recipe_id] = by_path[key] = record
    return by_id, by_path


def parse_pair(value: str) -> tuple[int, int]:
    """Parse DEV_ID:PROD_ID of --pair; `=` works as the separator too."""
    try:
        dev, prod = (int(part) for part in re.split("[:=]", value))
    except ValueError:
        dev = prod = 0
    if dev <= 0 or prod <= 0:
        raise argparse.ArgumentTypeError("expected positive DEV_ID:PROD_ID")
    return dev, prod


def pair_recipes(
    dev_records: list[Json],
    prod_records: list[Json],
    explicit: list[tuple[int, int]] | None = None,
) -> tuple[list[Pair], list[Json]]:
    """Pair the Dev recipes of a project with its Prod recipes; never guess a rename.

    Returns:
        One (Dev, Prod or None) pair per Dev recipe, and the Prod recipes that were not paired.
    """
    dev_ids, _ = recipe_indexes(dev_records, "Dev")
    prod_ids, prod_paths = recipe_indexes(prod_records, "Prod")
    overrides: dict[int, int] = {}
    reserved: set[int] = set()
    for dev_id, prod_id in explicit or []:
        if dev_id not in dev_ids or prod_id not in prod_ids:
            raise cli.Error(f"pair {dev_id}:{prod_id} is outside the Dev and Prod project")
        if dev_id in overrides or prod_id in reserved:
            raise cli.Error(f"conflicting explicit pair {dev_id}:{prod_id}")
        overrides[dev_id] = prod_id
        reserved.add(prod_id)
    pairs: list[Pair] = []
    used: set[int] = set()
    for dev in sorted(dev_records, key=lambda record: (*record["folder_path"], record["name"])):
        prod: Json | None
        if dev["id"] in overrides:
            prod = prod_ids[overrides[dev["id"]]]
        else:
            prod = prod_paths.get((*dev["folder_path"], dev["name"]))
            if prod is not None and prod["id"] in reserved:
                raise cli.Error(
                    f"Prod recipe {prod['id']} matches Dev {dev['id']} "
                    "but is explicitly paired elsewhere"
                )
        if prod is not None:
            if prod["id"] in used:
                raise cli.Error(f"Prod recipe {prod['id']} would be paired more than once")
            used.add(prod["id"])
        pairs.append((dev, prod))
    return pairs, [record for record in prod_records if record["id"] not in used]


def get_recipe(prof: str, recipe_id: int) -> Json:
    """Return one recipe with its code as an object."""
    recipe: Json = wkrepo.wk_json(prof, "recipes", "get", str(recipe_id))
    code = recipe.get("code")
    recipe["code"] = json.loads(code) if isinstance(code, str) else code
    return recipe


def checked_recipe(prof: str, record: Json, project_id: int) -> Json:
    """Read a listed recipe and refuse it when it was renamed or moved since the listing."""
    recipe = get_recipe(prof, record["id"])
    expected = {
        "id": record["id"],
        "project_id": project_id,
        "folder_id": record["folder_id"],
        "name": record["name"],
    }
    for name, value in expected.items():
        if name in recipe and str(recipe[name]) != str(value):
            raise cli.Error(
                f"recipe {record['id']} changed identity after listing ({name}); run it again"
            )
    return recipe


def flattened(step: Json) -> Iterator[Json]:
    """Yield a step and every step nested in it, in the order of the recipe."""
    yield step
    for child in step.get("block") or []:
        yield from flattened(child)


def steps(code: Json) -> dict[int | None, Json]:
    """Return the trigger and every nested step by step number."""
    return {step.get("number"): step for step in flattened(code)}


def unsuffixed(value: Any) -> Any:
    """Return a value without the environment suffix of custom-connector providers in datapills."""
    if isinstance(value, dict):
        return {key: unsuffixed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unsuffixed(item) for item in value]
    return PILL_PROVIDER.sub(r"\1\2\3", value) if isinstance(value, str) else value


def norm(value: Any, name: str | None = None) -> str:
    """Return a value as canonical JSON text, for comparison.

    Never normalize a user input, a formula literal, a business id or an arbitrary string: only
    the suffix of a custom-connector provider is dropped.
    """
    if name == "provider" and isinstance(value, str) and CUSTOM_PROVIDER.fullmatch(value):
        value = value.rsplit("_", 2)[0]
    return json.dumps(unsuffixed(value), sort_keys=True, separators=(",", ":"))


def same_asset(
    dev_step: Json, prod_step: Json, recipe_ids: dict[int, int], id_pairs: IdPairs
) -> Json:
    """Return the Prod step with its local id replaced by Dev's when both name the same asset."""
    same_provider = dev_step.get("provider") == prod_step.get("provider")
    id_field = ENV_IDS.get(str(dev_step.get("provider"))) if same_provider else None
    dev_input, prod_input = dev_step.get("input"), prod_step.get("input")
    if not id_field or not isinstance(dev_input, dict) or not isinstance(prod_input, dict):
        return prod_step
    dev_id, prod_id = str(dev_input.get(id_field)), str(prod_input.get(id_field))
    if dev_id == prod_id or not (dev_id.isdigit() and prod_id.isdigit()):
        return prod_step
    if id_field == "flow_id":
        same = recipe_ids.get(int(dev_id)) == int(prod_id)  # the called recipe is the paired one
    else:
        # The builder stores the asset's name next to its id; a deployment keeps the name.
        dev_name = (dev_step.get("dynamicPickListSelection") or {}).get(id_field)
        prod_name = (prod_step.get("dynamicPickListSelection") or {}).get(id_field)
        named = dev_name is not None and prod_name is not None
        same = not named or dev_name == prod_name
        if same:
            # True once any step confirmed the pair by name; a step without a stored name cannot.
            seen = id_pairs.setdefault(id_field, {})
            seen[dev_id, prod_id] = seen.get((dev_id, prod_id), False) or named
    return (
        {**prod_step, "input": {**prod_input, id_field: dev_input[id_field]}}
        if same
        else prod_step
    )


def idmap_findings(id_pairs: IdPairs) -> list[Json]:
    """Return a finding for every id that is not mapped one-to-one between Dev and Prod."""
    found = []
    for id_field, seen in sorted(id_pairs.items()):
        for dev_id, prod_id in sorted(seen):
            dev_uses = sum(dev_id == other for other, _ in seen)
            prod_uses = sum(prod_id == other for _, other in seen)
            if dev_uses > 1 or prod_uses > 1:
                note = f"{id_field}: Dev {dev_id} and Prod {prod_id} are not a one-to-one pair"
                found.append({"kind": "IDMAP", "note": note})
    return found


def unconfirmed(id_pairs: IdPairs) -> list[str]:
    """Return the pairs accepted although no step stored an asset name to compare."""
    return [
        f"{id_field}: Dev {dev_id} / Prod {prod_id}"
        for id_field, seen in sorted(id_pairs.items())
        for (dev_id, prod_id), named in sorted(seen.items())
        if not named
    ]


def short(text: str) -> str:
    """Shorten the e-mail addresses in a text to their first two characters."""
    return EMAIL.sub(lambda match: match.group(1)[:2] + "…@", text)


def window(dev_text: str, prod_text: str) -> tuple[str, str]:
    """Return the first place two texts differ, with some context on each side."""
    start = 0
    while start < min(len(dev_text), len(prod_text)) and dev_text[start] == prod_text[start]:
        start += 1
    low, high = max(0, start - WINDOW_BEFORE), start + WINDOW_WIDTH
    return short(dev_text[low:high]), short(prod_text[low:high])


def ui(number: int | None) -> int:
    """Return the number the Workato UI shows for a step."""
    return (number or 0) + 1


def compare_code(
    dev: Json,
    prod: Json,
    recipe_ids: dict[int, int] | None = None,
    id_pairs: IdPairs | None = None,
) -> list[Json]:
    """Compare the steps of a Dev recipe with those of its Prod copy.

    Args:
        dev: The Dev recipe, with `code` as an object.
        prod: The Prod recipe.
        recipe_ids: Dev recipe id -> paired Prod recipe id, to recognize a called recipe.
        id_pairs: Collects the table, template and schema ids that were accepted as the same.

    Returns:
        One CODE or COMMENT finding per difference.
    """
    recipe_ids = recipe_ids or {}
    id_pairs = {} if id_pairs is None else id_pairs
    findings: list[Json] = []
    dev_steps, prod_steps = steps(dev["code"]), steps(prod["code"])
    numbers = sorted(
        set(dev_steps) | set(prod_steps), key=lambda number: -1 if number is None else number
    )
    for number in numbers:
        dev_step, prod_step = dev_steps.get(number), prod_steps.get(number)
        if dev_step is None or prod_step is None:
            findings.append(
                {
                    "kind": "CODE",
                    "step": ui(number),
                    "field": "(step)",
                    "dev": "absent" if dev_step is None else dev_step.get("keyword"),
                    "prod": "absent" if prod_step is None else prod_step.get("keyword"),
                }
            )
            continue
        dev_comment, prod_comment = dev_step.get("comment") or "", prod_step.get("comment") or ""
        if dev_comment != prod_comment:
            findings.append(
                {
                    "kind": "COMMENT",
                    "step": ui(number),
                    "field": "comment",
                    "dev": short(dev_comment),
                    "prod": short(prod_comment),
                }
            )
        prod_step = same_asset(dev_step, prod_step, recipe_ids, id_pairs)
        for key in sorted((set(dev_step) | set(prod_step)) - COSMETIC_KEYS):
            dev_text, prod_text = norm(dev_step.get(key), key), norm(prod_step.get(key), key)
            if dev_text != prod_text:
                # the first difference that is left after the mapping
                dev_window, prod_window = window(dev_text, prod_text)
                findings.append(
                    {
                        "kind": "CODE",
                        "step": ui(number),
                        "field": key,
                        "dev": dev_window,
                        "prod": prod_window,
                    }
                )
    return findings


def slot_name(connection: Json) -> str:
    """Return the slot a connection fills: its provider, without a custom connector's suffix."""
    provider = connection.get("provider") or connection.get("keyword") or ""
    return CUSTOM_PROVIDER.sub(
        lambda match: match.group(0).split("_connector_")[0] + "_connector", provider
    )


def bindings(dev: Json, prod: Json, run: Run, mapped_folders: frozenset[int]) -> list[Json]:
    """Compare the connection slots of a recipe.

    Args:
        dev: The Dev recipe.
        prod: The Prod recipe.
        run: The connections of both environments.
        mapped_folders: The Dev folders whose connections a deployment maps to Prod.
    """
    findings = []
    dev_slots = {slot_name(item): item.get("account_id") for item in dev.get("config") or []}
    prod_slots = {slot_name(item): item.get("account_id") for item in prod.get("config") or []}
    for slot in sorted(set(dev_slots) | set(prod_slots)):
        dev_id, prod_id = dev_slots.get(slot), prod_slots.get(slot)
        if dev_id is None and prod_id is None:
            continue
        if prod_id is None:
            findings.append({"kind": "BINDING", "slot": slot, "note": "empty in Prod"})
        connection = run.dev_connections.get(dev_id) if dev_id is not None else None
        if connection and connection.get("folder_id") not in mapped_folders:
            in_prod = run.prod_connections.get(prod_id) if prod_id is not None else None
            prod_name = (in_prod or {}).get("name", prod_id)
            note = (
                f"Dev binds '{connection.get('name')}', which is outside this project and the "
                f"shared connections: a deployment leaves the Prod slot empty (now '{prod_name}')"
            )
            findings.append({"kind": "BINDING", "slot": slot, "note": note})
    return findings


def property_states(
    dev_values: dict[str, str], prod_values: dict[str, str]
) -> list[tuple[str, str]]:
    """Return (name, state) for every property that differs. No value leaves this function."""
    states = []
    for name in sorted(set(dev_values) | set(prod_values)):
        if name not in prod_values:
            states.append((name, "missing in Prod"))
        elif name not in dev_values:
            states.append((name, "only in Prod"))
        elif not prod_values[name]:
            states.append((name, "blank in Prod"))
        elif dev_values[name] != prod_values[name]:
            states.append((name, "value differs"))
    return states


def listings(
    slugs: list[str], explicit: list[tuple[int, int]], selected: list[str]
) -> list[Listing]:
    """Read and pair the recipes of each project. Every --pair must belong to one of them.

    A project that is not selected is read only to recognize calls into it. When it cannot be
    read or paired it is left out with a warning; such a call then shows as a difference.
    """
    dev_profile, prod_profile = wkrepo.profile("dev"), wkrepo.profile("prod")
    found = []
    claimed: set[tuple[int, int]] = set()
    for slug in slugs:
        entry = wkrepo.project(slug)
        try:
            dev_records, dev_folders = project_recipes(dev_profile, entry["dev"])
            prod_records, _ = project_recipes(prod_profile, entry["prod"])
            dev_ids = {record["id"] for record in dev_records}
            own = [pair for pair in explicit if pair[0] in dev_ids]
            pairs, prod_only = pair_recipes(dev_records, prod_records, own)
        except cli.Error as error:
            if slug in selected:
                raise cli.Error(f"{slug}: {error}") from None
            print(
                f"warning: {slug} is left out ({error}); a call into it is compared by id",
                file=sys.stderr,
            )
            continue
        claimed.update(own)
        found.append(
            Listing(slug, entry, pairs, prod_only, dev_folders, frozenset(dev for dev, _ in own))
        )
    for dev_id, prod_id in explicit:
        if (dev_id, prod_id) not in claimed:
            raise cli.Error(
                f"pair {dev_id}:{prod_id}: {dev_id} is not a Dev recipe of these projects"
            )
    return found


def recipe_entry(pair: Pair, listing: Listing, run: Run, mapped_folders: frozenset[int]) -> Json:
    """Compare one pair and return its entry of the report."""
    dev_record, prod_record = pair
    explicit = dev_record["id"] in listing.explicit
    entry: Json = {
        "name": dev_record["name"],
        "dev_id": dev_record["id"],
        "prod_id": prod_record["id"] if prod_record else None,
        "dev_folder": dev_record["folder_path"],
        "prod_folder": prod_record["folder_path"] if prod_record else None,
        "pairing": "explicit" if explicit else "folder-and-name",
        "findings": [],
    }
    if prod_record is None:
        note = (
            "no Prod recipe with the same folder and name; review new, renamed and moved recipes"
        )
        entry["findings"].append({"kind": "MISSING", "note": note})
        return entry
    dev = checked_recipe(run.dev_profile, dev_record, listing.entry["dev"]["project_id"])
    prod = checked_recipe(run.prod_profile, prod_record, listing.entry["prod"]["project_id"])
    entry["prod_running"] = prod.get("running")
    entry["findings"] += compare_code(dev, prod, run.recipe_ids, run.id_pairs)
    entry["findings"] += [
        {"kind": key.upper(), "note": "differs"}
        for key in ("name", "description")
        if (dev.get(key) or "") != (prod.get(key) or "")
    ]
    entry["findings"] += bindings(dev, prod, run, mapped_folders)
    if dev_record["folder_path"] != prod_record["folder_path"]:
        entry["findings"].append({"kind": "FOLDER", "note": "folder path differs"})
    return entry


def project_section(
    listing: Listing, only: set[int], run: Run, mapped_folders: frozenset[int]
) -> Json:
    """Compare one project and return its section of the report."""
    pairs = [pair for pair in listing.pairs if not only or pair[0]["id"] in only]
    recipes = [recipe_entry(pair, listing, run, mapped_folders) for pair in pairs]
    if not only:  # an unselected Dev recipe must not make its Prod copy look unpaired
        recipes += [
            {
                "name": record["name"],
                "dev_id": None,
                "prod_id": record["id"],
                "prod_folder": record["folder_path"],
                "prod_running": record.get("running"),
                "findings": [
                    {
                        "kind": "PROD_ONLY",
                        "note": "no paired Dev recipe; review rename, move or removal",
                    }
                ],
            }
            for record in sorted(
                listing.prod_only, key=lambda record: (*record["folder_path"], record["name"])
            )
        ]
    dev_project, prod_project = (
        listing.entry["dev"]["project_id"],
        listing.entry["prod"]["project_id"],
    )
    dev_only = set(listing.entry.get("dev_only_properties", []))
    states = property_states(
        wkrepo.property_values("dev", dev_project),
        wkrepo.property_values("prod", prod_project),
    )
    return {
        "project": listing.slug,
        "name": listing.entry["name"],
        "dev_project_id": dev_project,
        "prod_project_id": prod_project,
        "recipes": recipes,
        "properties": [
            {
                "name": name,
                "state": state,
                "expected": name in dev_only and state == "missing in Prod",
            }
            for name, state in states
        ],
    }


def print_recipe(entry: Json) -> None:
    """Print the findings of one recipe."""
    running = entry.get("prod_running")
    state = "" if running is None else " (Prod running)" if running else " (Prod stopped)"
    dev_url = wkrepo.recipe_url(entry["dev_id"]) if entry["dev_id"] else "-"
    prod_url = wkrepo.recipe_url(entry["prod_id"]) if entry["prod_id"] else "-"
    print(f"\n{entry['name']}{state}\n  Dev {dev_url}  Prod {prod_url}")
    for finding in entry["findings"]:
        kind = finding["kind"]
        if kind in {"CODE", "COMMENT"}:
            print(f"  {kind} step {finding['step']} {finding['field']}:")
            print(f"    Dev : {finding['dev']}\n    Prod: {finding['prod']}")
        elif kind == "BINDING":
            print(f"  BINDING {finding['slot']}: {finding['note']}")
        else:
            print(f"  {kind}: {finding['note']}")


def print_report(report: Json) -> int:
    """Print the report for a person and return how many things differ."""
    differences = 0
    for section in report["projects"]:
        differing = [entry for entry in section["recipes"] if entry["findings"]]
        properties = [item for item in section["properties"] if not item["expected"]]
        differences += len(differing) + len(properties)
        print(
            f"\n== {section['project']}: {len(section['recipes'])} recipes checked, "
            f"{len(differing)} differ between Dev and Prod"
        )
        for entry in differing:
            print_recipe(entry)
        if properties:
            print("\nProject properties:")
            for item in properties:
                print(f"  {item['name']}: {item['state']}")
    for finding in report["id_map_findings"]:
        print(f"\nIDMAP: {finding['note']}")
    if report["id_map_unconfirmed"]:
        print(
            "\nAccepted without a name to compare (the step stores no asset name; check by hand):"
        )
        for line in report["id_map_unconfirmed"]:
            print(f"  {line}")
    return differences + len(report["id_map_findings"])


def deployed_projects() -> list[str]:
    """Return the projects that exist in both environments, in the order of the registry."""
    return [slug for slug in wkrepo.snapshot_projects("prod") if "dev" in wkrepo.project(slug)]


def main(argv: list[str] | None = None) -> int:
    """Compare the selected projects, write the report and print it; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "projects",
        nargs="*",
        metavar="project",
        help="project slugs (default: every project in Dev and Prod)",
    )
    parser.add_argument(
        "--recipe", nargs="+", type=int, default=[], metavar="ID", help="only these Dev recipes"
    )
    parser.add_argument(
        "--pair",
        action="append",
        type=parse_pair,
        default=[],
        metavar="DEV_ID:PROD_ID",
        help="counterpart of a reviewed rename or move; repeatable",
    )
    args = parser.parse_args(argv)

    known = deployed_projects()
    selected = args.projects or known
    for slug in selected:
        if slug not in known:
            wkrepo.project(slug)  # an unknown slug fails here with the registry's message
            raise cli.Error(f"{slug} is not synced in both Dev and Prod; see the registry")
    # Every deployed project is read: a recipe may call a recipe function of another project.
    read = listings(known, args.pair, selected)
    chosen = [listing for listing in read if listing.slug in selected]
    only = set(args.recipe)
    unknown = only - {dev["id"] for listing in chosen for dev, _ in listing.pairs}
    if unknown:
        raise cli.Error(f"not a Dev recipe of the selected projects: {sorted(unknown)}")

    run = Run(
        dev_profile=wkrepo.profile("dev"),
        prod_profile=wkrepo.profile("prod"),
        recipe_ids={
            dev["id"]: prod["id"] for listing in read for dev, prod in listing.pairs if prod
        },
        dev_connections={
            item["id"]: item for item in wkrepo.list_connections(wkrepo.profile("dev"))
        },
        prod_connections={
            item["id"]: item for item in wkrepo.list_connections(wkrepo.profile("prod"))
        },
    )
    shared = frozenset(
        folder_id
        for listing in read
        if listing.entry.get("shared_connections")
        for folder_id in listing.dev_folders
    )
    now = datetime.now(UTC)
    report: Json = {
        "checked_at": now.isoformat(),
        "projects": [
            project_section(listing, only, run, listing.dev_folders | shared)
            for listing in chosen
            if not only or only & {dev["id"] for dev, _ in listing.pairs}
        ],
    }
    report["id_map"] = {name: sorted(seen) for name, seen in sorted(run.id_pairs.items())}
    report["id_map_findings"] = idmap_findings(run.id_pairs)
    report["id_map_unconfirmed"] = unconfirmed(run.id_pairs)

    out = OUT_DIR / f"drift-{now:%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    differences = print_report(report)
    checked = sum(len(section["recipes"]) for section in report["projects"])
    print(
        f"\n{checked} recipes checked in {len(report['projects'])} project(s). Full result: ",
        end="",
    )
    print(out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out)
    return cli.EXIT_FINDINGS if differences else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

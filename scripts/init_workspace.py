#!/usr/bin/env python3.14
"""Create the workspace folder of this repository from two `wk` profiles, or add what is new.

    scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
    scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod --pair 1001=1002

It reads `wk auth list` and the project list of both environments, then writes
workato/workspaces/<workspace>/registry.json, copies workato/workspace-template/ next to it and
runs scripts/sync_harness.py. It reads no token and changes nothing in Workato.

Projects are paired between Dev and Prod by exact name, when that name is used once in each
environment, or by --pair DEV_ID=PROD_ID; nothing is guessed. A project in both environments gets
"snapshots": true, a project only in Dev is registered without Prod, a project only in Prod is
listed and not registered. When two projects would get the same slug, or a slug is reserved, name
one with --slug PROJECT_ID=SLUG. Workato's default project (Home) has no folder of its own: it is
listed and not registered.

Run again for the same workspace it adds what is new: new projects, and the Prod half of a
project that has been deployed since. It finds a registered project by its Dev project id, so a
rename in Workato keeps its slug and updates `name`. --maintainer and --company-domain change
those two settings; a run without them leaves them alone. It never removes an entry, changes no
other key, and never overwrites a file it copied from the template. It writes registry.json with
its own formatting.

It refuses, and writes nothing, when a profile is unknown to `wk`, when the two profiles are in
different data centers, are swapped or reach the same environment, and when another workspace
folder exists.

Exit status: 0 done; 1 done, but a project needs --slug, or a --pair or --slug named no project;
2 refused.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
TEMPLATE = ROOT / "workato" / "workspace-template"
PLACEHOLDER = "{workspace}"
DESCRIPTION = (
    "The Workato projects of this workspace and where they live in each environment. Scripts "
    "read profile names and ids from here; nothing else hardcodes them. Every key is explained "
    "in docs/conventions/registry.md."
)


@dataclass
class Outcome:
    """What one run did, for the summary."""

    added: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)  # got their Prod half
    renamed: list[str] = field(default_factory=list)
    dev_only: list[str] = field(default_factory=list)
    prod_only: list[str] = field(default_factory=list)
    unnamed: list[str] = field(default_factory=list)  # need --slug
    no_folder: list[str] = field(default_factory=list)  # the default project of Workato
    gone: list[str] = field(default_factory=list)  # registered, no longer listed by Workato
    unused: list[str] = field(default_factory=list)  # a --pair or --slug that named no project


def id_pairs(option: str, values: list[str]) -> dict[int, str]:
    """Parse the ID=VALUE items of --pair or --slug."""
    pairs = {}
    for value in values:
        key, target = (*re.split("[=:]", value, maxsplit=1), "")[:2]  # `:` as prod_drift.py takes
        if not key.isdigit() or not target:
            raise cli.Error(f"{option} needs PROJECT_ID=VALUE, got '{value}'")
        pairs[int(key)] = target
    return pairs


def checked_options(pairs: dict[int, str], slugs: dict[int, str]) -> None:
    """Refuse a --pair that is not two ids and a --slug that cannot name a folder."""
    for dev_id, prod_id in pairs.items():
        if not prod_id.isdigit():
            raise cli.Error(f"--pair needs DEV_ID=PROD_ID with two project ids, got {dev_id}=...")
    if len(set(pairs.values())) != len(pairs):
        raise cli.Error("--pair names one Prod project for two Dev projects")
    for value in slugs.values():
        if not wkrepo.SLUG.fullmatch(value):
            raise cli.Error(
                f"--slug: '{value}' is not a slug; use lower-case words and digits joined by "
                "dashes"
            )
        if value in wkrepo.RESERVED_SLUGS:
            raise cli.Error(f"--slug: '{value}' is reserved, it is a folder of docs/")


def checked_profiles(dev: str, prod: str) -> tuple[Json, Json]:
    """Return the `wk` entries of both profiles, or refuse a pair that cannot be Dev and Prod."""
    known = {item.get("name"): item for item in wkrepo.profiles()}
    for env, name in (("dev", dev), ("prod", prod)):
        if name not in known:
            raise cli.Error(
                f"wk has no profile '{name}'. Sign in first: "
                f"wk auth login --name {name} --environment {env} --region <your region>"
            )
        if not wkrepo.PROFILE_NAME.fullmatch(name):
            raise cli.Error(
                f"the profile name '{name}' holds more than letters, digits, . _ -; sign in again "
                "under a plain name"
            )
    if wkrepo.base_url(dev) != wkrepo.base_url(prod):
        raise cli.Error(
            f"{dev} and {prod} are in different data centers; Dev and Prod must be two "
            "environments of one Workato account"
        )
    same = cli.Error(
        f"{dev} and {prod} reach the same environment. The kit needs a Dev and a Prod "
        "environment of one account; an account with a single environment is not supported"
    )
    if dev == prod:
        raise same
    for env, name, other in (("dev", dev, "prod"), ("prod", prod, "dev")):
        if str(known[name].get("environment") or "").lower() == other:
            raise cli.Error(
                f"wk holds the profile '{name}' as signed in to {other}, but it was given as the "
                f"{env} profile; swap --dev-profile and --prod-profile"
            )
    ids = [known[name].get("workspace_id") for name in (dev, prod)]
    if None in ids:
        raise cli.Error(
            "wk auth list gives no workspace id for these profiles, so Dev and Prod cannot be "
            "told apart; update wk and sign in again (docs/setup/workato.md)"
        )
    if ids[0] == ids[1]:
        raise same
    return known[dev], known[prod]


def new_registry(dev: Json, prod: Json) -> Json:
    """Return the registry of a workspace that has no projects yet."""
    return {
        "description": DESCRIPTION,
        "maintainer": "",
        "app_url": wkrepo.app_host(wkrepo.base_url(str(dev["name"]))),
        "company_domains": [],
        "environments": {
            "dev": {"profile": dev["name"], "workspace": dev.get("workspace", "")},
            "prod": {"profile": prod["name"], "workspace": prod.get("workspace", "")},
        },
        "projects": {},
    }


def checked_registry(registry: Json, dev: Json, prod: Json) -> None:
    """Refuse to continue a workspace that was created with other profiles."""
    for env, entry in (("dev", dev), ("prod", prod)):
        registered = registry.get("environments", {}).get(env, {}).get("profile")
        if registered != entry["name"]:
            raise cli.Error(
                f"the registry names the {env} profile '{registered}', not '{entry['name']}'; "
                "edit the registry if the profile was renamed"
            )


def label(project: Json, env: str) -> str:
    """Return a project as the summary names it."""
    return f"{project['name']} ({env} project {project['project_id']})"


def location(project: Json) -> Json:
    """Return the ids of a project as the registry stores them."""
    return {"project_id": project["project_id"], "folder_id": project["folder_id"]}


class Pairing:
    """Which Prod project is the same project as a Dev one: by --pair, else by a unique name."""

    def __init__(self, dev: list[Json], prod: list[Json], pairs: dict[int, str], taken: set[int]):
        self.by_id = {project["project_id"]: project for project in prod}
        self.pairs = {dev_id: int(prod_id) for dev_id, prod_id in pairs.items()}
        self.taken = set(taken)  # Prod projects the registry already holds
        # A Prod project named in a --pair is never given away by a name match.
        self.used = self.taken | set(self.pairs.values())
        self.consulted: set[int] = set()  # Dev ids whose --pair was looked at
        self.dev_names = Counter(project["name"] for project in dev)
        self.prod_names = Counter(project["name"] for project in prod)

    def match(self, project: Json) -> Json | None:
        """Return the Prod project of a Dev project, or None when there is none to be sure of."""
        wanted = self.pairs.get(project["project_id"])
        if wanted is not None:
            self.consulted.add(project["project_id"])
            if wanted not in self.by_id or wanted in self.taken:
                raise cli.Error(f"--pair: Prod has no unpaired project with the id {wanted}")
            return self.by_id[wanted]
        name = project["name"]
        if self.dev_names[name] != 1 or self.prod_names[name] != 1:
            return None  # the same name twice: pairing would be a guess
        found = next(item for item in self.by_id.values() if item["name"] == name)
        if found["project_id"] in self.used:
            return None
        self.used.add(found["project_id"])
        return found


def slug_problem(slug: str, entries: Json, shared: set[str]) -> str | None:
    """Return why a slug cannot be given to a new project, or None when it can."""
    if not wkrepo.SLUG.fullmatch(slug):
        return "is not lower-case Latin words and digits joined by dashes"
    if slug in wkrepo.RESERVED_SLUGS:
        return "is reserved, it is a folder of docs/"
    if slug in entries or slug in shared:
        return "is taken by another project"
    return None


def merge_projects(
    registry: Json,
    dev_projects: list[Json],
    prod_projects: list[Json],
    pairs: dict[int, str],
    slugs: dict[int, str],
) -> Outcome:
    """Add to the registry what is new in Workato; never remove or overwrite an entry."""
    outcome = Outcome()
    entries: Json = registry["projects"]
    # Workato lists its default project with the folder id 0: it has no folder to walk.
    outcome.no_folder = sorted(
        project["name"] for project in dev_projects if not project["folder_id"]
    )
    dev_projects = [project for project in dev_projects if project["folder_id"]]
    prod_projects = [project for project in prod_projects if project["folder_id"]]
    by_dev_id = {entry["dev"]["project_id"]: slug for slug, entry in entries.items()}
    listed = {project["project_id"] for project in dev_projects}
    outcome.gone = sorted(
        f"{slug} (Dev project {dev_id})"
        for dev_id, slug in by_dev_id.items()
        if dev_id not in listed
    )
    taken = {entry["prod"]["project_id"] for entry in entries.values() if "prod" in entry}
    pairing = Pairing(dev_projects, prod_projects, pairs, taken)
    wanted = {
        project["project_id"]: slugs.get(project["project_id"]) or wkrepo.slug(project["name"])
        for project in dev_projects
        if project["project_id"] not in by_dev_id
    }
    shared = {slug for slug in wanted.values() if list(wanted.values()).count(slug) > 1}
    for project in sorted(dev_projects, key=lambda item: item["name"]):
        slug = by_dev_id.get(project["project_id"])
        if slug is None:
            slug = wanted[project["project_id"]]
            problem = slug_problem(slug, entries, shared)
            if problem:
                outcome.unnamed.append(f"{label(project, 'Dev')}: the slug '{slug}' {problem}")
                continue
            entries[slug] = {"name": project["name"], "snapshots": False, "dev": location(project)}
            outcome.added.append(slug)
        elif entries[slug]["name"] != project["name"]:
            outcome.renamed.append(f"{slug}: now '{project['name']}' in Workato")
            entries[slug]["name"] = project["name"]
        entry = entries[slug]
        if "prod" not in entry:
            match = pairing.match(project)
            if match is None:
                outcome.dev_only.append(label(project, "Dev"))
                continue
            entry["prod"] = location(match)
            entry["snapshots"] = True
            if slug not in outcome.added:
                outcome.completed.append(slug)
    paired = {entry["prod"]["project_id"] for entry in entries.values() if "prod" in entry}
    outcome.prod_only = [
        label(project, "Prod")
        for project in sorted(prod_projects, key=lambda item: item["name"])
        if project["project_id"] not in paired
    ]
    outcome.unused = [
        f"--pair {dev_id}=...: no Dev project {dev_id} that still lacks its Prod half"
        for dev_id in sorted(set(pairs) - pairing.consulted)
    ] + [
        f"--slug {dev_id}=...: no new Dev project {dev_id} (a registered project keeps its slug)"
        for dev_id in sorted(set(slugs) - set(wanted))
    ]
    return outcome


def copy_template(folder: Path, workspace: str) -> list[str]:
    """Copy the files of the workspace template that the folder lacks; return what was added."""
    added = []
    for source in sorted(path for path in TEMPLATE.rglob("*") if path.is_file()):
        target = folder / source.relative_to(TEMPLATE)
        if source.is_symlink() or target.exists() or target.is_symlink():
            continue  # a link could point outside the repository: never follow one
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in {".md", ".json"}:
            text = source.read_text(encoding="utf-8").replace(PLACEHOLDER, workspace)
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(source, target)
        added.append(target.relative_to(ROOT).as_posix())
    return added


def listing(title: str, items: list[str]) -> None:
    """Print a titled list, or nothing when it is empty."""
    if items:
        print(f"\n{title}")
        print("\n".join(f"  {item}" for item in items))


def report(outcome: Outcome, registry: Json) -> bool:
    """Print what the run did; return True when a person still has something to decide."""
    lines = [
        ("registered", outcome.added),
        ("now also in Prod (snapshots switched on)", outcome.completed),
        ("renamed in Workato, slug kept", outcome.renamed),
    ]
    for title, items in lines:
        for item in items:
            print(f"  {title}: {item}")
    snapshots = [slug for slug, entry in registry["projects"].items() if entry.get("snapshots")]
    print(
        f"{len(registry['projects'])} projects in the registry, {len(snapshots)} with a Prod copy."
    )
    if outcome.no_folder:
        print(
            f"\nNot registered: {', '.join(outcome.no_folder)}. Workato lists its default project "
            "without a folder of its own, so recipes kept there stay outside the registry."
        )
    listing(
        "Not registered; name each with --slug PROJECT_ID=SLUG and run again:", outcome.unnamed
    )
    listing("Named no project; check the id and run again:", outcome.unused)
    listing(
        "In Dev only. After the first deployment of one, run this command again: it adds the "
        "Prod ids.",
        outcome.dev_only,
    )
    listing("In Prod only, not registered:", outcome.prod_only)
    if outcome.dev_only and outcome.prod_only:
        print(
            "\nIf a Dev-only and a Prod-only project are one project under two names, pair them "
            "with --pair DEV_ID=PROD_ID. If none is, there is nothing to do."
        )
    listing(
        "Registered, but Workato does not list it for the Dev profile any more (deleted, or the "
        "API client lost access). Nothing was removed; see docs/setup/maintaining.md:",
        outcome.gone,
    )
    return bool(outcome.unnamed or outcome.unused)


def checked_arguments(
    args: argparse.Namespace,
) -> tuple[dict[int, str], dict[int, str], list[str]]:
    """Return --pair, --slug and --company-domain as checked values, or refuse the call."""
    if not wkrepo.SLUG.fullmatch(args.workspace):
        raise cli.Error(
            "the workspace name must be lower-case words joined by dashes, for example "
            f"acme-corp; got '{args.workspace}'"
        )
    others = [name for name in wkrepo.workspaces() if name != args.workspace]
    if others:
        raise cli.Error(
            f"workato/workspaces/{others[0]}/ exists; one repository serves one workspace"
        )
    if os.environ.get("WK_WORKSPACE") not in (None, "", args.workspace):
        raise cli.Error(
            f"WK_WORKSPACE names another workspace than '{args.workspace}'; unset it first"
        )
    pairs, slugs = id_pairs("--pair", args.pair), id_pairs("--slug", args.slug)
    checked_options(pairs, slugs)
    domains = [domain.lower() for domain in args.company_domain]
    for domain in domains:
        if not wkrepo.DOMAIN.fullmatch(domain):
            raise cli.Error(
                f"--company-domain needs a domain such as acme.example, got '{domain}'"
            )
    return pairs, slugs, domains


def loaded_registry(registry_file: Path, dev: Json, prod: Json) -> Json:
    """Return the registry to extend: the one on disk, or a new one for these two profiles."""
    if not registry_file.exists():
        return new_registry(dev, prod)
    try:
        registry: Json = json.loads(registry_file.read_text(encoding="utf-8"))
    except ValueError:
        raise cli.Error(
            f"{registry_file.relative_to(ROOT).as_posix()} is not valid JSON: repair it first "
            "(scripts/check_data.py)"
        ) from None
    checked_registry(registry, dev, prod)
    return registry


def main(argv: list[str] | None = None) -> int:
    """Create or extend the workspace folder; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "workspace", help="name of the workspace folder: lower-case words and dashes"
    )
    parser.add_argument("--dev-profile", required=True, metavar="NAME", help="wk profile of Dev")
    parser.add_argument("--prod-profile", required=True, metavar="NAME", help="wk profile of Prod")
    parser.add_argument("--maintainer", metavar="TEXT", help="who decides about this workspace")
    parser.add_argument(
        "--company-domain", action="append", default=[], metavar="DOMAIN", help="repeatable"
    )
    parser.add_argument(
        "--pair", action="append", default=[], metavar="DEV_ID=PROD_ID", help="repeatable"
    )
    parser.add_argument(
        "--slug", action="append", default=[], metavar="PROJECT_ID=SLUG", help="repeatable"
    )
    args: argparse.Namespace = parser.parse_args(argv)

    pairs, slugs, domains = checked_arguments(args)
    dev, prod = checked_profiles(args.dev_profile, args.prod_profile)
    folder = wkrepo.WORKSPACES / args.workspace
    registry_file = folder / wkrepo.REGISTRY_NAME
    registry = loaded_registry(registry_file, dev, prod)
    if args.maintainer:
        registry["maintainer"] = args.maintainer
    known_domains = registry.setdefault("company_domains", [])
    for domain in domains:
        if domain not in known_domains:  # also a domain given twice in one call
            known_domains.append(domain)

    outcome = merge_projects(
        registry,
        wkrepo.list_projects(args.dev_profile),
        wkrepo.list_projects(args.prod_profile),
        pairs,
        slugs,
    )
    copied = copy_template(folder, args.workspace)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(
        f"Workspace folder: {folder.relative_to(ROOT).as_posix()}/ ({len(copied)} file(s) added)"
    )
    undecided = report(outcome, registry)

    print("\nHarness files (scripts/sync_harness.py):")
    sys.stdout.flush()  # what the script prints belongs after the lines above
    sync = [sys.executable, "-I", "-B", str(ROOT / "scripts" / "sync_harness.py")]
    if subprocess.run(sync, cwd=ROOT, check=False).returncode != 0:
        raise cli.Error("scripts/sync_harness.py failed; see its message above")
    print(
        "\nNext: finish the registry by hand, then scripts/doctor.py and "
        "scripts/sync_recipes.py prod."
    )
    print("The steps are in docs/setup/new-workspace.md.")
    return cli.EXIT_FINDINGS if undecided else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

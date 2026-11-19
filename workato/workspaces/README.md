# workato/workspaces/: the workspace of this repository

This folder holds the one Workato workspace the repository serves, in
`workato/workspaces/<workspace>/`. The kit ships it empty, with this README only.

`scripts/init_workspace.py` creates the workspace folder from two `wk` profiles, one for Dev and
one for Prod. It copies [workato/workspace-template/](../workspace-template/README.md) into the
new folder (`README.md`, `harness.json` and `notes/README.md`), writes `registry.json` and runs
`scripts/sync_harness.py`. It reads no token and changes nothing in Workato. The steps are in
[docs/setup/new-workspace.md](../../docs/setup/new-workspace.md). For example:

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
```

It registers a project that is in both environments as a managed project
(`"snapshots": true`) and a project that is only in Dev without Prod ids. It pairs the two halves
of a project by its exact name, when that name occurs once in Dev and once in Prod, or by
`--pair DEV_ID=PROD_ID`. A project only in Prod is listed and not registered. Workato's default
project, Home, has no folder of its own and is not registered either: recipes kept there stay
outside the registry.

Run it again later, with the same profiles, to add what is new in Workato:

- it adds new projects, and the Prod half of a project deployed since (and sets `snapshots` to
  `true`);
- it updates `name` after a rename in Workato and keeps the slug;
- `--maintainer` and `--company-domain` change those two settings; a run without them leaves
  them alone;
- it changes no other key and never removes an entry. A registered project that Workato no
  longer lists for the Dev profile is reported, and `docs/setup/maintaining.md` says what to do;
- it rewrites `registry.json` with its own formatting;
- it never overwrites a file it copied from the template.

Exit status: `0` done; `1` done, but a project needs `--slug`, or a `--pair` or `--slug` named no
project; `2` refused, with nothing written (one exception: when `scripts/sync_harness.py`
fails at the end, the registry is already written).

## What a workspace folder holds

| Path | What it holds |
|---|---|
| `registry.json` | the two environments with their `wk` profiles, and every project with its ids |
| `harness.json` | harness choices: optional MCP servers, extra Claude Code permissions, models |
| `notes/` | what this workspace adds to a skill of the kit, one file per skill |
| `projects/<slug>/` | the recipe JSON that runs in Prod, one folder per managed project |
| `message-templates/`, `connectors/`, `lookup-tables/` | sources and descriptions of workspace-level assets |
| `inventory/` | `recipes-index.json`, the generated recipe index; optionally `recipes.json`, a sheet kept by hand |
| `wklintrc.json` | optional: replaces the kit's lint configuration |

The README that `init_workspace.py` puts into the folder describes each of these and who writes
it. Every key of the registry and of `harness.json` is explained in
[docs/conventions/registry.md](../../docs/conventions/registry.md).

## One workspace per repository

A script finds the workspace as the only folder here that holds a `registry.json`. Without one,
every script that needs a workspace stops with this message (exit status `2`), and the offline
checks (`make check`) still pass:

```text
error: no workspace yet: run scripts/init_workspace.py (docs/setup/new-workspace.md)
```

`init_workspace.py` refuses to create a second workspace folder. If several folders with a
registry exist anyway, set `WK_WORKSPACE` to the name of the one to use; a script stops and asks
for it otherwise:

```bash
WK_WORKSPACE=acme scripts/doctor.py
```

## What never goes here

No secrets and no table data: no token, no password, no row of a lookup table or a data table.
Connection names and pointers only. Everything in a workspace folder belongs to the workspace
repository; none of it travels to the kit.

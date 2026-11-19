---
name: workato-assets
description: Rules for Workato assets other than recipe logic. Use before creating, updating, disconnecting or deleting a connection, tag, data table, lookup table, blueprint or any other Workato asset, and before deleting a recipe. Covers dependency checks, shared connections, which connections a recipe may bind, tags and tables.
---

# Connections, tags, tables, deletions

`<dev-profile>` and `<prod-profile>` below are `environments.dev.profile` and
`environments.prod.profile` of `workato/workspaces/<workspace>/registry.json`, for example
`acme-dev` and `acme-prod`. Every write here is made from the main conversation (rule **One
writer** of `AGENTS.md`), and in Dev unless the request names a write in Prod.

## Nothing destructive in silence

Delete an asset or disconnect a connection only when the request says so in words (rule
**Nothing destructive in silence**). Before you do, check for dependents and say what is being
destroyed and what depends on it.

- A recipe: find its callers. Observed for recipes called through the callable-recipes trigger:
  the titles of their jobs carry `Calling recipe ID=<n>` (`job_list`; see `workato-job-history`).
  Not verified for recipe functions. Add the static candidates from `change-impact-review`.
- A connection or a data table: list the recipes bound to it (below).

## Connections

**Which connection a recipe may bind** is rule **Connections stay in reach of a deployment**: a
connection of the recipe's own project, or of the project the registry marks
`"shared_connections": true`. Observed: a deployment leaves the Prod slot of any other connection
empty. The builder may offer other connections too: choose by project, not by name.

**Shared connections** live in the project marked `shared_connections`, for example `Common`
with its folder `[CM] Connections`. A recipe selects one with
`recipe_builder_select_connections`. A change to a shared connection reaches every project that
uses it: check its folder and its bound recipes, and name those dependents when you report the
change. Which shared connections the workspace has, and what each is for, is in its notes file
(below).

**Where to read them.** The connections of each managed project in Prod, with their exact names,
are in `workato/workspaces/<workspace>/projects/<slug>/index.json`. A recipe's bindings are the
`config` list of its JSON: one entry per connection slot, with its `account_id`. Search the
recipe JSON of the project (`projects/<slug>/` for Prod, `tmp/wk/dev/<slug>/` for Dev) for the
connection id to find the recipes bound to it.

```bash
wk -p <dev-profile> connections list --folder <folder id> -j
```

**A new connection.** When a recipe needs a connection its project does not have yet, create an
empty one in a folder of that project (or of the shared project):

```bash
wk -p <dev-profile> connections create --name "<name>" --provider <provider> --folder <folder id>
```

Apart from creating, `wk` can rename a connection (`wk connections update <id> --name`),
disconnect it and delete it; it cannot set the authentication. Disconnecting and deleting fall
under **Nothing destructive in silence**.
Then say what a person must set in the Workato UI: connector, authentication type, base URL,
which credential and with which rights. Never type the credential yourself and never read one
from a property or another connection (rule **Secrets**).

**Before any connection update**, read the connection and list the recipes bound to it: the
change reaches all of them. Afterwards read it again. Its `success` status does not prove a
working connection: a misconfigured authentication type can still report success, and a changed
credential may leave `updated_at` and the audit log untouched (observed:
`docs/knowledge/workato/recipe-builder-traps.md`). Prove it with a real call: the next job that
runs on its own, or a run a person asked for (rule **No jobs on your own**).

## Tags

The platform facts about tags, with their sources, are in
`docs/knowledge/workato/platform-notes-tags.md`.

- Write tags with `wk tags create`, `update`, `delete`, `apply` and `remove`. Observed: a tag can
  be added to a running recipe without a stop.
- Names, colors and descriptions follow the workspace's own convention, in its notes file.
- Tags are workspace-wide (documented). Before deleting or renaming a tag, list what carries it
  and name those assets in the same message as the change.
- Read the tags again after a change instead of trusting the command's result. Observed: `apply`
  reports success for a handle that does not exist, and `wk recipes list`, `wk recipes get` and
  the MCP server do not show an asset's tags. Read them through the API, the same way for
  `/connections`:

```bash
scripts/wk_api.py dev GET /recipes -q folder_id=<folder id> -q 'includes[]=tags'
```

- Say what changed.

## Data tables and lookup tables

- Before changing a data table's columns, truncating or deleting it, or writing or deleting its
  rows outside a recipe, list the recipes that read or write it and say what is destroyed or
  changed. Search the recipe JSON for the table's id; `tables` of the recipe index names a table
  only when the registry lists its id.
- Rows can contain personal data. Never quote a row in chat or in a file beyond what the task
  needs.
- After a column change, read the table again with `data_table_get`.
- Keep the state of one project in a data table inside that project; a lookup table serves data
  that several projects share.
- Each lookup table is described in `workato/workspaces/<workspace>/lookup-tables/` (purpose,
  fields, and a "Used by" list), refreshed by `scripts/sync_lookup_tables.py`. "Used by" lists
  the documented recipes whose index entry names the table, and the index records a table only
  when the registry lists its id under `tables` of a project. An empty list reads "The recipe
  index names no documented recipe for this table." and proves nothing: search the recipe JSON
  for the table's id. Never copy table rows into the repository (rule **No secrets and no table
  data in the repository**).

## Blueprints

For a workspace that uses the blueprint tools of the Workato MCP server:

- For an existing blueprint, `blueprint_pull` before applying edits.
- Not verified: `blueprint_push` overwrites without a conflict check. Check the saved state in a
  separate session before pushing; if it changed, reload and reapply the edits.
- Not verified: `blueprint_read` alone reads only the session's local copy. After pushing, pull
  the saved blueprint and verify it with `blueprint_read`.
- Report what changed.

## This workspace

If `workato/workspaces/<workspace>/notes/workato-assets.md` exists, read it before you act: it
holds what this workspace adds to this procedure.

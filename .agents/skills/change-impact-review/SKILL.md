---
name: change-impact-review
description: List what a Workato change touches before it is made. Use for a change that spans several recipes or a shared asset (a shared connection, a lookup table, a project property), for a deployment that touches a shared asset or several projects, for a decommission proposal, and when asked for the blast radius. Not for a routine edit of one named recipe.
---

# What does this change touch?

Analysis only: it authorizes no write. Say what the change is and which project and assets it
covers, then answer each question from the source named for it.

| Question | Where to look |
|---|---|
| Who calls it, and what does it call? | `calls` and `called_by` in `workato/workspaces/<workspace>/inventory/recipes-index.json` give candidates (`scripts/build_index.py` builds it; `docs/recipe-index.md` is the readable form). Confirm them in the recipe JSON (`workato-recipe-json`). Job history can show real callers (`workato-job-history`). No recent job does not prove that nobody calls it. |
| Which connections? | The bindings in the recipe JSON (the `config` list: one entry per connection slot, with its `account_id`) and the connections in `workato/workspaces/<workspace>/projects/<slug>/index.json`. A connection of the project the registry marks `shared_connections` reaches every project that binds it. A `success` status does not prove that a call works (observed: `docs/knowledge/workato/recipe-builder-traps.md`). |
| Which properties and tables? | Names only, never values or rows. Say what must exist in Prod before a deployment: `scripts/prod_drift.py` lists the properties that are missing, blank or different in Prod. `tables` of an index entry names the tables the recipe uses: the ones the registry names under `tables` of a project, and any other table a data table step or a lookup table step names by its id; `properties` names the project properties it reads. `scripts/doc_sync.py plan data_table:<id>` (or `lookup_table:<id>`, `connection:<id>`) lists the Dev recipes that use the asset, documented or not. The description of a lookup table in `workato/workspaces/<workspace>/lookup-tables/` has a "Used by" list: the documented recipes whose index entry names the table. An empty list proves nothing: a formula can read a table by name, so search the recipe JSON for the table's id and name. |
| What does a stop or a restart do? | `workato-start-stop`: a call to a stopped function fails, a polling trigger parks its cursor, a webhook may lose events, a schedule does not run while its recipe is stopped. |
| Which docs? | The recipe doc (`docs/<project-slug>/recipes/<dev_recipe_id>-<kebab-name>.md`), the runbooks in `docs/<project-slug>/runbooks/`, and wiki pages when the workspace keeps them (`confluence-recipe-pages`). `scripts/doc_sync.py plan <dev recipe id>` lists the docs around a recipe and says which are stale. |

Mark what you did not read as unknown; never infer behavior from a recipe name.

Report a table: asset, dependency, effect of the change, evidence, what you could not check. For
a decommission proposal the callers come before the recommendation (rule **A decommission
proposal states the blast radius** of `AGENTS.md`).

## This workspace

If `workato/workspaces/<workspace>/notes/change-impact-review.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

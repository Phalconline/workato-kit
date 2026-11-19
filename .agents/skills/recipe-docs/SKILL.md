---
name: recipe-docs
description: Write or update a recipe document in this repository. Use when documenting a Workato recipe, after changing a recipe, when moving or renaming a recipe doc, or when rebuilding the recipe index. Covers where a doc lives, its template, what a doc must never contain, and how the generated index is rebuilt.
---

# Recipe docs in this repository

## Where a doc lives

- One doc per recipe (**One doc per recipe**):
  `docs/<project-slug>/recipes/<dev_recipe_id>-<kebab-name>.md`, for example
  `docs/sales-orders/recipes/3001-so-rec-new-order.md`.
- `<project-slug>` is the slug of the Workato project the recipe sits in, from
  `workato/workspaces/<workspace>/registry.json`. Read the recipe's project id before you choose
  the folder (**Check the project first**): a name or a prefix does not tell you the project.
- A recipe has exactly one doc in the repository. Never keep a second copy elsewhere. When a
  recipe moves to another project, move its doc and fix the links to it.
- Docs carry **Dev** ids. A doc of a recipe that is also in Prod carries `prod_recipe_id` in its
  frontmatter; `scripts/link_prod_ids.py` writes it, never a person.
- Start from `docs/conventions/recipe-doc-template.md`. Its frontmatter and sections are the
  shape of every doc. Add a section only for a part that is genuinely complicated, such as a
  field mapping.

## Never invent behavior

Write only what you read in the recipe's JSON or in the Workato UI (**Never invent recipe
behavior**). Read the JSON with `workato-recipe-json`. What you could not read gets
`verified: unverified` in the frontmatter, and the doc says what is assumed.

## What a doc never contains

- **No step numbers** (**A recipe doc has no step numbers**). Describe what the recipe does, not
  where in the recipe it happens. Step numbers belong in chat and in a changelog, as Workato UI
  numbers (the JSON indexes the trigger as 0, so add 1).
- **No bare id for a called recipe.** Write the recipe's name as a link,
  `[<name>](<app_url>/recipes/<dev recipe id>)` with `app_url` from the registry, then the call
  type (synchronous or asynchronous) and the fields passed. The field names come from the calling
  step's `input.request` or `input.parameters`.
- **No provenance line**, such as "Documented from an export of N steps on <date>". Where a doc
  came from belongs in the frontmatter (`verified`, `last_reviewed`).
- **No personal data from jobs and no run counts** (**Real people stay out**): no e-mail address
  of a customer or a user. Dates of runs only; `<user>` in a quoted error.
- **No secret and no table data**: name a connection, a property or a table, never its value or
  its rows.
- **No link to a file under `tmp/`.** `scripts/check_links.py` fails on one.

A decommission proposal states the blast radius (who calls the recipe) before the recommendation
(**A decommission proposal states the blast radius**). Job history shows the callers
(`workato-job-history`).

## Generated index

`docs/recipe-index.md` and `workato/workspaces/<workspace>/inventory/recipes-index.json` are
generated (**Generated files are never edited by hand**). Rebuild both after a doc was added,
renamed or changed:

```bash
scripts/sync_recipes.py dev
scripts/build_index.py
```

The index reads the Dev JSON from `tmp/wk/dev/`, because docs carry Dev ids, so refresh that copy
first. The script takes `name`, `path`, `severity`, `owner`, `last_job` and `verdict` from the
frontmatter of each doc. From the Dev copy of each managed project it recomputes the trigger, the
step count, the connectors, the forward calls, `tables` (the tables whose id the registry lists
under `tables`) and `properties` (the project properties the recipe reads). It keeps the callers
(`called_by`) of the current index and adds the forward calls to them, and it carries over untouched
every key it does not write itself. A project without a Dev copy on your machine keeps its old
values, and the script says so. To see whether the index is current without writing:

```bash
scripts/build_index.py --check
```

Then check the links:

```bash
scripts/check_links.py
```

## This workspace

If `workato/workspaces/<workspace>/notes/recipe-docs.md` exists, read it before you act: it holds
what this workspace adds to this procedure.

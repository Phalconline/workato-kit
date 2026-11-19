---
name: workato-recipe-json
description: Read and refresh raw Workato recipe JSON. Use when you need the exact content of a recipe, when refreshing the Prod copy in workato/workspaces/<workspace>/projects/, when comparing Dev with Prod, when checking whether Prod was edited directly, or when you are about to use wk pull, wk diff or wk clone. Covers where the JSON lives, how to sync it with a plain GET, how to read it and how to run the lint.
---

# Recipe JSON: where it is and how to refresh it

## Where it lives

| Environment | Folder | In git |
|---|---|---|
| Prod | `workato/workspaces/<workspace>/projects/<slug>/` | yes |
| Dev | `tmp/wk/dev/<slug>/` | no, a personal cache |

- Layout: `<workato folders>/<recipe id>-<name>.recipe.json`, plus one `index.json` per project
  with the folders, the recipes (id, name, folder, file, `match_key`, version, running), the
  connections in the project's folders (with an `authorized` flag) and the names of the project
  properties. Property values and credentials are never read into the repository.
- Ids differ between environments, so the Dev file and the Prod file of one recipe have different
  names. Pair them by `match_key` (folder plus name), which is the same in both `index.json` files.
  A recipe doc is named with the Dev id and carries `prod_recipe_id` in its frontmatter;
  `scripts/link_prod_ids.py` writes it.
- Slugs, project ids and the `wk` profile of each environment are in
  `workato/workspaces/<workspace>/registry.json`. Only projects with `"snapshots": true` are synced
  by default.
- These files are generated: **Generated files are never edited by hand**.

## Refresh

```bash
scripts/sync_recipes.py prod
```

Every snapshot project, into the Prod copy.

```bash
scripts/sync_recipes.py prod --check
```

Writes nothing; exit `1` when the copy is stale. A stale copy is not proof that Prod was edited
directly.

```bash
scripts/sync_recipes.py dev <slug>
```

One Dev project, into `tmp/wk/dev/`. A slug named here is synced even when it is a Dev-only
project. A project the registry has no ids for in that environment is skipped with a message;
without a project argument the script syncs the managed projects only.

```bash
scripts/sync_recipes.py dev --recipe <id> [<id> ...]
```

Only these recipes, for example after a push. The files and index entries of the other recipes
stay as they are; the folders, connections and property names in `index.json` are refreshed. Only
a full sync removes the files of recipes that were deleted in Workato.

The script uses `wk recipes pull <id>`: one GET per recipe and no export manifest. Never use
`wk pull`, `wk diff` or `wk clone` for this (**No package commands**). Each project is fetched and
checked before its first file is written: a failed pull leaves that project and the ones after it
unchanged, while projects synced earlier in the same run stay refreshed. If a run dies while
writing, run it again. Exit `2` means Workato could not be read or a recipe id is unknown.

The Dev copy is a cache on your machine. Refresh it at the start of a task: it is never current
on its own, and another person's cache is not yours.

## When to refresh the Prod copy

**Keep the Prod copy true** says when: after every deployment and after any other change in Prod,
and with `--check` before a deployment. Commit the refreshed copy with the doc changes of the same
task: the history of `workato/workspaces/<workspace>/projects/` is the release history. When
`--check` reports a difference, git holds the previous copy, so refresh and read:

```bash
scripts/sync_recipes.py prod
git diff workato/workspaces/<workspace>/projects/
scripts/wk_api.py dev GET /deployments -q project_id=<dev project id>
```

That rule says which differences are a direct Prod edit and which are only a missed sync.

## Comparing Dev with Prod

Do not diff the two raw files: the JSON carries environment-local ids and UI caches, so a raw diff
is mostly noise. Run the comparison script:

```bash
scripts/prod_drift.py
scripts/prod_drift.py <slug>
scripts/prod_drift.py --recipe <dev recipe id> [<dev recipe id> ...]
```

Without arguments it compares every project that exists in Dev and in Prod; with a slug, one
project (a project with no Prod ids in the registry is refused); with `--recipe`, only the
recipes you are about to deploy. It pairs recipes by exact folder path and name inside one
project; a reviewed rename or move needs `--pair DEV_ID:PROD_ID` (`DEV_ID=PROD_ID` works too).
It ignores only what a deployment remaps (the id of a called recipe, data table, message template
and schema ids, the suffix of a custom connector, UI caches) and checks each of those instead of
masking it. Everything else is compared exactly. `MISSING` means no Prod recipe with that folder
and name: new, renamed or moved. Exit `1` means differences to read, `2` that the comparison could
not be made. The full result goes to `tmp/wk/prod-drift/`. The details are in
`scripts/README.md`.

`git diff workato/workspaces/<workspace>/projects/` answers a different question: what changed in
Prod between two syncs.

## Running the lint

`scripts/lint_recipes.py` refreshes the Dev copy with one GET per recipe, runs `wk lint` and adds
the house checks. It only reads Workato.

```bash
scripts/lint_recipes.py
scripts/lint_recipes.py <slug>
scripts/lint_recipes.py --recipe <dev recipe id> [<dev recipe id> ...]
```

Without arguments it lints the managed projects; a project that was never deployed is linted by
naming it. `--no-pull` checks the Dev copy already in `tmp/wk/dev/`. Exit `1` means at least one
error, `2` that the Dev copy could not be refreshed or `wk lint` did not answer. The raw output
is in `tmp/wk/lint.json`. What each check means is in the script's `--help`; the procedure around
a push is in `workato-recipe-edit`.

## Reading a recipe

- Trust the raw JSON over the render of the MCP recipe builder's pull. Observed: that render is
  lossy for arrays of datapills, labels of called recipes and step comments
  (`docs/knowledge/workato/recipe-builder-traps.md`).
- Print a recipe as a compact step tree:

  ```bash
  scripts/render_recipe.py <file.recipe.json>
  scripts/render_recipe.py <file.recipe.json> --full
  ```

  It prints Workato UI step numbers and datapills as the `#{...}` text they are stored as;
  `--full` prints long input values uncut.
- Step numbers in the JSON start at 0 for the trigger. The Workato UI starts at 1, so add 1 when
  you name a step in chat or in a changelog.
- One limit of the per-recipe endpoint: `private` and `concurrency` come back as the platform
  defaults (false and 1), not the real values (`wk recipes pull --help`). `wk recipes get <id> -j`
  is where to read the recipe's own values.
- Before any write to Workato, read the live recipe again (**Push procedure**). The copy on disk is
  only as true as its last sync.

## This workspace

If `workato/workspaces/<workspace>/notes/workato-recipe-json.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

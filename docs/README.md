# docs/: everything written by hand

The kit owns three folders here. Every other folder belongs to one Workato project of your
workspace.

| Folder | What it holds | Owner |
|---|---|---|
| [setup/](setup/README.md) | how to create a workspace repository, join one, update it from the kit, and connect `wk`, Workato and your AI harness | the kit |
| [conventions/](conventions/README.md) | the Python standard, the recipe doc template, the registry reference, the reasons behind the rules, and the workspace's own decision log (`decisions.md`) | the kit, except `decisions.md` |
| [knowledge/](knowledge/README.md) | notes on how the Workato platform behaves (`knowledge/workato/`); a workspace keeps its own notes in `knowledge/workspace/` | the kit, except `knowledge/workspace/` |
| `<project-slug>/` | the docs of one Workato project | the workspace |

The kit ships no project folder. There is no list of projects on this page: the projects and
their slugs are in the registry, `workato/workspaces/<workspace>/registry.json`. A project slug is
never `setup`, `conventions`, `knowledge` or `kit`, so a project folder cannot collide with a
folder of the kit.

## A project folder

A project folder is named by the project's slug in the registry, for example `sales-orders/` for
the project `Sales Orders`. Inside it:

| Folder | What it holds |
|---|---|
| `recipes/` | one doc per recipe, named `<dev_recipe_id>-<kebab-name>.md`, from [conventions/recipe-doc-template.md](conventions/recipe-doc-template.md) |
| `design/` | architecture, decisions of the project, specs, requirements |
| `runbooks/` | how to release, test and operate the project |
| `reference/` | connections, maps and background analysis that is still true |

Create a folder when it has something to hold; a small project may have `recipes/` only.

A recipe doc is named with the recipe's **Dev** id, because every change is made in Dev. Its
frontmatter carries `prod_recipe_id`, which `scripts/link_prod_ids.py` fills in from the Prod
copy. A recipe doc sits under the project the recipe is in, whatever its name says. For example
the doc of `[SO] LF | Create invoice` with the Dev id `3002` is
`sales-orders/recipes/3002-so-lf-create-invoice.md`.

## The recipe index

`docs/recipe-index.md` lists every documented recipe by project. `scripts/build_index.py`
generates it, together with `recipes-index.json` in the workspace's `inventory/` folder. Never
edit either by hand; the kit ships neither. Rebuild them after a recipe doc was added, renamed or
changed (the `recipe-docs` skill has the commands).

## Rules

The rules for writing docs are in `AGENTS.md` ("Documentation") and in the `recipe-docs` skill
(`.agents/skills/recipe-docs/`). A team that also keeps pages in Confluence follows the
`confluence-recipe-pages` skill.

# workato/workspaces/{workspace}/: the Workato workspace

Everything this repository keeps of the Workato workspace itself. The repository serves this one
workspace, with its Dev and its Prod environment. `scripts/init_workspace.py` created this folder
from the kit's workspace template. Run it again, with the same profiles, to add projects that are
new in Workato and the Prod half of a project after its first deployment. It never overwrites
this README, `harness.json` or `notes/README.md`, so a later change of the kit's template reaches
this folder only when you copy it from `workato/workspace-template/`.

The docs of each project are not here: they are in `docs/<project-slug>/` at the repository root.

| Path | What it holds | Who writes it |
|---|---|---|
| `registry.json` | the two environments with their `wk` profiles and Workato workspace names, every project with its slug, exact name and ids per environment, and the settings the scripts read | `scripts/init_workspace.py`, then by hand |
| [harness.json](harness.json) | harness choices of this workspace: optional MCP servers to switch on (`mcp_servers`), extra Claude Code allow rules (`claude_allow`), model overrides (`models`) | by hand, then `scripts/sync_harness.py` |
| [notes/](notes/README.md) | what this workspace adds to a skill of the kit: one Markdown file per skill | by hand |
| `projects/<slug>/` | the recipe JSON that runs in **Prod**, one folder per managed project, with `index.json` (recipes, folders, connections, property names) | `scripts/sync_recipes.py prod` only |
| `message-templates/` | the sources of the workspace's message templates | by hand |
| `connectors/` | the source code of custom connectors (Workato Connector SDK) | by hand |
| `lookup-tables/` | one description per lookup table: its purpose and its fields | `scripts/sync_lookup_tables.py`; the purpose and the field texts by hand |
| `inventory/` | `recipes-index.json`, the machine-readable recipe index; `doc-sync.json`, when the doc of each asset was last compared with Workato; optionally `recipes.json`, a sheet of recipes (a list of objects with `recipe_id` and any of `name`, `path`, `severity`, `owner`) that fills what a doc leaves empty | `recipes-index.json` by `scripts/build_index.py` only; `doc-sync.json` by `scripts/doc_sync.py stamp` only; `recipes.json` by hand |
| `wklintrc.json` | optional: the lint configuration of this workspace, used instead of the kit's `scripts/wklintrc.json` | by hand |

A folder that a script writes appears the first time the script runs. Every key of
`registry.json` and `harness.json` is explained in `docs/conventions/registry.md`.

## registry.json

Scripts read profile names, project ids and folder ids only from the registry: no script and no
kit file hardcodes them. Where a doc and the registry disagree, the registry is right.

After `scripts/init_workspace.py`, fill in by hand what it cannot know:

- `maintainer`: who decides about this workspace (a role or a team is enough);
- `company_domains`: the e-mail domains of the company, so that the lint reports a hardcoded
  address; optionally `lint_literal_patterns` for more hardcoded values to report, and
  `lint_prose_patterns` for words that do not belong in a recipe description or a comment;
- per project, when it applies: `shared_connections`, `dev_only_properties`, `lint_checks`,
  `lint_guard_property`, `lint_guard_parameter`, `lint_guard_exempt`, `tables`, `notes`, and for
  the optional Atlassian integration `confluence_main_page` and `jira`.

A project with `"snapshots": true` is a managed project: it exists in Dev and Prod, and its Prod
recipes are copied into `projects/`. `scripts/check_data.py` checks the structure and rejects an
unknown key. Until the first `scripts/sync_recipes.py prod`, it notes the managed projects that
have no Prod copy yet; that is not a failure. After a change to the profiles, to `app_url` or to
`harness.json`, run `scripts/sync_harness.py`: it rewrites the permissions of Claude Code, so a
person runs it or approves the run. It also checks `harness.json`: an unknown key is an error.

## Rules

- **No secrets.** No token, password or client secret in any file here. Connector code holds no
  credentials; a connector project's `master.key` and `settings.yaml` are git-ignored.
- **No table data.** A lookup table or a data table is described by its purpose and its fields.
  Its rows never enter the repository.
- **`projects/`, `inventory/recipes-index.json` and `inventory/doc-sync.json` are generated.**
  Nothing in them is edited by hand. The optional `inventory/recipes.json` is the one file of
  `inventory/` kept by hand.
- **Sources change nothing in Workato.** A message template or a connector here is a copy of the
  source. Changing it changes nothing in Workato until the asset is updated there; say in the
  change which environments were updated.
- **This folder is private.** It belongs to the workspace repository and never travels to the
  public kit.

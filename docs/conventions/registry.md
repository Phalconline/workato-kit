# The registry and `harness.json`

Everything a script needs to know about a workspace comes from two files in its folder,
`workato/workspaces/<workspace>/`:

| File | What it holds | Written by | Checked by |
|---|---|---|---|
| `registry.json` | the two environments, every project with its ids, and the settings the scripts read | `scripts/init_workspace.py`, then by hand | `scripts/check_data.py` (in `make check`) |
| `harness.json` | the harness choices of the workspace: optional MCP servers, extra permissions, models | the template, then by hand | `scripts/sync_harness.py`, and `scripts/sync_harness.py --check` (in `make check`); `scripts/check_data.py` only checks that it is JSON |

Scripts read ids and profile names only from the registry. Where a doc and the registry disagree,
the registry is right. After an edit of the registry run `scripts/check_data.py`. After an edit of
`harness.json`, or of the profiles or `app_url` in the registry, run `scripts/sync_harness.py`.

## A complete example

```json
{
  "description": "The Workato projects of the Acme workspace and where they live.",
  "maintainer": "Integration lead",
  "app_url": "https://app.workato.com",
  "company_domains": ["acme.example"],
  "lint_literal_patterns": {"ERP host": "erp\\.acme\\.example"},
  "notes": "",
  "environments": {
    "dev": {"profile": "acme-dev", "workspace": "Acme (Dev)"},
    "prod": {"profile": "acme-prod", "workspace": "Acme"}
  },
  "projects": {
    "sales-orders": {
      "name": "Sales Orders",
      "snapshots": true,
      "dev": {"project_id": 1001, "folder_id": 2001},
      "prod": {"project_id": 1002, "folder_id": 2002},
      "dev_only_properties": [],
      "lint_checks": ["NO_GUARD_PROPERTY"],
      "lint_guard_property": "protected_accounts",
      "lint_guard_parameter": "(^|_)account_id$",
      "lint_guard_exempt": [],
      "tables": {"5001": "Open orders"},
      "confluence_main_page": "7001",
      "jira": "SO",
      "notes": "Orders from the web shop."
    },
    "common": {
      "name": "Common",
      "snapshots": true,
      "shared_connections": true,
      "dev": {"project_id": 1003, "folder_id": 2003},
      "prod": {"project_id": 1004, "folder_id": 2004}
    },
    "sandbox": {
      "name": "Sandbox",
      "snapshots": false,
      "dev": {"project_id": 1005, "folder_id": 2005}
    }
  }
}
```

`sales-orders` and `common` are **managed projects**: they exist in Dev and Prod, and their Prod
recipes are copied into `workato/workspaces/<workspace>/projects/<slug>/`. `sandbox` exists in
Dev only. This example passes `scripts/check_data.py`.

## Rules for the whole file

- **An unknown key is an error.** `scripts/check_data.py` refuses a key it does not know, at the
  top, in an environment, in a project and in a project's `dev` or `prod`. A typo therefore fails
  `make check` instead of being ignored. Its message names the field, never its value. A
  misspelled project key `lint_check`, for example, gives:

  ```text
  Invalid registry: workato/workspaces/acme/registry.json: sales-orders: unknown key lint_check
  ```

- Some keys are read by scripts, others only by people and agents (the "Read by" columns below).
- The file is strict JSON: no comments, no duplicate key, no `NaN`.
- A new key is a change of the kit: it goes into `scripts/check_data.py` and onto this page.
- `scripts/init_workspace.py` rewrites the file with its own formatting when it runs again.

## Keys at the top

| Key | Type | Required | Meaning | Read by |
|---|---|---|---|---|
| `description` | text | no | what the file is; `init_workspace.py` writes a default | people |
| `maintainer` | text | no | who decides about this workspace: a new tool, a rule, a deployment policy. A role or a team is enough. `AGENTS.md` calls this person "the maintainer" | people and agents; `check_kit_files.py` reports it in a kit-owned file when it has two or more words |
| `app_url` | https address | no; default `https://app.workato.com` | the address of the Workato web app of the workspace's data center: the plain https address of a host below `workato.com` or `workatoapp.cn`, with no path, port, query or user. Otherwise `check_data.py` and `sync_harness.py` refuse it: "app_url must be the https address of a Workato web app". Used for links and for the Workato MCP server's address, never to send a token. The Workato MCP server is left out for the China address, `https://app.workatoapp.cn` | `wkrepo.app_url()` (links in `lint_recipes.py`, `build_index.py`, `prod_drift.py`, `prod_jobs_report.py`); `sync_harness.py` (fills `{app_url}` in `.agents/mcp.json`) |
| `company_domains` | list of lower-case domains | no | e-mail domains of the company. A hardcoded address in one of them is a lint finding | `lint_recipes.py` (`MAGIC_LITERAL`); `check_kit_files.py` (`NAME`) |
| `lint_literal_patterns` | object: label to regular expression | no | more hardcoded values the lint reports, besides a Slack channel id and a URL. A value that is not a regular expression is an error | `lint_recipes.py` (`MAGIC_LITERAL`) |
| `environments` | object | yes | exactly `dev` and `prod`; see below | every script that reaches Workato |
| `projects` | object: slug to project | yes | every registered project; see below | most scripts |
| `notes` | text | no | free text for people | no script |

`init_workspace.py` writes `description`, `maintainer` (empty, or the value of `--maintainer`),
`app_url` (from the base URL of the Dev profile), `company_domains` (from `--company-domain`),
`environments` and `projects`. Run again, it changes `maintainer` only when `--maintainer` is
given, and adds the domains of `--company-domain` to `company_domains`.

## Environments

`environments` holds exactly two entries, `dev` and `prod`. A Test environment, if the account has
one, is not registered and not used.

| Key | Type | Required | Meaning | Read by |
|---|---|---|---|---|
| `profile` | text: a letter or digit, then letters, digits, `.`, `_`, `-` | yes | the `wk` profile that reaches this environment, as `wk auth list` names it. Another character is an error: the name goes into the permission rules of Claude Code | `wkrepo.profile()`, so every script that reaches Workato; `sync_harness.py` writes read permissions for it; `init_workspace.py` refuses to continue a workspace with other profiles; `check_kit_files.py` (`NAME`) |
| `workspace` | text | yes | the name of the Workato workspace this profile must reach | `doctor.py` compares it with what the profile reaches; `check_kit_files.py` (`NAME`) |
| `notes` | text | no | free text for people | no script |

```json
"environments": {
  "dev": {"profile": "acme-dev", "workspace": "Acme (Dev)"},
  "prod": {"profile": "acme-prod", "workspace": "Acme"}
}
```

## Projects

The key of a project is its **slug**: lower-case Latin letters and digits, in words joined by
dashes, such as `sales-orders`. A key that is not a slug stops every script. The slug names the
folder of the project everywhere: `docs/<slug>/`, `workato/workspaces/<workspace>/projects/<slug>/`
and `tmp/wk/dev/<slug>/`. It stays when the project is renamed in Workato. **Reserved slugs:**
`setup`, `conventions`, `knowledge` and `kit`, because the first three are folders of `docs/` that
the kit owns.

| Key | Type | Required | Meaning | Read by |
|---|---|---|---|---|
| `name` | text | yes | the project's name in Workato | `sync_recipes.py` (`index.json`), `build_index.py`, `prod_drift.py`, `sync_lookup_tables.py`; `init_workspace.py` updates it after a rename in Workato and keeps the slug; `check_kit_files.py` (`NAME`, for a name of two or more words) |
| `snapshots` | boolean | yes | `true` makes it a managed project: its Prod recipes are copied into the repository, and it is linted and compared by default. Needs `prod`. `init_workspace.py` sets it when it adds the Prod half | `sync_recipes.py`, `lint_recipes.py`, `prod_drift.py`, `link_prod_ids.py`, `build_index.py` |
| `dev` | object | yes | the project in Dev: `project_id` and `folder_id` | `sync_recipes.py`, `prod_drift.py`, `doctor.py`, `sync_lookup_tables.py`; `init_workspace.py` finds a registered project by its Dev `project_id` |
| `prod` | object | when `snapshots` is true | the same for Prod | `sync_recipes.py`, `prod_drift.py`, `doctor.py` |
| `shared_connections` | boolean | no | `true` for the one project that holds the connections other projects use. `prod_drift.py` reports a Dev binding to a connection outside the recipe's own project and this one. Observed: a deployment leaves the Prod slot of any other connection empty | `prod_drift.py` (`BINDING`) |
| `dev_only_properties` | list of names | no | project properties that may be missing in Prod, for example one that only a Dev test needs | `prod_drift.py` |
| `lint_checks` | list of names | no | extra lint checks for this project: `ACCOUNT_PROPERTY` (a pill on a workspace account property instead of a project property), `NO_GUARD_PROPERTY` (see the next two keys). Another name is an error | `lint_recipes.py` |
| `lint_guard_property` | text | when `lint_checks` holds `NO_GUARD_PROPERTY` | the project property that lists the records automation must not touch, for example `protected_accounts` | `lint_recipes.py` |
| `lint_guard_parameter` | regular expression | when `lint_checks` holds `NO_GUARD_PROPERTY` | the parameter names that need the guard, for example `(^\|_)account_id$`. `NO_GUARD_PROPERTY` reports a recipe function that takes a parameter whose name matches, acts on something and never reads `lint_guard_property`: "takes '<parameter>' but never reads <property>". A value that is not a regular expression is an error | `lint_recipes.py` |
| `lint_guard_exempt` | list of recipe names | no | recipe functions the guard check skips, because their only caller reads the property first | `lint_recipes.py` |
| `tables` | object: table id (as text) to name | no | the tables (data tables, and lookup tables if you want them) whose id the recipe index looks for in recipe JSON. A recipe's index entry lists under `tables` the ones it holds, and a lookup table's description lists as "Used by" the documented recipes whose entry names it | `build_index.py`; `sync_lookup_tables.py` reads the result from the index |
| `confluence_main_page` | text | no | the project's main Confluence page, for the optional Atlassian integration | no script |
| `jira` | text | no | where the project's work is tracked in Jira, for the optional Atlassian integration | no script |
| `notes` | text | no | free text for people | no script |

The `dev` and `prod` objects hold exactly two keys:

| Key | Type | Meaning |
|---|---|---|
| `project_id` | positive integer, unique in its environment | the project's id in that environment |
| `folder_id` | positive integer, unique in its environment | the id of the project's root folder in that environment |

A recipe, a project and a folder have a different id in each environment, which is why both
halves are kept. `init_workspace.py` fills them from `wk folders list --projects`. Run again, it
adds new projects and the Prod half of a project deployed since, updates `name` after a rename,
and changes no other key of a project. It never removes an entry: a project that Workato no
longer lists for the Dev profile is reported, and `docs/setup/maintaining.md` says what to do.

## `harness.json`

Optional, and every key in it is optional. The template writes it with empty values; filled in,
it looks like this:

```json
{
  "mcp_servers": ["atlassian"],
  "claude_allow": ["Bash(scripts/ws_orders.py *)"],
  "models": {"claude": {"architect": {"model": null, "effort": "high"}}}
}
```

| Key | Type | Meaning |
|---|---|---|
| `mcp_servers` | list of names | the optional MCP servers of `.agents/mcp.json` to switch on. The kit has one, `atlassian`. A name that is not an optional server there is an error. The skills an optional server names are copied for Claude Code only while it is switched on |
| `claude_allow` | list of permission rules | added to the allow list of `.claude/settings.json`, before the kit's rules. It accepts only `Bash(scripts/ws_<name>.py)` and `Bash(scripts/ws_<name>.py *)` (the name in lower-case letters, digits and `_`), and `mcp__<server>__<tool>` of an optional server that is switched on. Anything else is refused: "Keep any other permission in your own .claude/settings.local.json" |
| `models` | object: provider, then role, then `model` and `effort` | overrides `.agents/models.json`, key by key. Providers are `claude` and `codex`; roles are those of `.agents/agents.json`. `effort` is one of `low`, `medium`, `high`, `xhigh`, `max` for `claude`, and `minimal`, `low`, `medium`, `high`, `xhigh` for `codex`. A `model` of `null` means the session's model |

Only `scripts/sync_harness.py` reads this file (also when `init_workspace.py` runs it). An
unknown key is an error, so a misspelled key does not pass silently:

```text
error: workato/workspaces/acme/harness.json: unknown key mcp_server; it is an object with the keys mcp_servers, claude_allow, models
```

Because the script rewrites the permissions of Claude Code, a person runs it or approves the
run. When `.claude/settings.json`
changes, it prints every permission rule it adds or removes, one per line, for example
`  allow + Bash(scripts/ws_orders.py *)`. It prints the MCP servers it adds or removes in
`.mcp.json` the same way. Read those lines before you commit.

## Next to the registry

| Path | Meaning | Read by |
|---|---|---|
| `wklintrc.json` | replaces the kit's `scripts/wklintrc.json` as the configuration of `wk lint` | `lint_recipes.py` |
| `inventory/recipes.json` | optional, kept by hand: a list of objects with `recipe_id` and any of `name`, `path`, `severity`, `owner`, which fills what a recipe doc leaves empty | `build_index.py` |
| `notes/<skill-name>.md` | what this workspace adds to a skill of the kit: names of its shared connections, its release order, where its wiki pages live. Every skill ends by pointing at its file | agents, when they load the skill |

## Environment variables

| Variable | Effect |
|---|---|
| `WK_WORKSPACE` | the workspace folder to use when `workato/workspaces/` holds more than one with a registry. One repository serves one workspace, so it is normally unset. For the scripts that use `scripts/lib/wkrepo.py`, a name that is not one of the folders is an error |
| `WK_PROFILE_DEV`, `WK_PROFILE_PROD` | replace the `profile` of that environment for every script that reaches Workato. The same characters are allowed as in the registry. `sync_harness.py` does not read them: the generated permissions name the registry's profiles |

## Related

- [python.md](python.md): how a script reads the registry (`scripts/lib/wkrepo.py`).
- [../setup/new-workspace.md](../setup/new-workspace.md): creating the workspace folder.
- [rationale.md](rationale.md): why the scripts take ids from here only.

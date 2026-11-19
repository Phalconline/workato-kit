# scripts/

The tooling of the repository: eighteen commands in Python 3.14 that use the standard library
only, and their shared code in `lib/`. Run them from the repository root. The ones that read
Workato also need `wk` and the two profiles of the workspace ([setup](../docs/setup/workato.md)).
How a script is written and tested is in
[docs/conventions/python.md](../docs/conventions/python.md).

Every script answers `--help` with its full description and does nothing else. That text is the
reference; this page is the overview.

## At a glance

| Script | Reaches Workato | Profile | Writes |
|---|---|---|---|
| `sync_recipes.py` | reads | the one of the environment given | Prod: `workato/workspaces/<workspace>/projects/`; Dev: `tmp/wk/dev/` |
| `lint_recipes.py` | reads, unless `--no-pull` | Dev | `tmp/wk/dev/`, `tmp/wk/lint.json` |
| `prod_drift.py` | reads | Dev and Prod | `tmp/wk/prod-drift/` |
| `prod_jobs_report.py` | reads | Prod, or `--profile` | `tmp/wk/prod-jobs/`, or the `--out` file, which must be under `tmp/` |
| `sync_lookup_tables.py` | reads | Dev | `workato/workspaces/<workspace>/lookup-tables/` |
| `wk_api.py` | reads; **writes** with `--write` | the one of the environment given | nothing |
| `link_prod_ids.py` | no | | the `prod_recipe_id` line of the recipe docs |
| `build_index.py` | no | | `workato/workspaces/<workspace>/inventory/recipes-index.json`, `docs/recipe-index.md` |
| `render_recipe.py` | no | | nothing; prints |
| `check.py` | no | | nothing but temporary test fixtures |
| `check_data.py` | no | | nothing |
| `check_kit_files.py` | no | | nothing |
| `check_links.py` | no | | nothing |
| `check_secrets.py` | no | | nothing |
| `sync_harness.py` | no | | the generated harness files, `.agents/generated-files.json` among them |
| `guard_wk.py` | no | | nothing |
| `init_workspace.py` | reads | the two given with `--dev-profile`, `--prod-profile` | `workato/workspaces/<workspace>/`, then what `sync_harness.py` writes |
| `doctor.py` | reads | Dev and Prod | nothing |

No script reads or prints an API token in the shell. A script that calls the API takes the token
from `wk` inside its own process and sends it only to the base URL `wk` holds for the profile,
and only when that is the plain https address of a host below `workato.com` or `workatoapp.cn`.
Otherwise it stops with:

```text
error: wk profile 'acme-dev' has no https base URL on a Workato host; sign in again (the scripts send a token to Workato only)
```

## Exit status

Every script uses the same three values:

| Status | Meaning |
|---|---|
| `0` | done; with `--check`, nothing differs |
| `1` | the script ran and found something: a difference, a lint error, a broken link, a failed check, a failed API call, a project that `init_workspace.py` could not register |
| `2` | the script could not do its job: Workato could not be read, a source is invalid, an argument is wrong, there is no workspace yet. The reason is one line on stderr that starts with `error:`. A crash also ends with `2`, after its traceback: a traceback always means a bug |

`guard_wk.py` is a hook and follows the hook protocol instead: `0` lets the command run, `2`
blocks it, and the reason on stderr goes to the agent.

A script that needs the workspace stops with exit `2` and this message until one exists:

```text
error: no workspace yet: run scripts/init_workspace.py (docs/setup/new-workspace.md)
```

A registry that is not JSON, or that has a project key that is not a slug, stops every script
that reads it with one line, for example:

```text
error: workato/workspaces/acme/registry.json is not valid JSON: run scripts/check_data.py
```

## Environment variables

| Variable | Effect |
|---|---|
| `WK_WORKSPACE` | the workspace folder to use when `workato/workspaces/` holds more than one registry. With exactly one, it is not needed |
| `WK_PROFILE_DEV` | the `wk` profile of Dev, instead of the one in the registry |
| `WK_PROFILE_PROD` | the `wk` profile of Prod, instead of the one in the registry |

A profile name, from the registry or from a variable, holds letters, digits, `.`, `_` and `-`
only. `init_workspace.py` takes its profiles from its arguments, not from these variables, and
refuses to run while `WK_WORKSPACE` names another workspace.

## Temporary output

Everything a script writes for you alone goes to `tmp/wk/`, which git ignores and a script can
rebuild:

| Path | Written by |
|---|---|
| `tmp/wk/dev/<project>/` | `sync_recipes.py dev`, and `lint_recipes.py` through it: the Dev recipe JSON and its `index.json` |
| `tmp/wk/lint.json` | `lint_recipes.py`: the raw output of `wk lint` |
| `tmp/wk/prod-drift/drift-<time>.json` | `prod_drift.py`: the full comparison |
| `tmp/wk/prod-jobs/jobs-<time>.json` | `prod_jobs_report.py`: jobs and audit events of a window, with e-mail addresses replaced by `<user>`. Other personal data in job titles and errors stays: treat the file as personal data |

Never link to a file under `tmp/` from a tracked file.

## Reading Workato

All of these only read, except `wk_api.py --write`.

### `sync_recipes.py {dev,prod} [project ...] [--recipe ID ...] [--check]`

Copies recipe JSON from Workato with `wk recipes pull <id>`: one GET per recipe and no export
manifest (rule **No package commands**). `prod` refreshes the copy in git,
`workato/workspaces/<workspace>/projects/<project>/`; `dev` refreshes the personal cache
`tmp/wk/dev/<project>/`. Each project folder holds one `<id>-<name>.recipe.json` per recipe, in
its Workato folders, and an `index.json` with the folders, the recipes (with `match_key`, folder
plus name, the same in Dev and Prod), the connections and the names of the project properties.
Property values and credentials are never read into the repository. A folder or recipe name
keeps its letters in the file name, in any alphabet; a name without a letter or digit becomes
`unnamed`.

- Without a project argument it syncs every managed project (`"snapshots": true` in the
  registry). Name a project to copy a Dev-only one into your cache. When the registry has no
  managed project, it says `No managed project has <env> ids in the registry: nothing to sync.
  Name a project to sync a Dev-only one.`
- A named project without ids in that environment is skipped with `<env> <slug>: the registry
  has no <env> ids for this project, skipped (after its first deployment run
  scripts/init_workspace.py again)`.
- Each project is fetched and checked before its first file is written. A failed pull leaves that
  project and the ones after it unchanged; projects synced earlier in the run stay refreshed.
- `--recipe` pulls only those recipes; the folders, connections and property names in
  `index.json` are refreshed too. Only a full sync removes the files of deleted recipes. Without a
  project argument only the managed projects are searched for the ids.
- `--check` writes nothing. A difference means the copy is stale, not that Prod was edited
  directly: refresh it and read the diff (rule **Keep the Prod copy true**).
- Exit: `0` done or nothing differs; `1` with `--check`, the copy is stale; `2` Workato could not
  be read or a recipe id is unknown.

### `lint_recipes.py [project ...] [--recipe ID ...] [--no-pull]`

Lints the Dev recipes of the managed projects, or of the projects named. A project that was
never deployed has no Prod copy and is not a managed project: lint it by naming it, also with
`--recipe`:

```bash
scripts/lint_recipes.py sandbox
```

It refreshes the Dev cache first with `sync_recipes.py dev` (skip with `--no-pull`), runs
`wk lint` with [wklintrc.json](wklintrc.json), or with the workspace's own `wklintrc.json` when
its folder has one, and adds the house checks:

| Check | Finds |
|---|---|
| `PROPERTY_MISSING` | a datapill on a project property that does not exist; a renamed property leaves its datapills on the old name |
| `MAGIC_LITERAL` | a hardcoded Slack channel id, URL or e-mail address of the company (`company_domains` in the registry), or a match of `lint_literal_patterns`, outside a variable or config step |
| `UNFINISHED_STEP`, `SKIPPED_STEP` | steps left unfinished or skipped |
| `ACCOUNT_PROPERTY` | only where the project lists it under `lint_checks`: a datapill on a workspace account property instead of a project property |
| `NO_GUARD_PROPERTY` | only where the project lists it under `lint_checks`: a recipe function that takes a parameter whose name matches the project's `lint_guard_parameter` (a regular expression, for example `(^|_)account_id$`), acts on something, and never reads the property named by `lint_guard_property`, the list of records automation must not touch. The message reads `takes '<parameter>' but never reads <property>`. A stub that only logs and returns, and the functions under `lint_guard_exempt`, are skipped |

Three lint rules misread platform-standard datapills; the script drops their known false
positives instead of switching the rules off. Step numbers in the output are UI numbers. Run
`--recipe <dev id>` after every push.

Exit: `0` no errors (warnings do not fail the run); `1` at least one error; `2` the Dev copy could
not be refreshed or read, `wk lint` did not answer, or the registry's lint settings are invalid.

### `prod_drift.py [project ...] [--recipe ID ...] [--pair DEV_ID:PROD_ID]`

Compares the Dev recipes with their Prod copies before a deployment, using both profiles.
Without a project argument it compares every project the registry has in Dev and in Prod.
Recipes are paired by exact folder path and name inside one project; a reviewed rename or move
needs `--pair`, which takes `DEV_ID:PROD_ID` or `DEV_ID=PROD_ID` and pairs two recipes
(`init_workspace.py --pair` pairs two projects). It ignores only what a deployment remaps (ids of
called recipes, tables, templates and schemas, a custom connector's numeric suffix, UI caches)
and checks each of those instead of masking it. It reports `CODE`, `COMMENT`, `NAME`,
`DESCRIPTION`, `BINDING` (a connection a deployment cannot map, see `shared_connections` in the
registry), `MISSING`, `PROD_ONLY`, `FOLDER` and `IDMAP`, and per project the state of each
property; values are never printed, and properties under `dev_only_properties` may be missing in
Prod.

Exit: `0` nothing differs; `1` something differs; `2` the pairing is invalid or ambiguous, or
Workato could not be read.

### `prod_jobs_report.py [--since ISO] [--until ISO] [--profile NAME] [--out FILE]`

Collects every job of the Prod workspace in a time window (by default the 24 hours before
`--until`, which is now by default), the failing step of each failed job, and the audit log of
the window: starts, stops, edits, connection changes. Only GET requests. A recipe whose jobs could
not be read is listed under `errors` and the run goes on. `--out` takes only a file under `tmp/`
(`--out must be a file under tmp/: a report holds job data`), because the command may run without
asking.

Exit: `0` done; `2` Workato could not be read at all, a time is not ISO 8601, or `--out` is
outside `tmp/`.

### `sync_lookup_tables.py [--check]`

Writes one Markdown file per lookup table of Dev, and a `README.md` index, into
`workato/workspaces/<workspace>/lookup-tables/`. It reads every page of the table list and the
column definitions only, never rows. The frontmatter, the field list and "Used by" are
generated; the purpose, the field descriptions and the `verified` and `personal_data` values are
a person's and are kept, also when a table is renamed in Workato.

"Used by" lists the documented recipes whose entry in the recipe index names the table. The
index records a table only when the registry lists its id under `tables` of a project
(`build_index.py`). An empty list reads "The recipe index names no documented recipe for this
table." and proves nothing.

Exit: `0` done or up to date; `1` with `--check`, a file is out of date; `2` Workato could not be
read.

### `wk_api.py {dev,prod} METHOD PATH [-q KEY=VALUE ...] [--json TEXT | --json-file FILE] [--write]`

One call to the developer API for what `wk` does not cover, for example:

```bash
scripts/wk_api.py dev GET /deployments -q project_id=1001
```

The environment selects the profile of the registry; the path is relative to that profile's API.
Anything but GET changes Workato and needs `--write`, which only stops an accident: whether the
change may be made is decided by the rules in `AGENTS.md`. A redirect is reported as an error,
never followed. A connection that breaks is reported by the kind of error, without a traceback.
`GET /properties` must name one property with `-q prefix=<full name>`, because a property can
hold a secret. Workato can answer HTTP 200 with `"success": false`; that counts as a failed call.

Exit: `0` success; `1` the call failed; `2` the request was refused, or `wk` gave no token.

## Local copies and docs

These read only files of the repository.

### `link_prod_ids.py [--check]`

Writes `prod_recipe_id` into the frontmatter of each recipe doc of the managed projects, pairing
the Dev and the Prod copy by `match_key` from `tmp/wk/dev/<project>/index.json` and
`workato/workspaces/<workspace>/projects/<project>/index.json`. Only that line is touched. A link
to a recipe that is still in Prod is never removed, only reported; a project without a Dev copy
is skipped. Run it after a deployment; when a recipe is new to Prod, run `sync_recipes.py dev`
first.

Exit: `0` done or up to date; `1` with `--check`, a doc is out of date.

### `build_index.py [--check]`

Rebuilds the recipe index, `workato/workspaces/<workspace>/inventory/recipes-index.json` and
`docs/recipe-index.md`: one entry per documented recipe, with the fields `recipe_id`, `name`,
`url`, `doc`, `project`, `path`, `severity`, `owner`, `trigger_type`, `step_count`, `connectors`,
`calls`, `called_by`, `tables`, `properties`, `last_job`, `findings_count` and
`verdict`. It reads:

- the frontmatter of the recipe docs (`name`, `path`, `severity`, `owner`, `last_job`,
  `verdict`), and an optional sheet `inventory/recipes.json` that fills what a doc leaves empty;
- the Dev copy in `tmp/wk/dev/` (refresh it first with `sync_recipes.py dev`): trigger, step
  count, connectors, forward calls, `tables` (the tables the registry names under `tables` whose
  id the recipe holds) and `properties` (the names of the project properties it reads). A
  "Call recipe" step without a target yet is recorded with
  `recipe_id: null`;
- the current index: the callers (`called_by`) are kept, and a key the script does not write is
  carried over untouched, so a workspace can keep facts of its own in an entry. Never delete the
  index.

A name comes from the doc's frontmatter first, then from the Dev JSON, then from the current
index.

Exit: `0` done or nothing would change; `1` with `--check`, a file would change.

### `render_recipe.py FILE [--full]`

Prints a `.recipe.json` file as a compact step tree with UI step numbers. Datapills show as the
`#{...}` text they are stored as. Long values are cut unless `--full` is given.

Exit: `0` done; `2` the file cannot be read as a recipe.

## Checking the repository

All offline: no Workato access, no credentials, no network. They pass without a workspace, and
between `init_workspace.py` and the first `sync_recipes.py prod`.

### `check.py`

What `make check` and CI run: Ruff lint, Ruff format, mypy, the unit tests, `check_data.py`, the
generated harness files (`sync_harness.py --check`), `check_links.py`, `check_secrets.py`,
`check_kit_files.py` and the ignore rules. A failed check does not stop the ones after it. Ruff and
mypy come from `.venv/`; `make dev` installs them once.

```bash
make check
```

Exit: `0` every check passed; `1` at least one failed; `2` Ruff and mypy are not installed, or the
interpreter is not Python 3.14.

### `check_data.py`

Every JSON file git would track must parse (a duplicate key, `NaN` or `Infinity` counts as
invalid), and the registry must be well formed, with no unknown key. File contents are never
printed; for a registry the field is named, never its value. Besides the structure it refuses:

- an `app_url` that is not the plain https address of a Workato web app (`app_url must be the
  https address of a Workato web app, alone`);
- a profile name with other characters than letters, digits, `.`, `_` and `-`;
- `lint_checks` other than `ACCOUNT_PROPERTY` and `NO_GUARD_PROPERTY`, and `NO_GUARD_PROPERTY`
  without both `lint_guard_property` and `lint_guard_parameter`;
- a `lint_literal_patterns` value or a `lint_guard_parameter` that is not a regular expression;
- `tables` that does not map a table id to its name.

A managed project without a Prod copy yet is a note, not a failure:

```text
note: no Prod copy yet of sales-orders: run scripts/sync_recipes.py prod
```

`harness.json` is only parsed here; its keys are checked by `sync_harness.py --check`. The keys
of both files are described in [docs/conventions/registry.md](../docs/conventions/registry.md).

Exit: `0` valid; `1` otherwise.

### `check_kit_files.py`

The files the kit owns must hold nothing of a workspace. A finding has one of these kinds: `NUMBER`
(five or more digits, the shape of a Workato id), `ADDRESS` (an e-mail address outside the example
domains), `HOST` (a host not on the script's list of public hosts, or a Workato webhook or API
endpoint host), `CODE` (a bracket code other than the examples'), `TICKET` (a ticket key other than
the examples'), `DATE` (a date before 2030; `CHANGELOG.md` is exempt), `SCRIPT` (text in a non-Latin
script), `PATH` (a home directory), `NAME` (a name the registry holds: both profiles, both Workato
workspace names, the company domains, and a maintainer or a project name of two or more words) and
`LINK` (a symbolic link). It cannot know a one-word name, a recipe name or a connection name: read a
change to a kit-owned file before you send it anywhere. The copyright line of `LICENSE` is not
checked: it names the copyright holder of the kit.

Not checked, because the workspace owns them: its folder under `workato/workspaces/`,
`docs/<project>/`, `docs/recipe-index.md`, `docs/conventions/decisions.md`,
`docs/knowledge/workspace/`, the last section of `AGENTS.md`, the workspace-owned names listed
under [A script of your workspace](#a-script-of-your-workspace), and the generated harness files.
The two vendor skills are checked by their publisher.

Exit: `0` nothing found; `1` at least one finding.

### `check_links.py [file ...]`

Every relative Markdown link must point to an existing file, and none may point into `tmp/`
(`tmp/README.md` excepted). External links and anchors are skipped. Without arguments it checks
every Markdown file outside `tmp/`. Exit: `0` every link resolves; `1` otherwise; `2` a file
given as an argument does not exist.

### `check_secrets.py`

Scans the files git would track and reports file, line and kind, never the value. It looks for
token-shaped strings (Slack, AWS, GitHub, JWT, private keys, `sk-` keys, a Workato API token
shape), a bearer token, a Workato webhook address, `token`, `secret`, `api_key` or `password`
assigned a value of twenty or more characters that mixes letters and digits, in any text file,
and literal secrets in recipe JSON. A dedicated scanner knows more formats; this one runs
everywhere without an install. Exit: `0` nothing found; `1` otherwise.

## The harness

### `sync_harness.py [--check]`

Writes the files each AI harness reads, from the sources in `.agents/` (skills, roles,
`agents.json`, `models.json`, `mcp.json`, `claude-settings.json`) and, when there is a workspace,
from its `registry.json` (`app_url`, the two profiles that get read permissions) and
`harness.json` (optional MCP servers, extra allow rules, model overrides). It writes
`.claude/settings.json`, `.claude/skills/`, `.claude/agents/`, `.codex/agents/`,
`.codex/config.toml`, `.mcp.json`, `.cursor/mcp.json`, `.gemini/settings.json`,
`.agents/mcp_config.json`, and `.agents/generated-files.json`, the list of the files it wrote. It
writes no credentials.

- It deletes a generated file whose source is gone, but only a file that
  `.agents/generated-files.json` names. A file a person put into `.claude/agents/` or
  `.claude/skills/` is left alone and printed as `left alone, not generated here: <path>`.
- The skills an optional server names in `.agents/mcp.json` are copied to `.claude/skills/` only
  while that server is switched on in `harness.json`.
- `harness.json`: an unknown key is an error. `claude_allow` accepts only
  `Bash(scripts/ws_<name>.py)`, `Bash(scripts/ws_<name>.py *)` and `mcp__<server>__<tool>` of an
  optional server that is switched on; anything else is refused with "Keep any other permission
  in your own .claude/settings.local.json".
- `app_url` must be the address of a Workato web app, because every harness signs in there. The
  Workato MCP server is left out when `app_url` is the address of the China data center.
- Role, skill and server names are plain (`[a-z0-9][a-z0-9-]*`), a role's color is one of eight
  names, and a symbolic link among the sources is refused.

It prints the allow and deny rules it adds (`+`) and removes (`-`) in `.claude/settings.json`,
and the MCP servers it adds and removes in `.mcp.json`. After a merge conflict in one of those two
files, resolve it, run the script, then compare with the last commit:

```bash
git diff HEAD -- .claude/settings.json .mcp.json
```

Because it rewrites the permissions of Claude Code, a person runs it or approves the run; only
`--check` is allowed without asking.

Exit: `0` done or up to date; `1` with `--check`, a file is out of date; `2` a source is invalid.

### `guard_wk.py`

A PreToolUse hook on shell commands: it reads the hook JSON on stdin and blocks

- `wk pull`, `wk diff`, `wk clone` and `wk push`, with any profile and in any flag order;
- every shell use of `wk auth token` and `wk mcp auth-header`;
- every command that names `profiles.env`, also by a glob in the current folder (`cat prof*`),
  except `ls`, `stat`, `test`, `chmod`, `touch` and three read-only `git` commands, and none of
  those when `xargs` could hand the name on;
- `wk ... -o <file>` with a file outside `tmp/`;
- `wk --verbose`, whose debug log may show the token;
- `xargs wk` with fewer than two subcommand words.

It also looks inside the `-c` text of a shell (`sh`, `bash`, `zsh`, `dash`, `ksh`, `fish`, `csh`,
`tcsh`) and inside `env -S`. It guards against mistakes and is not a security boundary: `eval`,
text piped into a shell, a command held in a variable, aliases, scripts, a program handed to
another interpreter (`python3 -c`, `perl -e`) and `grep -r` are out of its reach. It imports
nothing from `lib/`, so it keeps working when the rest of the tooling is broken. Claude Code runs
it from `.claude/settings.json`; `.codex/hooks.json` registers it for Codex (Not verified: the kit
was not used with Codex).

Exit: `0` the command may run; `2` it is blocked.

## Setting up

### `init_workspace.py WORKSPACE --dev-profile NAME --prod-profile NAME [...]`

Creates `workato/workspaces/<workspace>/` from two `wk` profiles, or adds what is new. It reads
`wk auth list` and the project list of both environments (never a token), writes
`registry.json`, copies the files of `workato/workspace-template/` that the folder lacks
(`README.md`, `harness.json`, `notes/README.md`), and runs `sync_harness.py`. Other options:
`--maintainer TEXT`, `--company-domain DOMAIN` (repeatable), `--pair DEV_ID=PROD_ID`
(repeatable; `DEV_ID:PROD_ID` works too) and `--slug PROJECT_ID=SLUG` (repeatable, for a slug
clash or a reserved slug).

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
```

Pairing: a Dev and a Prod project are one project when their exact name occurs once in Dev and
once in Prod, or when a `--pair` says so. A Prod project a `--pair` names is never taken by a name
match. A paired project gets `"snapshots": true`, a Dev-only project is registered without Prod,
and a Prod-only project is listed and not registered. Workato's default project, Home, has no
folder of its own: it is listed as "Not registered: Home. ..." and recipes kept there stay outside
the registry. A project left out for its slug says why: the slug "is not lower-case Latin words
and digits joined by dashes", "is reserved, it is a folder of docs/" or "is taken by another
project".

Output: a summary, then the line `Harness files (scripts/sync_harness.py):` and what that script
prints, then `Next: finish the registry by hand, then scripts/doctor.py and
scripts/sync_recipes.py prod.`

Run again, it finds projects by their Dev id. It adds new projects and the Prod half of a project
deployed since (and sets `snapshots` to true), updates `name` after a rename and keeps the slug.
`--maintainer` replaces the maintainer and `--company-domain` adds a domain; a run without them
leaves those settings alone. It changes no other key, never removes an entry, and lists a
registered project that Workato no longer shows to the Dev profile (see
`docs/setup/maintaining.md`). It rewrites `registry.json` with its own formatting and never
overwrites a file it copied from the template.

It refuses, writing nothing:

- a profile `wk` does not know, or one whose name holds other characters than letters, digits,
  `.`, `_` and `-`;
- two profiles in different data centers;
- the same profile twice, or two profiles with one `workspace_id` ("reach the same environment");
- swapped profiles: `wk` holds the `--dev-profile` as signed in to prod, or the reverse ("swap
  --dev-profile and --prod-profile");
- profiles without a `workspace_id` in `wk auth list` ("update wk and sign in again");
- another workspace folder, or `WK_WORKSPACE` set to another name;
- a workspace name that is not a slug, a `--company-domain` that is not a domain, a `--slug`
  value that is not a slug or is reserved, a `--pair` that is not two ids, one Prod id paired with
  two Dev projects, a `--pair` whose Prod project is missing or already registered;
- a registry already there that is not JSON, or that names other profiles.

The full walk-through is [docs/setup/new-workspace.md](../docs/setup/new-workspace.md).

Exit: `0` done, also when projects stay in Dev only or in Prod only (that is information, and
the output lists them under "In Dev only." and "In Prod only, not registered:" with the hint to
use `--pair` if two of them are one project); `1` done, but a project needs `--slug`, or a
`--pair` or `--slug` named no project; `2` refused.

### `doctor.py`

Runs `check.py`, then checks the personal setup read-only, under the heading
`Workato CLI access (read-only)`: `wk` is installed, the lint plugin is registered, and for the
Dev and the Prod profile: the profile exists and reaches Workato, `wk` holds it as signed in to
the right environment, it reaches the workspace the registry names, and its API client may read
what the scripts read (recipes, projects and folders, connections, project properties). It also
checks that both profiles are in one data center. Each line starts with `ok`, `note` or `FAIL`; a
profile that `wk` holds as signed in to the other environment gives a `FAIL` line that ends with
"the two profiles of the registry look swapped". It starts nothing and prints no token or
property value. Without a workspace it checks the tools only. The MCP sign-ins and the guard hook
of your harness are not covered.

Exit: `0` everything works; `1` a check failed or something is missing.

## Shared code

| Module | What it holds |
|---|---|
| `lib/cli.py` | what every script shares on the command line: the exit codes, `--help` from the docstring, one-line errors |
| `lib/wkrepo.py` | the repository's view of Workato: the workspace folder, the registry, profiles, paths, `wk` calls and API GETs |

## A script of your workspace

The kit owns every script above and replaces them when you merge a kit update. These names belong
to the workspace: the kit never uses them, so a merge never touches them, and
`check_kit_files.py` does not check them:

| Name | What it is |
|---|---|
| `scripts/ws_<name>.py` | a command of the workspace |
| `scripts/lib/ws_<name>.py` | shared code of the workspace's commands |
| `tests/test_ws_<name>.py` | its tests; also allowed without a script of that name, for tests of the workspace's own data or rules |
| `.agents/skills/ws-<name>/` | a skill of the workspace, listed in the last section of `AGENTS.md` |
| `.github/workflows/ws-<name>.yml` | a CI workflow of the workspace |

There is no workspace-owned role: `.agents/agents.json` is one file of the kit.

A workspace script follows the same conventions as the kit's scripts
([docs/conventions/python.md](../docs/conventions/python.md)). `make check` enforces the first
three:

- it starts with `#!/usr/bin/env python3.14`, is executable, and imports only the standard
  library and `lib`; a module in `scripts/lib/` is not executable;
- its docstring shows its usage as `scripts/ws_<name>.py ...` and holds an `Exit status:` line,
  and that docstring is its `--help`;
- `main(argv: list[str] | None = None) -> int` returns the exit status, and it has its test
  module `tests/test_ws_<name>.py`;
- the file ends with `cli.run(main)`, it uses the exit codes above, and it raises `cli.Error` for
  a problem the person can fix.

To let Claude Code run it without asking, add an allow rule to the workspace's `harness.json`, for
example `"claude_allow": ["Bash(scripts/ws_report.py *)"]`, and run `sync_harness.py`.

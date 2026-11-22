# Workato: the `wk` CLI, API clients and the MCP server

The repository reaches Workato in two ways. The `wk` CLI and the scripts read with an API client
token, one per environment. The agents build and edit recipes through Workato's MCP server, with
your own Workato user. This page covers both.

Checked with `wk` 1.1.0 and `recipe-lint` 1.2.0. `wk` comes from Workato Labs, which publishes it
without an SLA (<https://github.com/workato-devs/wk>); `wk --help` calls it "the official Workato
CLI tool". It is an accepted tool of the repository ("Integrations" in
[AGENTS.md](../../AGENTS.md)).

## Install

On macOS and Linux, from Workato's Homebrew tap:

```bash
brew install workato-devs/tap/wk workato-devs/tap/recipe-lint
```

Other ways, not tested here:

- Release binaries of `wk` for macOS and Linux are on its releases page
  (<https://github.com/workato-devs/wk>), and those of `recipe-lint` on
  <https://github.com/workato-devs/recipe-lint>. Workato's install guide
  (<https://github.com/workato-devs/labs>) says that on macOS a downloaded binary needs its
  quarantine attribute removed.
- `go install github.com/workato-devs/wk@latest` is possible; the `wk` README does not recommend
  it.
- On Windows, `wk` and `recipe-lint` come from Scoop. The kit itself runs on Windows only
  inside WSL; there, use the Linux way.

Register the lint plugin. `wk` finds `recipe-lint` on your PATH:

```bash
wk plugins install recipe-lint
```

Check the version with the subcommand (`wk --version` is an error):

```bash
wk version
```

If `scripts/doctor.py` reports the plugin as not registered after an upgrade, run
`wk plugins install recipe-lint` again.

## Data centers

Workato runs several data centers, each with its own address. Your account lives in one, and
both of your profiles must use it.

| Data center | Sign in with | Web app (`app_url`) | Workato MCP server |
|---|---|---|---|
| US | `--region us` (the default) | `https://app.workato.com` | `https://app.workato.com/airo_mcp` |
| EU | `--region eu` | `https://app.eu.workato.com` | `https://app.eu.workato.com/airo_mcp` |
| Japan | `--region jp` | `https://app.jp.workato.com` | `https://app.jp.workato.com/airo_mcp` |
| Singapore | `--region sg` | `https://app.sg.workato.com` | `https://app.sg.workato.com/airo_mcp` |
| Australia | `--region au` | `https://app.au.workato.com` | `https://app.au.workato.com/airo_mcp` |
| Israel | `--region il` | `https://app.il.workato.com` | `https://app.il.workato.com/airo_mcp` |
| China | `--region cn` | `https://app.workatoapp.cn` | none: Workato offers no AIRO MCP server there |
| South Korea | `--base-url https://app.kr.workato.com` | `https://app.kr.workato.com` | `https://app.kr.workato.com/airo_mcp` |
| UK | `--base-url https://app.uk.workato.com` | `https://app.uk.workato.com` | `https://app.uk.workato.com/airo_mcp` |

- `wk auth login --region` does not accept South Korea and the UK. `--base-url` sets the
  address directly and skips the region check.
- `--region trial` (Developer Sandbox) is a single-environment account, which the kit does not
  support ([new-workspace.md](new-workspace.md#who-this-is-for)).
- For the US, `wk` sends API calls to `https://www.workato.com`. Workato documents
  `https://app.workato.com/api`. This is `wk`'s choice; both answer.
- Only the US data center serves its API and its web app from two hosts. Elsewhere they are the
  same host.

**Where the token goes.** `wk` stores a base URL with each profile. The scripts ask
`wk auth list` for it and send the token only to that host, under `/api`, and only when it is
the plain https address of a host below `workato.com` or `workatoapp.cn`. Any other base URL
stops the script before the token is read:

```text
wk profile 'acme-dev' has no https base URL on a Workato host; sign in again (the scripts send a token to Workato only)
```

The scripts follow no redirect. No address in a file of the repository can send a token
elsewhere.

**What `app_url` is for.** The registry's `app_url` is the web app address. It is used for links
(recipe links in docs, the lint, the comparison, the recipe index) and for the address of the
MCP server in the generated harness files, so every harness sends its Workato sign-in there.
`scripts/init_workspace.py` writes it from the Dev profile's base URL. It must be the plain https
address of a Workato host and nothing more: `scripts/check_data.py` refuses anything else with
"app_url must be the https address of a Workato web app, alone", and `scripts/sync_harness.py`
refuses to write the harness files.

**China.** Workato offers no MCP server there, so `scripts/sync_harness.py` leaves the Workato
server out of the harness files when `app_url` is `https://app.workatoapp.cn`. Agents then work
with `wk` and the scripts only.

## Sign in

One profile per environment. The command asks for the API client token; paste it yourself.
Use the profile names of the registry, and your data center:

```bash
wk auth login --name acme-dev --environment dev --region eu
```

```bash
wk auth login --name acme-prod --environment prod --region eu
```

Make Dev the default profile. An agent runs `wk` without `-p` for Dev and adds `-p acme-prod`
for Prod:

```bash
wk auth switch acme-dev
```

Check:

```bash
wk auth list
```

```bash
wk -p acme-prod auth status
```

`auth status` shows the workspace and whether the API answers. It does not print the token.

The scripts take the profile names from the registry (`environments.dev.profile`,
`environments.prod.profile`). `WK_PROFILE_DEV` and `WK_PROFILE_PROD` in your shell override them.

## Where the token is kept

**The OS keychain** is the default of `wk auth login`, and the recommendation wherever one
exists.

**The file store** is for a machine without a keychain: a Linux server, WSL, CI. Sign in from
the repository root with the global flag `--store-type file`:

```bash
wk --store-type file auth login --name acme-dev --environment dev --region eu
```

Not verified (the kit was tested with the keychain only): `wk` then keeps the token as plain
text in `profiles.env` in the repository root, next to `.wk/wk.toml`.

The scripts read from `wk auth list` which store a profile uses and add `--store-type file`
themselves. A `wk` command typed by hand for such a profile needs the flag too, by you or by an
agent. In Claude Code such a command asks for approval every time: the shared allow rules cover
`wk -p acme-dev ...`, not `wk --store-type file -p acme-dev ...`. A person who wants the reads
without a prompt adds rules of that form to their own `.claude/settings.local.json`.

The risks of a plain-text token file:

- Every program that runs as you can read it: an agent's file tools, an editor plugin, a backup
  or sync tool.
- A copy of the repository folder copies the token with it.
- `git add -f` would commit it in spite of `.gitignore`.
- The token keeps working until a workspace admin regenerates it.

What the kit does about it:

| Protection | What it covers |
|---|---|
| `.gitignore` | `profiles.env`, `.wk/`, `.env`, `.env.*` and the Connector SDK secrets `master.key` and `settings.yaml` are never added by `git add`. `make check` fails if `profiles.env`, `master.key` or `.env` stop being ignored. |
| `scripts/guard_wk.py` | Blocks a shell command that names `profiles.env`, also through a glob in the current folder (`cat prof*`), except `ls`, `stat`, `test`, `chmod`, `touch`, and `git check-ignore`, `git status`, `git ls-files`, and those too when `xargs` could hand the name on. It runs as a hook in Claude Code and Codex. It guards against mistakes; it is not a security boundary: a command that reads a whole folder (`grep -r`), `eval`, or a program handed to another interpreter (`python3 -c`) is not recognized. |
| Claude Code deny rules | `Read(/profiles.env)`, `Read(/.env)`, `Read(/.env.*)`, `Read(/.wk/**)`, `Read(/workato/workspaces/**/master.key)` and `Read(/workato/workspaces/**/settings.yaml)` in the generated `.claude/settings.json`. The leading `/` anchors each rule at the repository root. A Read deny rule also blocks edits of the file and the file commands Claude Code recognizes in Bash (`cat`, `head`, `tail`, `sed`, `tee`); it does not cover `grep -r` or a script that opens the file itself (<https://code.claude.com/docs/en/permissions>). |
| `.cursorignore`, `.geminiignore` | List `profiles.env`, `.wk/`, `.env`, `.env.*`, `master.key` and `settings.yaml`. Not verified: how far Cursor and Gemini CLI keep an ignored file away from their agents. |
| `scripts/doctor.py` | Prints a `note` for each profile in the file store. |

Codex, GitHub Copilot and Antigravity get no ignore file from the kit. There, the guard (Codex
only) and the rule **Secrets** of [AGENTS.md](../../AGENTS.md) are what protect the file.

Keep the file readable by you alone:

```bash
chmod 600 profiles.env
```

To change a profile, use `wk auth login` or `wk auth delete`. If you must edit `profiles.env`,
open it in an editor yourself; an agent never reads it.

## API clients and privileges

A workspace admin creates the API clients in Workato's workspace admin pages, under API clients
(not verified: the menu path).

- An API client is created for **one environment**. Dev and Prod need one client each: two
  tokens, two profiles.
- A client gets a list of projects. That list limits what it sees of connections, recipes,
  folders, lookup tables and properties. Give each client every project in the registry,
  including the project that holds the shared connections. A project the client cannot see is
  missing from `scripts/init_workspace.py` and from the Prod copy.
- A client's role lists the API endpoints it may call. Workato publishes no complete list of
  privilege names, so the table names what each script reads. Find the matching entries on the
  role screen.
- Workato shows a token once. Regenerating it makes the old one invalid.

What the scripts read:

| Script | Environment | What it reads |
|---|---|---|
| `scripts/init_workspace.py` | Dev and Prod | the profiles (`wk auth list`) and the projects (`wk folders list --projects`) |
| `scripts/doctor.py` | Dev and Prod | the profile (`wk auth status`), one page of recipes, the projects, one page of connections, and the properties of the first project the registry has in that environment (`GET /properties`) |
| `scripts/sync_recipes.py` | Prod; Dev for your cache | for each project: its folders (`wk folders list --parent`), the recipes of each folder (`wk recipes list --folder`), then each recipe (`wk recipes pull`); every connection the client sees (`wk connections list`); the project properties (`GET /properties`, names kept) |
| `scripts/lint_recipes.py` | Dev | what `scripts/sync_recipes.py dev` reads, unless `--no-pull` is given; `wk lint` itself runs locally |
| `scripts/prod_drift.py` | Dev and Prod | for each project: its folders, the recipes of each folder, then each recipe (`wk recipes get`); every connection; the project properties with their values (`GET /properties`) |
| `scripts/prod_jobs_report.py` | Prod, or the profile `--profile` names | every recipe the client sees, the jobs of each in the window (`GET /recipes/<id>/jobs`), each failed job (`GET /recipes/<id>/jobs/<job id>`), and the audit log (`GET /activity_logs`) |
| `scripts/sync_lookup_tables.py` | Dev | the lookup tables with their column definitions (`GET /lookup_tables`, every page), never rows |
| `scripts/doc_sync.py` | Dev | every recipe the client sees, with its code (`wk recipes list`, every page), and every connection (`wk connections list`); `stamp` also reads each stamped recipe (`GET /recipes/<id>`). Never rows of a table |
| `scripts/wk_api.py` | the one you name | the endpoint you call; the deployments and the deploy call are in Dev. With `--data-tables`: the record API of data tables, on the `data-tables` host of the same data center |
| `scripts/render_recipe.py`, `scripts/link_prod_ids.py`, `scripts/build_index.py`, `scripts/check_step_numbers.py` | none | local files only |

`GET /properties` answers with names and values. `scripts/sync_recipes.py` keeps the names only,
`scripts/prod_drift.py` compares the values without printing them, and `scripts/wk_api.py`
prints one named property at a time. Workato does not document a masking of secret values here.

`scripts/doctor.py` tries the reads of its row with both clients and names the one that fails.
It does not try jobs, the audit log, lookup tables or deployments: a missing privilege there
shows when the script that needs it runs, for example as
`Workato answered HTTP 403 to GET /activity_logs`.

So the two clients need:

| Client | Reads | Writes |
|---|---|---|
| Dev | projects, folders, recipes, connections, project properties, lookup tables, deployments | what a person asks agents to do with `wk` and `scripts/wk_api.py`: start and stop recipes, update a recipe, tags, and deployments (below). Workato accepts a deployment only in the Dev environment's API. |
| Prod | projects, folders, recipes, connections, project properties, jobs, the activity log | none. Prod changes only by deployment, and the scripts only read Prod. |

The deployment call, as the `workato-prod-deploy` skill makes it:

```bash
scripts/wk_api.py dev POST /projects/<dev project id>/deploy --write \
  --json '{"environment_type": "prod"}'
```

Observed to work. Workato documents the form `POST /projects/<id>/deploy?environment_type=prod`,
which is `-q environment_type=prod` instead of `--json`
(<https://docs.workato.com/en/workato-api/projects.html>).

A read-only Prod client cannot start or stop a Prod recipe, write a project property or set a
tag in Prod. When a request asks for one of those, a person does it in the Workato UI. A
workspace that wants agents to make such a change gives its Prod client that privilege; the kit
needs none.

Workato's page on API clients: <https://docs.workato.com/en/workato-api/api-clients.html>.

## Commands you will use

| Command | What it does |
|---|---|
| `wk recipes get <id> -j` | one recipe's metadata, including `running` |
| `wk recipes list --folder <id> -j` | the recipes of a folder |
| `wk recipes pull <id> -o tmp/<file>` | one recipe as JSON in `wk`'s project format, by a plain GET; the guard lets `-o` write only below `tmp/` |
| `wk folders list --projects -j` | the projects of the environment |
| `wk connections list -j` | connections with their authorization status |
| `wk lint <files>` | lint recipe JSON; `scripts/lint_recipes.py` wraps it |
| `wk recipes stop <id>`, `wk recipes start <id>` | stop or start a recipe; only when the request says so |

Add `-p acme-prod` to address Prod. Read the rest with `wk <command> --help`.

`wk recipes pull` reads the single-recipe endpoint, which does not return the recipe's
`private` and `concurrency` settings. The file holds Workato's defaults there (`false` and `1`),
whatever the recipe has (`wk recipes pull --help`).

## Never run these

Rule **No package commands** in [AGENTS.md](../../AGENTS.md): never run `wk pull`, `wk diff`,
`wk clone` or `wk push`.

- `wk pull`, `wk diff` and `wk clone` export a package. In `wk` 1.1.0 each run creates an
  export manifest in the workspace (`POST /export_manifests`) and never deletes it. Workato's API
  can delete a manifest by id but cannot list them, so a forgotten one cannot be found later.
- `wk push` imports a whole package into the workspace. Recipes are changed one at a time, by
  the push procedure of the `workato-recipe-edit` skill.

To read recipes, use the plain GETs:

```bash
scripts/sync_recipes.py dev
```

```bash
wk recipes pull <id> -o tmp/recipe.json
```

Rule **Secrets**: never run `wk auth token` or `wk mcp auth-header` in a shell, in any form. Both
print the API token, and a pipe, a substitution or a redirect puts it into a transcript. Never
run `wk --verbose` either: a debug log may show the request headers. For an API call that `wk`
does not cover, use the helper. It reads the token inside its own process:

```bash
scripts/wk_api.py dev GET /deployments -q project_id=<dev project id>
```

Anything but a GET needs `--write`.

Where a harness runs `scripts/guard_wk.py` as a hook (Claude Code and Codex), it blocks:

- the package commands `wk pull`, `wk diff`, `wk clone` and `wk push`, in any flag order and with
  any profile;
- `wk auth token` and `wk mcp auth-header`, also in pipes, substitutions and redirects;
- a command that names `profiles.env` (see "Where the token is kept");
- `wk ... -o <file>` with a file outside `tmp/`;
- `wk --verbose`;
- `xargs wk` with fewer than two subcommand words, where the rest would come from standard input.

The guard guards against mistakes; it is not a security boundary. It does not interpret `eval`,
text piped into a shell, a command held in a variable, aliases, scripts, or a program handed to
another interpreter (`python3 -c`, `perl -e`). The Claude Code settings also deny the package
commands, `wk auth token` and `wk mcp auth-header`. A deny rule matches the command text from its
start, so `wk -p acme-dev pull` passes it and only the guard stops it. Elsewhere the rules are the
only guard. Why each rule exists: [rationale.md](../conventions/rationale.md).

## The Workato MCP server

The agents build and change recipes through Workato's MCP server for builders (AIRO).

- Address: `{app_url}/airo_mcp`, for example `https://app.workato.com/airo_mcp` (the table under
  "Data centers"). It is in `.agents/mcp.json` as `workato-airo-mcp-server`, and
  `scripts/sync_harness.py` writes it into the config of every harness with your `app_url`.
- Sign-in: OAuth, with your own Workato user. The server then acts as you, with your permissions.
- **It acts in the workspace and environment that are active in your browser when you
  authorize it.** Switch Workato to **Dev** in the browser first, then authorize. If you ever see
  Prod projects through it, remove the authorization and do it again from Dev. The
  `environment-preflight` skill checks this.
- Do not use token sign-in for this server. A token connection acts as the workspace owner,
  whatever role and project list the API client has; a read-only client does not make it
  read-only.
- Not available in the China data center. OAuth is not available on a Developer Sandbox.
- Your user needs access to the server. Not verified: which setting of a user's role grants it.
  If the sign-in is refused, ask a workspace admin.
- Not verified: Workato's audit log marks what was done through the server as "(via AIRO)".

How to sign in from each harness: [harnesses.md](harnesses.md). Workato's page:
<https://docs.workato.com/en/airo/mcp.html>.

`wk mcp connect airo --client <harness>` installs the server into some harnesses' own
configuration, or prints the entry (`wk mcp connect --help`). You do not need it:
`scripts/sync_harness.py` writes those files, and you only sign in.

## Deployments

A deployment moves one project from Dev to Prod, and only when a person asks for it. Workato
deploys only from the Development environment, so the deployment calls use the Dev profile. What
travels, what does not, and the steps before and after are the `workato-prod-deploy` skill.
Workato's page: <https://docs.workato.com/features/environments/deployment.html>.

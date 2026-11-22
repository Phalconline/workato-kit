# Start a new workspace repository

This page takes you from the public kit to a private repository that holds a copy of your Prod
recipes, in order. A colleague who joins an existing repository reads
[docs/setup/README.md](README.md) instead.

## Who this is for

The kit serves **one Workato account with the Environments feature**, and of its environments it
uses exactly two: **Dev**, where every recipe is changed, and **Prod**, which changes only by
deployment from Dev. One repository serves one workspace.

You need:

- a Workato account whose plan includes the Environments feature, with a Dev and a Prod
  environment;
- an admin of the workspace who can create one API client in Dev and one in Prod;
- a Workato user with access to the Workato MCP server (for the agents' recipe edits);
- macOS or Linux, git, make and Python 3.14;
- a place for a **private** git repository. The examples use GitHub.

Not supported:

| Setup | Why |
|---|---|
| An account with a single environment, such as a Free, Pro or Developer Sandbox (trial) account | There is no Prod to deploy to and nothing to compare. `scripts/init_workspace.py` refuses two profiles that reach the same environment. |
| Dev and Prod as two separate accounts | A deployment moves a project between environments of one account. The scripts also refuse two profiles of different data centers. |
| A Test environment | Workato creates one with the Environments feature. The kit ignores it: the registry knows `dev` and `prod` only. |
| Recipes in Workato's default project, Home | Workato lists Home without a folder of its own, so the kit cannot walk it. Its recipes stay outside the registry, the Prod copy and the lint. Keep the recipes the repository should know in projects of their own. |
| Windows without WSL | The hooks, `make` and the script headers need a POSIX shell. Not verified: WSL. |

What was run: the scripts and the setup path on this page, on macOS, against a real Dev and Prod
environment of one account in the US data center; the rules, skills and the guard hook with
Claude Code. Not run: Linux, another data center, the file store of `wk`, another harness, and
`make dev` on a second machine.

## Create your private repository

Your repository will hold the JSON of your Prod recipes, connection names and process docs. It
must be **private**. Two ways that look shorter do not work:

- A GitHub fork of a public repository is public, and its visibility cannot be changed.
- A repository made with GitHub's "Use this template" button starts with a single new commit
  and shares no history with the kit. A later `git merge kit/main` then refuses to merge
  unrelated histories, so kit updates cannot arrive.

So clone the kit and push the clone to a new, empty private repository. First create that
repository on your git host: private, and empty, with no README, license or `.gitignore`, so
that the first push has nothing to collide with.

Then clone the kit. git must be installed for this
([README.md](README.md#install-the-tools) has the commands). `acme-workato` is the folder of your
repository:

```bash
git clone https://github.com/Phalconline/workato-kit.git acme-workato
```

```bash
cd acme-workato
```

Keep the kit as a second remote named `kit`, and make sure nothing is ever pushed to it:

```bash
git remote rename origin kit
```

```bash
git remote set-url --push kit no-push
```

Add your private repository as `origin` and push:

```bash
git remote add origin <your private repository URL>
```

```bash
git push -u origin main
```

Your repository now shares its history with the kit, so updates arrive by an ordinary merge
([updating.md](updating.md)).

## Install the tools

Install git, make, Python 3.14, `wk` and `recipe-lint`, and register the lint plugin, as in
[Install the tools](README.md#install-the-tools). Then run `make dev` and `make check`, as in
[Install the development tools and run the offline
checks](README.md#install-the-development-tools-and-run-the-offline-checks).
You have already cloned the repository, so skip that step there. Without a workspace the offline
checks pass, and `scripts/check_data.py` prints `No workspace yet: scripts/init_workspace.py
creates one.`

## Create the two API clients

A workspace admin creates one API client in Dev and one in Prod: an API client is created for
one environment. For each:

- give it every project the repository should know, including the project that holds the shared
  connections. A project the client cannot see is missing from the registry;
- copy the token when it is shown. Workato shows it once.

Their roles differ ([workato.md](workato.md#api-clients-and-privileges) lists both):

- **Dev client:** the reads and the writes of the Dev row: start and stop recipes, update a
  recipe, tags, and the deployment call, which Workato accepts only in the Dev environment.
- **Prod client:** the reads of the Prod row only. Prod changes only by deployment, and a
  deployment is called in Dev. A read-only Prod client cannot start or stop a Prod recipe or
  change a Prod project property: when a request asks for that, a person does it in the Workato
  UI.

## Sign `wk` in twice

Pick the two profile names now: they go into the registry and into the shared permissions of
Claude Code. A name starts with a letter or a digit and may hold letters, digits, `.`, `_` and
`-`. The examples use `acme-dev` and
`acme-prod`. Replace `us` with your region ([workato.md](workato.md#data-centers)); paste the
token when asked:

```bash
wk auth login --name acme-dev --environment dev --region us
```

```bash
wk auth login --name acme-prod --environment prod --region us
```

```bash
wk auth switch acme-dev
```

On a machine without a keychain, read [workato.md](workato.md#where-the-token-is-kept) first.

## Create the workspace folder

Pick a short name for the workspace folder: lower-case words and digits joined by dashes, such
as `acme`. Then run, in the repository root:

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod \
  --maintainer "Integration lead" --company-domain acme.example
```

| Argument | What it does |
|---|---|
| `acme` | the name of the folder `workato/workspaces/acme/` |
| `--dev-profile NAME`, `--prod-profile NAME` | the two `wk` profiles; required |
| `--maintainer TEXT` | who decides about this workspace, a role or a team; written to `maintainer`, replacing what is there |
| `--company-domain DOMAIN` | an e-mail domain of your company, for the lint's check of hardcoded addresses; added to `company_domains`; repeatable |
| `--pair DEV_ID=PROD_ID` | pairs a Dev project with a Prod project when their names do not pair them; `DEV_ID:PROD_ID` works too; repeatable |
| `--slug PROJECT_ID=SLUG` | names the slug of a new Dev project when the derived one is taken, reserved or empty; repeatable |

What it does:

- It reads `wk auth list` and the project list of both environments (`wk folders list
  --projects`). It reads no token and changes nothing in Workato.
- It pairs a Dev and a Prod project by exact name, when that name occurs once in Dev and once in
  Prod, or by `--pair`. It never guesses. A Prod project that a `--pair` names is never taken by
  a name match.
- A paired project is registered with `"snapshots": true`: it is a managed project, and its Prod
  recipes are copied into the repository. A project only in Dev is registered with
  `"snapshots": false`. A project only in Prod is listed and not registered. Workato's default
  project, Home, is listed and not registered.
- The slug of a project is derived from its Workato name: lower-case Latin words and digits
  joined by dashes. It may not be `setup`, `conventions`, `knowledge` or `kit` (folders of
  `docs/`). When two new projects would get one slug, both are left out until you name them with
  `--slug`.
- It writes `workato/workspaces/acme/registry.json` and copies the three files of
  `workato/workspace-template/` into the folder: `README.md`, `harness.json` and
  `notes/README.md`. It never overwrites a file it copied before.
- It runs `scripts/sync_harness.py`, which writes the profile names into the harness files and
  prints the permission rules it adds.
- It prints what it registered and what is left to decide, then the next steps.

A run on an account whose Dev holds Common, Sales Orders and Sandbox, and whose Prod holds Common
and Sales Orders, prints (the permission list is shortened here):

```text
Workspace folder: workato/workspaces/acme/ (3 file(s) added)
  registered: common
  registered: sales-orders
  registered: sandbox
3 projects in the registry, 2 with a Prod copy.

Not registered: Home. Workato lists its default project without a folder of its own, so recipes kept there stay outside the registry.

In Dev only. After the first deployment of one, run this command again: it adds the Prod ids.
  Sandbox (Dev project 1005)

Harness files (scripts/sync_harness.py):
1 file(s) written.
   .claude/settings.json
Permission rules of .claude/settings.json:
  allow + Bash(wk -p acme-dev recipes get *)
  allow + Bash(wk -p acme-dev recipes list *)
  ...

Next: finish the registry by hand, then scripts/doctor.py and scripts/sync_recipes.py prod.
The steps are in docs/setup/new-workspace.md.
```

Exit status:

- 0: done. Projects that are only in Dev or only in Prod are information, not a failure.
- 1: done, but a project needs `--slug`, or a `--pair` or `--slug` named no project. The other
  projects were registered.
- 2: refused, nothing written ([Troubleshooting](#troubleshooting)). The one exception is a
  failure of `scripts/sync_harness.py`: the registry is then written.

Run it again whenever you like. A re-run needs only the workspace name and the two profiles:

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
```

On a re-run it:

- finds a registered project by its Dev project id and adds the projects that are new in Dev;
- adds the Prod half of a project that has been deployed since, and sets its `snapshots` to
  true;
- updates `name` after a rename in Workato and keeps the slug;
- changes `maintainer` and `company_domains` only when you pass `--maintainer` or
  `--company-domain`;
- changes no other key and never removes an entry. A registered project that Workato no longer
  lists for the Dev profile is reported, and [maintaining.md](maintaining.md) says what to do;
- writes `registry.json` with its own formatting, so hand formatting is lost (the content you
  added stays);
- copies a template file only when the folder lacks it.

## Finish the registry by hand

Open `workato/workspaces/acme/registry.json`. Check `maintainer`, `company_domains` and the
workspace names under `environments`, and mark the project that holds the shared connections
with `"shared_connections": true`. Every key is explained in
[registry.md](../conventions/registry.md). Then check the file:

```bash
scripts/check_data.py
```

Until the first Prod copy exists it prints a note such as `note: no Prod copy yet of common,
sales-orders: run scripts/sync_recipes.py prod`. That note is expected here; it is not a failure.

## Check access and take the first copy

```bash
scripts/doctor.py
```

It runs the offline checks first, the same as `make check`; they pass with the note above. Then
it prints the section `Workato CLI access (read-only)`. Every line under that heading must say
`ok` or `note`. It checks the reading of project properties only in an environment where the
registry has a project. Then copy the Prod recipes into the repository:

```bash
scripts/sync_recipes.py prod
```

The Prod copy lands in `workato/workspaces/acme/projects/<slug>/`. If no project exists in Prod
yet, it prints `No managed project has prod ids in the registry: nothing to sync. Name a project
to sync a Dev-only one.` Run `scripts/init_workspace.py` again after the first deployment.

Copy the Dev recipes into your personal cache, which the lint and the index read:

```bash
scripts/sync_recipes.py dev
```

Without a project argument it copies the managed projects only. Name a project that is only in
Dev to copy it too:

```bash
scripts/sync_recipes.py dev sandbox
```

The Dev copy lands in `tmp/wk/dev/` and is git-ignored.

## First commit

Run the offline checks, then commit the workspace folder and the harness files that
`scripts/sync_harness.py` rewrote:

```bash
make check
```

```bash
git add workato/workspaces/acme .claude .codex .cursor .gemini .mcp.json \
  .agents/mcp_config.json .agents/generated-files.json
```

`git add` respects `.gitignore`, so `.claude/settings.local.json` and `profiles.env` stay out.
Check with `git status` before you commit.

```bash
git commit -m "Add the acme workspace"
```

```bash
git push
```

## Connect the harness

Start your harness in the repository root, approve the MCP servers, switch Workato to Dev in the
browser and sign in to the Workato MCP server ([harnesses.md](harnesses.md)). Then do the checks
of [First session](README.md#first-session).

## What next

- **Document a recipe.** Ask your agent to document one recipe, for example
  `[SO] REC | New order`. It loads the `recipe-docs` skill and writes the doc as
  `docs/<project-slug>/recipes/<dev_recipe_id>-<kebab-name>.md`. Then rebuild the recipe index
  from the docs and the Dev copy:

  ```bash
  scripts/build_index.py
  ```

- **Write the first rule of the workspace.** Add it to the last section of
  [AGENTS.md](../../AGENTS.md), "Rules of this workspace": a name in bold, then what to do. Its
  reason goes to [decisions.md](../conventions/decisions.md).
- **Life after setup.** A new project, the first deployment of a project, a rename, a new
  maintainer: [maintaining.md](maintaining.md). Updates of the kit: [updating.md](updating.md).

## Where the workspace's own things go

Nothing a workspace needs to say requires editing a file the kit owns. Kit files change with every
update of the kit; your own files do not conflict with it.

| What | Where |
|---|---|
| projects, ids, profiles, lint settings | `workato/workspaces/acme/registry.json` |
| optional MCP servers, extra Claude Code permissions, model choices | `workato/workspaces/acme/harness.json`, then `scripts/sync_harness.py` |
| what the workspace adds to a skill: names of its shared connections, its release order, where its pages live | `workato/workspaces/acme/notes/<skill-name>.md` ([skills.md](skills.md)) |
| rules of this workspace | the last section of [AGENTS.md](../../AGENTS.md), "Rules of this workspace" |
| decisions, with their reasons | [docs/conventions/decisions.md](../conventions/decisions.md) |
| notes about the platform as this workspace meets it | `docs/knowledge/workspace/` |
| docs of a project and its recipes | `docs/<project-slug>/` ([docs/README.md](../README.md)) |
| scripts of the workspace | `scripts/ws_<name>.py` and `scripts/lib/ws_<name>.py`, with tests in `tests/test_ws_<name>.py` (a test file of that name may also exist without a script) |
| skills of the workspace | `.agents/skills/ws-<name>/SKILL.md`, listed by name, in backticks, in the last section of `AGENTS.md`, then `scripts/sync_harness.py` ([skills.md](skills.md#a-skill-of-the-workspaces-own)) |
| CI workflows of the workspace | `.github/workflows/ws-<name>.yml` |

There is no subagent role of the workspace's own: `.agents/agents.json` is one file, and the kit
owns it.

`scripts/check_kit_files.py`, part of `make check`, fails when an id, an address, a host, a
bracket code, a ticket key, a date before 2030 or a name the registry holds lands in a file the
kit owns. It cannot know every name, a recipe's or a connection's for example.

## Troubleshooting

`scripts/init_workspace.py` prints an error as `error: <message>` and exits with status 2; it
has then written nothing, except where the table says so. The examples use the names of this
page.

| Message | What to do |
|---|---|
| `error: the following arguments are required: --dev-profile, --prod-profile` | Pass both profiles, on every run. |
| `error: the workspace name must be lower-case words joined by dashes, for example acme-corp; got 'Acme'` | Choose a folder name of lower-case letters, digits and dashes. |
| `error: workato/workspaces/<other>/ exists; one repository serves one workspace` | This repository already has a workspace. Use its name, or start another repository for another account. |
| `error: WK_WORKSPACE names another workspace than 'acme'; unset it first` | Unset `WK_WORKSPACE` in your shell, or set it to the name you pass. |
| `error: --pair needs PROJECT_ID=VALUE, got '1001'` (or `--slug`) | Write the option as `--pair 1001=1002` or `--slug 1005=sandbox`. |
| `error: --pair needs DEV_ID=PROD_ID with two project ids, got 1001=...` | The value after `=` must be a Prod project id. |
| `error: --pair names one Prod project for two Dev projects` | Each Prod project pairs with one Dev project. Check the ids. |
| `error: --slug: 'Sandbox' is not a slug; use lower-case words and digits joined by dashes` | Write the slug as lower-case Latin words and digits joined by dashes, such as `sandbox`. |
| `error: --slug: 'setup' is reserved, it is a folder of docs/` | `setup`, `conventions`, `knowledge` and `kit` are folders of `docs/`. Choose another slug. |
| `error: --company-domain needs a domain such as acme.example, got 'acme'` | Pass a domain with at least one dot. |
| `error: wk is not installed or not on PATH; see docs/setup/workato.md` | Install `wk` and open a new terminal. |
| `error: wk has no profile 'acme-prod'. Sign in first: wk auth login --name acme-prod --environment prod --region <your region>` | Run the command it prints, with your region. South Korea and the UK have no `--region` value: use `--base-url` ([workato.md](workato.md#data-centers)). |
| `error: the profile name 'acme dev' holds more than letters, digits, . _ -; sign in again under a plain name` | Sign in again with `wk auth login --name` and a name of letters, digits, `.`, `_` and `-`. |
| `error: wk profile 'acme-dev' has no https base URL on a Workato host; sign in again (the scripts send a token to Workato only)` | Sign in again with `--region`, or with an https `--base-url` on a Workato host. |
| `error: acme-dev and acme-prod are in different data centers; Dev and Prod must be two environments of one Workato account` | Both profiles must use the same `--region` or `--base-url`. If they do, Dev and Prod are two accounts, which the kit does not support. |
| `error: acme-dev and acme-dev reach the same environment. The kit needs a Dev and a Prod environment of one account; an account with a single environment is not supported` | The same profile was given twice, or both profiles hold tokens of one environment. Sign the Prod profile in with the token of the Prod API client. Without a Prod environment the kit cannot be used. |
| `error: wk holds the profile 'acme-prod' as signed in to prod, but it was given as the dev profile; swap --dev-profile and --prod-profile` | Run the command again with the two profiles the other way round. |
| `error: wk auth list gives no workspace id for these profiles, so Dev and Prod cannot be told apart; update wk and sign in again (docs/setup/workato.md)` | Update `wk` ([workato.md](workato.md#install)), then sign both profiles in again. |
| `error: wk auth list did not answer with JSON` | Run `wk auth list -j` yourself and read what it says; update `wk` if needed. |
| `error: wk -p acme-prod folders list --projects failed: ...` | The API client may not list projects, or the token is wrong. Check its privileges ([workato.md](workato.md#api-clients-and-privileges)) and run `scripts/doctor.py`. |
| `error: wk -p acme-prod folders list --projects did not answer with name, project_id and id for each project; is wk up to date?` (or `... did not answer with JSON`) | Update `wk` and run the command again. |
| `error: the registry names the dev profile 'old-name', not 'acme-dev'; edit the registry if the profile was renamed` | Pass the profile names the registry holds, or change `environments` in the registry when you renamed a profile on purpose ([maintaining.md](maintaining.md)). |
| `error: workato/workspaces/acme/registry.json is not valid JSON: repair it first (scripts/check_data.py)` | Repair the file by hand; `scripts/check_data.py` says when it parses. |
| `error: --pair: Prod has no unpaired project with the id 1002` | The Prod id is wrong, or that project is already paired. Check the ids it listed. |
| `error: scripts/sync_harness.py failed; see its message above` | The registry is written. Fix what `sync_harness.py` reported, then run `scripts/sync_harness.py`. |

These lines come with exit status 0 or 1; the registry is written:

| Message | What to do |
|---|---|
| `Not registered; name each with --slug PROJECT_ID=SLUG and run again:` then `Sandbox (Dev project 1005): the slug 'sandbox' is taken by another project` | Two new projects give the same slug (both are left out), or a registered project holds it. Run again with `--slug 1005=<new-slug>`. Exit status 1. |
| the same, ending `is reserved, it is a folder of docs/` | The name gives `setup`, `conventions`, `knowledge` or `kit`. Name another slug with `--slug`. Exit status 1. |
| the same, ending `is not lower-case Latin words and digits joined by dashes` | The name has no Latin letter or digit, or holds letters of another alphabet. Name a slug with `--slug`. Exit status 1. |
| `Named no project; check the id and run again:` then `--pair 1002=...: no Dev project 1002 that still lacks its Prod half` | The Dev id is wrong (here a Prod id), or the project is paired already. Exit status 1. |
| `Named no project; ...` then `--slug 1001=...: no new Dev project 1001 (a registered project keeps its slug)` | A registered project keeps its slug; to change it, see [maintaining.md](maintaining.md). Exit status 1. |
| `In Dev only. After the first deployment of one, run this command again: it adds the Prod ids.` | Nothing to do now. Run the command again after the first deployment of such a project. |
| `In Prod only, not registered:` | A project exists in Prod and not in Dev. The kit does not register it: Prod changes only by deployment from Dev. |
| `If a Dev-only and a Prod-only project are one project under two names, pair them with --pair DEV_ID=PROD_ID. If none is, there is nothing to do.` | Pair them only if they are the same project. A wrong pair makes the Prod copy hold another project's recipes. |
| `Not registered: Home. Workato lists its default project without a folder of its own, so recipes kept there stay outside the registry.` | Nothing to do. Recipes the repository should know belong in a project of their own. |
| `Registered, but Workato does not list it for the Dev profile any more (deleted, or the API client lost access). Nothing was removed; see docs/setup/maintaining.md:` | See [A project deleted in Workato](maintaining.md#a-project-deleted-in-workato). |

After you edit the registry by hand, `scripts/check_data.py` (part of `make check`) prints
`Invalid registry: workato/workspaces/acme/registry.json: <what is wrong>` and names the field,
never its value. The common ones:

| What is wrong | What to do |
|---|---|
| `dev: workspace must be non-empty text` | `wk` gave no workspace name for that profile. Write the name that `wk -p acme-dev auth status` shows into `environments.dev.workspace`, and the same for Prod. |
| `dev: profile may hold letters, digits, . _ - only` | Use a profile name of those characters, and sign `wk` in under it. |
| `app_url must be the https address of a Workato web app, alone` | Write the plain https address of your data center's web app, such as `https://app.workato.com`, with no path ([workato.md](workato.md#data-centers)). |
| `company_domains must be a list of lower-case domains` | Write each domain in lower case, such as `acme.example`. |
| `sales-orders: unknown key ...` (or `registry: unknown key ...`) | A typo or a renamed key. Every key is in [registry.md](../conventions/registry.md). |
| `sales-orders: needs dev ids, and prod ids when snapshots is true` | Leave `snapshots` false until the project has Prod ids; `scripts/init_workspace.py` adds them. |
| `sales-orders: lint_checks knows ACCOUNT_PROPERTY, NO_GUARD_PROPERTY only` | Remove the unknown check name. |
| `sales-orders: NO_GUARD_PROPERTY needs lint_guard_property and lint_guard_parameter` | Set both keys, or remove the check. |
| `sales-orders: lint_guard_parameter must be a regular expression` | Repair the expression, for example `(^\|_)account_id$`. |
| `lint_literal_patterns must map a label to a regular expression` | Each value must be a regular expression that compiles. |
| `sales-orders: tables must map a table id to its name` | Write `"tables": {"5001": "Open orders"}`: the id as text, the name as the value. |
| `Invalid JSON: workato/workspaces/acme/registry.json (JSONDecodeError)` | The file does not parse. A duplicate key reads `(ValueError)`. |

`scripts/doctor.py` reports the rest: its messages are in
[If something fails](README.md#if-something-fails).

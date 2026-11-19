# Setup: join a workspace repository

This page is for a person who joins a repository that already serves a Workato workspace: its
folder `workato/workspaces/<workspace>/` holds a `registry.json`. If you are the one who starts a
repository from the kit, follow [new-workspace.md](new-workspace.md) instead and come back here
for your colleagues.

Supported systems: macOS and Linux. Windows only through WSL (not verified). What was run: the
scripts and the setup path on macOS, against a real Dev and Prod environment of one account in
the US data center; the rules, skills and the guard hook with Claude Code. Not run: Linux,
another data center, the file store of `wk`, another harness, and `make dev` on a second
machine.

## What to ask for first

Ask the maintainer (named under `maintainer` in `workato/workspaces/<workspace>/registry.json`)
for:

- access to this repository;
- a Workato user in the workspace, with access to the Dev environment and to the Workato MCP
  server;
- one API client token for Dev and one for Prod. One API client serves one environment, so there
  are two. What each client may read is in [workato.md](workato.md#api-clients-and-privileges).
- Jira and Confluence access, only if the workspace uses them ([atlassian.md](atlassian.md)).

## Install the tools

You need git, make, Python 3.14 (any patch release), the `wk` CLI and its `recipe-lint` plugin.
The scripts use the standard library only and need nothing from pip; `make dev` (below) installs
the two development tools into `.venv/`.

On macOS, git and make come with Apple's Command Line Tools:

```bash
xcode-select --install
```

On Debian or Ubuntu, install git and make, and the `venv` module of Python 3.14, which
`make dev` needs. Not verified for 3.14: these distributions ship that module as a package of its
own, named as below:

```bash
sudo apt install python3.14-venv git make
```

`wk` and `recipe-lint` come from Workato's Homebrew tap, on macOS and on Linux. Without Homebrew,
take them from their release pages ([workato.md](workato.md#install)):

```bash
brew install workato-devs/tap/wk workato-devs/tap/recipe-lint
```

Python 3.14 comes from Homebrew (its formula for the 3.14 series; `brew search python` lists
it), from your Linux distribution or from pyenv. The scripts and hooks call it as `python3.14`,
so that command must be on your PATH. With pyenv, the repository's `.python-version` says
`3.14`, so pyenv picks the newest 3.14 release you have installed:

```bash
pyenv install 3.14
```

Then register the lint plugin with `wk`. This finds `recipe-lint` on your PATH:

```bash
wk plugins install recipe-lint
```

## Install the development tools and run the offline checks

Clone the repository, then, in its root folder, install the pinned Ruff and mypy into `.venv/`.
This is done once per clone and installs nothing outside the repository:

```bash
make dev
```

Run the offline checks. They need no Workato account and no network:

```bash
make check
```

It ends with `All offline checks passed`.

## Sign `wk` in for Dev and for Prod

The registry names the two `wk` profiles under `environments`: `dev.profile` and `prod.profile`.
Use exactly these names. The shared permissions of Claude Code are written for them, and the
scripts look them up there. In the examples below they are `acme-dev` and `acme-prod`.

`wk auth login` asks for the token; paste it yourself. Replace `us` with the region of your data
center ([workato.md](workato.md#data-centers)):

```bash
wk auth login --name acme-dev --environment dev --region us
```

```bash
wk auth login --name acme-prod --environment prod --region us
```

Make the Dev profile the default, because an agent runs `wk` without `-p` for Dev:

```bash
wk auth switch acme-dev
```

The token goes to your OS keychain. On a machine without one, read
[workato.md](workato.md#where-the-token-is-kept) before you sign in.

If you must use other profile names, set `WK_PROFILE_DEV` and `WK_PROFILE_PROD` in your shell.
The scripts then use your names, but Claude Code asks before every `wk -p <your profile>` read,
because its allow list names the registry's profiles.

## Check your access

```bash
scripts/doctor.py
```

It runs the offline checks first, the same as `make check`. Then, under the heading
`Workato CLI access (read-only)`, it checks that `wk` and the lint plugin are there, that each
profile reaches the workspace the registry names and is signed in to the right environment, that
both are in one data center, and that each API client may read recipes, folders and connections,
and the project properties of an environment where the registry has a project. Every line under
that heading must say `ok` or `note`. A `FAIL` line names the fix; the table below has the
common ones.

`doctor.py` does not check the MCP sign-ins or the guard hook of your harness. Do that in your
first session (below).

## Connect your harness

1. Start your harness in the repository root. Claude Code loads its shared permissions and the
   guard hook only from the folder where the session starts ([harnesses.md](harnesses.md)).
2. Approve the project's MCP servers when asked.
3. In the browser, switch Workato to the **Dev** environment. Then sign in to the Workato MCP
   server from your harness. The server acts in the environment that was active in the browser
   when you authorized it ([workato.md](workato.md#the-workato-mcp-server)).
4. If the workspace uses Jira and Confluence, sign in to the Atlassian server too
   ([atlassian.md](atlassian.md)).
5. Read [AGENTS.md](../../AGENTS.md). It is short, and your agent follows it. The last section
   holds the rules of this workspace.

## First session

- Ask your agent which rules file it loaded.
- Ask it to list the Workato projects through the MCP server. The project ids must be the Dev ids
  in the registry. If you see the Prod ids, remove the authorization and authorize again from Dev.
- In Claude Code, run `/hooks` and check that the Bash guard is listed. Not verified: the same
  command in Codex.

## If something fails

| Message or symptom | What to do |
|---|---|
| `python3.14: command not found`, or every agent shell command is blocked with `wk guard: python3.14 is not on PATH` | Install Python 3.14, then restart the terminal and the harness so that they see the new PATH. |
| `error: the tooling runs on Python 3.14; this is ...` | `make` or the script ran under another Python. Put Python 3.14 on the PATH as `python3.14`. |
| ``error: ruff and mypy not found in .venv: run `make dev` first`` | Run `make dev`, then `make check` again. |
| `make check` names `Generated harness files` as failed | Run `scripts/sync_harness.py`, then `make check` again. |
| `make check` fails in `Format (ruff format)` or `Lint (ruff check)` after you edited a script | Run `make format`, read what is left, then `make check` again. |
| `make check` prints `note: no Prod copy yet of sales-orders: run scripts/sync_recipes.py prod` | Not a failure. The registry names a managed project whose Prod copy is not in the repository yet; run the command it names. |
| `make check` prints `Invalid registry: workato/workspaces/acme/registry.json: ...` | The registry was edited by hand and a field is wrong; the message names it. The common ones are in [new-workspace.md](new-workspace.md#troubleshooting). |
| `The offline checks failed: see their output above.` (from `scripts/doctor.py`) | One of the offline checks failed; the Workato lines above it still ran. Read the `FAILED:` line of the offline checks and fix that first. |
| `FAIL  wk is not installed; see docs/setup/workato.md` | Install `wk` and open a new terminal. |
| `FAIL  recipe-lint is not registered with wk; run: wk plugins install recipe-lint` | Install `recipe-lint` so that it is on your PATH, then run the command it names. |
| ``FAIL  dev profile (acme-dev): wk has no profile 'acme-dev'; see `wk auth list` and docs/setup/workato.md`` | Sign in with that exact profile name. |
| `FAIL  prod profile (acme-prod) cannot reach Workato; sign in again: docs/setup/workato.md` | The token was revoked or mistyped. Ask for a new one and run `wk auth login` again for that profile. |
| `FAIL  dev profile (acme-dev) is signed in to prod according to wk: the two profiles of the registry look swapped` | The profile named `acme-dev` holds the Prod token. Sign both profiles in again, each with the token of its own environment. Do not make it the default profile. |
| `FAIL  dev profile (acme-dev) reaches the workspace 'Acme'; the registry says 'Acme (Dev)'` | The token belongs to another workspace or environment. Ask for the right token. |
| `FAIL  prod: reads recipes: wk -p acme-prod recipes list --per-page failed: ...` (also `reads projects and folders: wk -p acme-prod folders list --projects failed: ...`, `reads connections: wk -p acme-prod connections list --per-page failed: ...`) | A read through `wk` failed; the end of the line is what `wk` said. Usually the API client may not read that: ask a workspace admin to add the privilege ([workato.md](workato.md#api-clients-and-privileges)). |
| `FAIL  prod: reads project properties: Workato answered HTTP 403 to GET /properties` | A read through the API: the API client may not read project properties, which `scripts/sync_recipes.py` needs. Ask a workspace admin to add the privilege. |
| ``FAIL  prod: reads project properties: wk -p acme-prod auth token failed; check `wk auth status` (output withheld)`` | The script could not take the token from `wk`. Run `wk -p acme-prod auth status` and sign in again if it fails. |
| `FAIL  prod: reads project properties: wk profile 'acme-prod' has no https base URL on a Workato host; sign in again (the scripts send a token to Workato only)` | Sign in again with `--region`, or with an https `--base-url` on a Workato host ([workato.md](workato.md#data-centers)). |
| `FAIL  acme-dev and acme-prod are in different data centers` | Both profiles must use the same region or base URL. Sign in again with the right one. |
| `note  wk's default profile is the Prod one; make Dev the default: acme-dev` | Run `wk auth switch acme-dev`. |
| `note  dev profile (acme-dev) keeps its token as plain text in profiles.env; keep that file private` | Expected on a machine without a keychain. Read the risks in [workato.md](workato.md#where-the-token-is-kept). |
| The agent sees Prod projects through the MCP server | Remove the authorization in your harness, switch the browser to Dev, authorize again. |

## Pages

| Page | What it covers |
|---|---|
| [new-workspace.md](new-workspace.md) | start a new repository from the kit, up to the first sync |
| [maintaining.md](maintaining.md) | after setup: a new project, a first deployment, renames, a deleted project, a new maintainer, a person leaving, stopping use of the kit |
| [updating.md](updating.md) | take updates of the kit; who owns which file; send a fix back |
| [workato.md](workato.md) | the `wk` CLI, data centers, API clients and privileges, token storage, the MCP server, what is never run |
| [harnesses.md](harnesses.md) | Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, Antigravity: what each reads, hooks, approvals |
| [skills.md](skills.md) | skills, the notes of a workspace, the two vendor skills, subagent roles and models |
| [tools.md](tools.md) | the tools the repository uses and how a workspace adds one |
| [atlassian.md](atlassian.md) | the optional Jira and Confluence integration |

## Secrets

- You type your own tokens into `wk auth login` and into the sign-in pages. An agent never types,
  reads or prints a secret (rule **Secrets** in [AGENTS.md](../../AGENTS.md)).
- Nothing in this repository holds a credential. `profiles.env`, `.wk/` and `.env*` are
  git-ignored.
- If a token ends up in a chat, a file or a commit, tell the maintainer and have the API client's
  token regenerated. Regenerating invalidates the old token.

# Workato kit

An unofficial starter kit to keep one Workato workspace documented, checked and safely changed
with AI coding agents. It gives the agents rules and procedures, keeps a copy in git of the
recipes of every project deployed to Prod, and checks the repository offline. It is for a team
that runs one Workato account with the Environments feature (Dev and Prod) and wants AI agents to
change its recipes under written rules. It is an independent project, not made or endorsed by
Workato.

To start a repository for your workspace, follow
[docs/setup/new-workspace.md](docs/setup/new-workspace.md). In a repository built from the kit,
start at [docs/setup/README.md](docs/setup/README.md): it sets up your machine and your access.
The rest of this page is about the kit itself.

## Why

A Workato recipe lives in Workato. Its versions stay there, outside git and outside code review,
and nothing tells an AI agent what it may change, in which environment, or what to check first.
The kit writes rules for that around one workspace, and for Claude Code it backs some of them with
permissions and a guard hook:

- an agent changes recipes in Dev only, and Prod changes only by deployment;
- every recipe of a project deployed to Prod has a copy in git, so a change shows up as a diff;
- a recipe doc says only what was read from the recipe, and marks anything else as unverified;
- what an agent may run without asking is written down, and so is what it must never run.

## What you get

| Part | What it does |
|---|---|
| Rules for agents | [AGENTS.md](AGENTS.md), one file every harness loads: named rules for writing to Workato, for the repository and for the docs, and a last section for the rules of your own workspace |
| Skills | procedures an agent loads when a task matches: check which environment it acts in, edit a recipe, stop and start one, deploy a project to Prod, read and refresh recipe JSON, manage connections and other assets, read job history, review the impact of a change, build a connector, document a recipe; optional skills for Jira and Confluence |
| A copy of Prod in git | `scripts/sync_recipes.py` copies the recipes of every project deployed to Prod as JSON, by plain reads; `scripts/prod_drift.py` compares the live Dev recipes with the live Prod recipes |
| Docs | one doc per recipe from a template and an index of them; setup pages, conventions and notes on how the platform behaves |
| Tooling | eighteen Python scripts on the standard library only: setup, reads from Workato, lint, generators and offline checks. None changes Workato unless its help says so |
| Guardrails | for Claude Code: an allow list of commands that only read Workato, a deny list for the package and token commands of `wk` and for the credential files, and a hook that blocks the `wk` commands the rules forbid |
| One source for six harnesses | Claude Code, Codex, Cursor, Gemini CLI, Antigravity CLI and GitHub Copilot get their rules, MCP servers and skills from one source, and Claude Code and Codex also their subagent roles (only Claude Code was tested) |
| Offline checks | `make check`: lint, format, types, unit tests, JSON and registry, generated harness files, links, secret patterns and a check that the kit's own files hold no workspace data. After a one-time `make dev` it needs no account and no network |

## How it works

1. You clone the kit and push the clone to a new, empty private repository.
2. An admin creates one API client per environment and you sign `wk` in to each. Then
   `scripts/init_workspace.py` reads the project lists of Dev and Prod and writes the registry of
   your projects and the harness files.
3. `scripts/sync_recipes.py prod` takes the first copy of your Prod recipes.
4. Agents change recipes in Dev through the Workato MCP server and `wk`, and follow the skills.
   When a person asks for it, an agent deploys the project to Prod.
5. After a deployment the Prod copy is refreshed and committed together with the docs.
6. Kit updates arrive by `git merge` from the kit, which your repository keeps as a second
   remote.

You do not work in the kit itself: your workspace lives in the private repository you create
from it.

## Is this for you

You need all of these:

| Requirement | Why |
|---|---|
| One Workato account with the Environments feature, and its Dev and Prod environments | recipes are changed in Dev and reach Prod only by deployment |
| A workspace admin who can create API clients | the scripts and `wk` reach Workato through one API client per environment |
| One API client per environment, each with a `wk` profile | an API client is created for one environment; the scripts read with it |
| A Workato user with access to the Workato MCP server | agents build and edit recipes through it; the scripts do not need it |
| The `wk` CLI, a Workato Labs tool | the CLI the procedures use for stop and start, lint, tags and recipe JSON |
| Python 3.14 (any patch release) and git | the tooling uses the standard library only |
| macOS or Linux | the hooks and the `Makefile` assume a POSIX shell, and the scripts start with `python3.14` as a command |
| A private Git repository | a workspace repository holds Prod recipe JSON and connection names |

Not supported:

- an account with a single environment (this includes the self-service and trial plans);
- Dev and Prod as two separate Workato accounts;
- a Test environment: it may exist in the account, but the kit ignores it;
- recipes in Workato's default project, Home: it has no folder of its own, so the registry
  leaves it out. Keep the recipes you want documented and copied in projects of their own;
- Windows outside WSL. Not verified: inside WSL it is expected to work.

An AI harness is optional for the tooling and needed for the agent side. The kit writes the
configuration of Claude Code, Codex, Cursor, Gemini CLI, Antigravity CLI and GitHub Copilot from
one source.
Jira and Confluence are an optional integration, off by default.

### What was tested

The scripts and the setup path were run on macOS against a real Dev and Prod account in the US
data center of Workato. The rules, the skills and the guard hook were used with Claude Code.

Not run: `make dev` on a second machine, Linux, another data center, the file store of `wk`, and
every harness other than Claude Code. They are expected to work. The Workato MCP server is not
available in the CN data center, so there only the CLI and the scripts work.

## Start here

- **A new repository for your workspace:**
  [docs/setup/new-workspace.md](docs/setup/new-workspace.md). It goes from the clone of the kit to
  the first copy of your Prod recipes.
- **Joining a repository that a colleague already set up:**
  [docs/setup/README.md](docs/setup/README.md).

Create the repository by cloning the kit and pushing the clone to a new, empty private
repository. Do not fork the kit: a fork of a public repository stays public. Do not use "Use this
template" either: the copy shares no history with the kit, so it cannot merge kit updates.

To look at the kit first, the offline checks run without an account and without a workspace:

```bash
make dev
```

```bash
make check
```

`make dev` installs Ruff and mypy into `.venv/` once. Then read [AGENTS.md](AGENTS.md): it is the
rules file every harness loads.

## What is where

| Path | What it holds |
|---|---|
| [AGENTS.md](AGENTS.md) | the rules for agents; its last section holds the rules of your workspace |
| [docs/](docs/README.md) | setup, conventions, platform notes, and later the docs of each of your Workato projects |
| [scripts/](scripts/README.md) | the tooling: offline checks, Workato reads, generators; [tests/](tests/) are its offline tests |
| [workato/workspaces/](workato/workspaces/README.md) | your workspace once it is created: registry, Prod recipe JSON, notes for the skills |
| [workato/workspace-template/](workato/workspace-template/README.md) | what `scripts/init_workspace.py` copies into a new workspace folder |
| [.agents/](.agents/) | skills, subagent roles and the sources of every harness configuration file |
| `.codex/hooks.json`, `.cursorignore`, `.geminiignore` | written by hand, owned by the kit: the guard hook of Codex and the files two harnesses must not read |
| `.claude/settings.json`, `.claude/skills/`, `.claude/agents/`, `.codex/agents/`, `.codex/config.toml`, `.cursor/mcp.json`, `.gemini/settings.json`, `.mcp.json`, `.agents/mcp_config.json`, `.agents/generated-files.json` | harness files generated by `scripts/sync_harness.py`; never edited by hand |
| [tmp/](tmp/README.md) | your personal working cache; git-ignored |

## How updates arrive

Your repository keeps the kit as a second git remote named `kit`. You fetch and merge it, then
regenerate the harness files and run the checks. The commands, and what to do with a conflict, are
in [docs/setup/updating.md](docs/setup/updating.md). Each kit change that needs a manual step in
your repository says so in [CHANGELOG.md](CHANGELOG.md).

Every file has one owner, so a merge rarely conflicts: the kit owns the tooling, the skills and
these docs; your repository owns `workato/workspaces/<workspace>/`, the docs of your projects and
the last section of `AGENTS.md`. A generated harness file holds the settings of your workspace
and can conflict; [docs/setup/updating.md](docs/setup/updating.md) says what to do.

## What the kit never does

- No automation runs from here. Recipes live in Workato and are changed there.
- No script changes Workato unless its help says so. The one that can is `scripts/wk_api.py`, and
  only with `--write`. Every other script reads Workato, or does not reach it at all.
- No script prints an API token. Tokens stay in the store of `wk`: the OS keychain by default. A
  script sends a token only to a Workato host.
- `scripts/guard_wk.py` runs as a hook in Claude Code, and is configured for Codex (not
  verified). It blocks the package commands
  of `wk` (`pull`, `diff`, `clone`, `push`), every shell use of the token, commands that name the
  token file `profiles.env`, a `wk` output file outside `tmp/`, `wk --verbose`, and `xargs wk`
  fed from standard input. It is a guard against mistakes, not a security boundary. See
  [SECURITY.md](SECURITY.md).

## Not affiliated with Workato

This is an independent project. It is not made, endorsed or supported by Workato. Workato is a
trademark of its owner. The `wk` CLI that the kit relies on is a Workato Labs tool, published
without an SLA.

## License

The kit is free to use, change and share under the [MIT License](LICENSE).

The license covers the files of the kit, except the two vendor skills below. A repository built
from the kit keeps the `LICENSE` file, because the license asks for its notice to stay with every
copy of the kit. It does not make that repository public: what you add there (your workspace
folder, the docs of your projects, your rules) stays yours and stays private.

The two vendor skills in `.agents/skills/search-company-knowledge/` and
`.agents/skills/triage-issue/` are pinned copies under the Apache License 2.0. The license text
is in [.agents/licenses/atlassian.txt](.agents/licenses/atlassian.txt).

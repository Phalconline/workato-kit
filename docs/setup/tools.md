# Tools

The repository works with a short list of tools: command-line tools on your machine, the MCP
servers listed in `.agents/mcp.json`, and the connectors your harness already provides. It hosts
no server and deploys no app of its own. Each tool on the list is there for a reason the rules
name ("Integrations" in [AGENTS.md](../../AGENTS.md)).

## The tools and why each is allowed

| Tool | What for | Why it is allowed | Who needs it | Install |
|---|---|---|---|---|
| git, make | the repository, `make dev`, `make check` | the base of any repository | everyone | [README.md](README.md#install-the-tools) |
| Python 3.14 | every script, the guard hook, `make check` | the tooling is written in it, standard library only | everyone | [README.md](README.md#install-the-tools) |
| Ruff, mypy | lint, formatting and type checks behind `make check` ([python.md](../conventions/python.md)) | pinned in `pyproject.toml`, installed into `.venv/` of the repository, nothing global | everyone | `make dev` |
| `wk` | recipe JSON, lint, start and stop, tags, sign-in for the scripts | Workato Labs publishes it, without an SLA. `wk` is the CLI the procedures use for stop and start, lint, tags and recipe JSON, and the scripts get their token through it. | everyone who touches recipes | [workato.md](workato.md#install) |
| `recipe-lint` | the plugin behind `wk lint` | published with `wk` by Workato Labs | everyone who touches recipes | [workato.md](workato.md#install) |
| Workato MCP server | building and editing recipes from a harness | Workato's own remote server; each person signs in with their own Workato user | everyone who changes recipes | [harnesses.md](harnesses.md) |
| Atlassian MCP server | Jira and Confluence | optional; Atlassian's own remote server with per-user sign-in (not verified: [atlassian.md](atlassian.md)); off until a workspace switches it on | teams that use Atlassian | [atlassian.md](atlassian.md) |

An installed tool grants no access: each person signs in with their own account. A skill names
procedures and grants no credentials and no permission to write to an external system.

Tools a person may use on their own machine, which nothing in the repository depends on:

| Tool | What for |
|---|---|
| `gh` | pull requests and CI runs, once the repository is on GitHub |
| `jq`, `rg` | reading JSON, searching the tree |
| Workato Connector SDK | local tests of a custom connector (the `connector-development` skill) |

Not verified: Workato Labs also publishes recipe-writing skills
(<https://github.com/workato-devs/recipe-skills>), which teach a flow of writing recipe JSON and
pushing it. Read them as a personal reference if you like, but do not copy them into
`.agents/skills/`: a second procedure for the same task would compete with `workato-recipe-edit`
and the rule **Push procedure**.

## How a workspace adds a tool

A new tool or MCP server needs two things before anyone uses it in the repository:

1. **The maintainer's yes.** The maintainer is named under `maintainer` in the registry.
2. **A line in [decisions.md](../conventions/decisions.md)**: what the tool is, what it is for,
   who decided and why. That file belongs to the workspace, so the kit never changes it.

Then:

- **An MCP server the kit lists as optional** (today: `atlassian`): add it to `mcp_servers` in
  `workato/workspaces/<workspace>/harness.json` and run `scripts/sync_harness.py`.
- **A command the agents should run without asking in Claude Code**: add an allow rule to
  `claude_allow` in `harness.json` and run `scripts/sync_harness.py`. It accepts only the
  workspace's own scripts, `Bash(scripts/ws_<name>.py)` or `Bash(scripts/ws_<name>.py *)`, and
  single tools `mcp__<server>__<tool>` of an optional server the workspace switched on. Any other
  permission is personal and goes into your own `.claude/settings.local.json`. Never allow a
  command that changes Workato.
- **A script of the workspace**: name it `scripts/ws_<name>.py` (a shared module
  `scripts/lib/ws_<name>.py`), with tests in `tests/test_ws_<name>.py`, written to
  [python.md](../conventions/python.md). A CI workflow of the workspace is
  `.github/workflows/ws-<name>.yml`. The kit never uses the `ws` prefix, so an update cannot
  collide with these files.
- **A skill of the workspace**: `.agents/skills/ws-<name>/SKILL.md`, listed in the last section of
  [AGENTS.md](../../AGENTS.md) ([skills.md](skills.md#a-skill-of-the-workspaces-own)).
- **Anything that needs a kit file changed** (a new MCP server in `.agents/mcp.json`, a skill or
  a role for every workspace): propose it to the kit
  ([updating.md](updating.md#send-an-improvement-back-to-the-kit)).

Only remote MCP servers with per-user sign-in belong in the configuration: no tokens, no
command-line servers with credentials in their arguments.

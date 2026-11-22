# Skills and subagent roles

## Skills

A skill is a written procedure that an agent loads when the task matches: how to change a
recipe, how to deploy, how to read job history. A skill installs nothing and grants no access or
permission. Which skill belongs to which task is the table in [AGENTS.md](../../AGENTS.md).

The source of every skill is `.agents/skills/<name>/SKILL.md`. `scripts/sync_harness.py` copies
it to `.claude/skills/` for Claude Code; never edit the copy. The three skills that need the
Atlassian server (`confluence-recipe-pages`, `search-company-knowledge`, `triage-issue`) are
copied only while the workspace has that server switched on ([atlassian.md](atlassian.md)), so
Claude Code does not offer them to a team without Atlassian. Not verified: Codex, Cursor, Gemini
CLI, Antigravity and GitHub Copilot read `.agents/skills/` directly; there every skill is present,
and the three Atlassian skills say themselves that they apply only with the server on.

| Skill | What it covers |
|---|---|
| `environment-preflight` | which environment the `wk` profile and the MCP server really act in |
| `change-impact-review` | what a change, a deployment or a decommission touches |
| `connector-development` | building and testing a custom connector |
| `workato-recipe-edit` | changing a recipe in Dev: pull, compare, push, verify, lint |
| `workato-start-stop` | stopping and starting a recipe, and what a stop does to callers |
| `workato-assets` | connections, tags, data tables, deleting anything |
| `workato-prod-deploy` | deploying a project from Dev to Prod |
| `workato-recipe-json` | reading recipe JSON, refreshing the Prod copy, checking for drift |
| `workato-job-history` | job history, failed jobs, the audit log |
| `recipe-docs` | writing a recipe doc in this repository |
| `confluence-recipe-pages` | Confluence pages about recipes; only with the Atlassian integration |
| `search-company-knowledge`, `triage-issue` | vendor skills for Jira and Confluence; only with the Atlassian integration |

The skills belong to the kit. A workspace does not edit them; it adds to them in its notes
(below), or writes a skill of its own.

## A skill of the workspace's own

A procedure that only this workspace follows gets its own skill:

```text
.agents/skills/ws-<name>/SKILL.md
```

`<name>` holds lower-case letters, digits and dashes. The file starts with a frontmatter that has
a `name`, equal to the folder name, and a `description`.

The kit never uses the `ws-` prefix, so an update of the kit never touches such a skill. List it
in the last section of [AGENTS.md](../../AGENTS.md), "Rules of this workspace": its name in
backticks, such as `ws-orders`, and when to load it. Then run:

```bash
scripts/sync_harness.py
```

`make check` fails while a skill of the workspace's own is not named in that section, and while
that section names one that does not exist. It also fails while the table "Which skill to load"
names one: the kit owns that table. Such a skill needs no notes file (below): it is the
workspace's own text already.

A procedure every workspace could use belongs in the kit instead: propose it there
([updating.md](updating.md#send-an-improvement-back-to-the-kit)).

## Notes of a workspace

Every skill of the kit ends with a section "This workspace" that points at one file of the
workspace (the vendor skills point at it in their "Local rules" block):

```text
workato/workspaces/<workspace>/notes/<skill-name>.md
```

When that file exists, the agent reads it before it acts. It holds what this workspace adds to
the procedure: the names of its shared connections, its release order, where its wiki pages
live, which Jira project gets its tickets. Write only what is particular to the workspace; the
procedure itself stays in the skill.

Because the notes are files of the workspace, an update of the kit never conflicts with them
([updating.md](updating.md#who-owns-which-file)). `scripts/init_workspace.py` creates the
`notes/` folder from `workato/workspace-template/`.

## Vendor skills

| Skill | Source | Commit | License | Changed here |
|---|---|---|---|---|
| `search-company-knowledge`, `triage-issue` | [atlassian/atlassian-mcp-server](https://github.com/atlassian/atlassian-mcp-server), folder `skills/` | `352a02b05189e2a958a973867cc6eca365cb8fc3` | Apache-2.0, `.agents/licenses/atlassian.txt` | the "Local rules" block after the frontmatter |

The kit is under the MIT License; these two stay under Apache-2.0. Only their "Local rules"
block is written by the kit. Its heading says that it was added here and is not part of the
upstream skill; that heading is the notice of change the license asks for. They apply only when
the workspace switched the Atlassian server on ([atlassian.md](atlassian.md)), and they use your
existing Atlassian connection. Their notes files are `notes/search-company-knowledge.md` and
`notes/triage-issue.md`; the second holds the Jira project, the components and the fields every
ticket gets.

To update one:

1. Copy its folder from the upstream repository at a newer commit over
   `.agents/skills/<name>/`.
2. Put the "Local rules" block back after the frontmatter.
3. If you had to change any other file of the skill, add a note of the change to that file too.
4. Change the commit in the table above.
5. Run:

   ```bash
   scripts/sync_harness.py
   ```

   ```bash
   make check
   ```

Never run a bulk skill installer over `.agents/skills/`: it would overwrite the kit's skills.

## Subagent roles and models

A subagent role is described once: its metadata in `.agents/agents.json`, its prompt in
`.agents/roles/<name>.md`, its model and effort per provider in `.agents/models.json`.
`scripts/sync_harness.py` generates `.claude/agents/<name>.md` for Claude Code and
`.codex/agents/<name>.toml` for Codex.

| Role | What it does |
|---|---|
| `workato-operator` | read-only Workato operations: recipe JSON, the copies, lint, the Dev/Prod comparison |
| `architect` | research, design, root-cause analysis |
| `task-worker` | one bounded sub-task: a doc, a script change, a ticket |
| `log-analyst` | job history and log analysis |

No role writes to Workato: writes are made in the main conversation, one recipe at a time (rule
**One writer** in [AGENTS.md](../../AGENTS.md)). A subagent still has the write tools; the rule
is an instruction in each role, not a tool restriction.

There is no role of the workspace's own: `.agents/agents.json` is one file of the kit, and a
role added there would conflict with the next update. A workspace changes only the models of the
kit's roles, in its `harness.json` (below).

**Model choices.** `.agents/models.json` holds the kit's defaults, per provider (`claude`,
`codex`) and per role: a `model` and an `effort`. A missing value or `null` means the session's
own. A workspace overrides them in `workato/workspaces/<workspace>/harness.json`, without
touching the kit's file:

```json
{
  "models": {
    "claude": {"architect": {"model": "opus", "effort": "max"}},
    "codex": {"task-worker": {"effort": "low"}}
  }
}
```

The kit's defaults give the two roles that follow a written procedure (`workato-operator`,
`task-worker`) a smaller model in Claude Code (`sonnet`, effort `medium`), and the two roles that
reason (`architect`, `log-analyst`) the session's model with effort `high`. For Codex every role
runs on the session's model, with the same efforts.

The workspace's values win, key by key; a role or a provider it does not name keeps the
defaults. Run `scripts/sync_harness.py` afterwards. Allowed efforts:

| Provider | Efforts |
|---|---|
| `claude` | `low`, `medium`, `high`, `xhigh`, `max` |
| `codex` | `minimal`, `low`, `medium`, `high`, `xhigh` |

`scripts/sync_harness.py` refuses any other value. Which model names a harness accepts is up to
the harness and your plan.

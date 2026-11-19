@AGENTS.md

# Claude Code notes

Everything above comes from `AGENTS.md`, the rules file every harness reads. Edit rules there,
not here. This part holds only what is specific to Claude Code.

## Subagents

Generated in `.claude/agents/` from `.agents/agents.json` and `.agents/roles/`. The model and the
effort of each come from `.agents/models.json`, and a workspace can override them in its
`harness.json`. Delegate when the work matches; otherwise do it yourself.

| Subagent | Use it for |
|---|---|
| `workato-operator` | read-only Workato operations: pull recipe JSON, refresh the copies, lint, the Dev/Prod comparison, reads |
| `architect` | research, planning, problem solving, anything about architecture or design |
| `task-worker` | a well-scoped sub-task: a doc, a script change, a ticket or a wiki page |
| `log-analyst` | job history, failed jobs, the audit log and other log analysis |

**No subagent writes to Workato** (rule **One writer** in `AGENTS.md`). Claude Code can run a
subagent in the background, where a chat message relayed to it can redirect it in the middle of a
write. Recipe edits, starts, stops, tags and deployments are made in the main conversation, one
recipe at a time. This is an instruction in each role, not a tool restriction: a subagent still has
the write tools.

## Skills, hooks, settings

- `.claude/skills/` is a generated copy of `.agents/skills/`. Edit the source, then run
  `scripts/sync_harness.py`. A skill that needs an optional MCP server (the Atlassian skills) is
  copied only while the workspace switches that server on in `harness.json`.
- `.claude/settings.json` is generated too, from `.agents/claude-settings.json`, the two `wk`
  profiles of the registry and `claude_allow` in the workspace's `harness.json`. It allows the
  read-only `wk` commands, most of the kit's scripts (none of the allowed calls changes Workato)
  and a few read tools of the Workato MCP server; in Manual mode every Workato write asks you,
  unless you saved an approval for it ([Approvals](docs/setup/harnesses.md#approvals)). Never
  edit it by hand: the next sync overwrites it. `.agents/generated-files.json` lists every
  generated file.
- The allowed scripts are files of the working tree. Keep automatic acceptance of file edits off
  in this repository: with it, an agent could change a script and run it under its allow rule
  without asking. The allowed sync and index scripts rewrite their own tracked files (the Prod
  copy, the recipe index, lookup-table descriptions, `prod_recipe_id` in recipe docs): read
  `git diff` before a commit.
- `scripts/guard_wk.py` runs as a hook before every Bash command. It blocks `wk pull`, `wk diff`,
  `wk clone`, `wk push`, every shell use of `wk auth token` and `wk mcp auth-header`, commands
  that name `profiles.env`, `wk ... -o` with a file outside `tmp/`, `wk --verbose`, and `xargs wk`
  fed from standard input. It guards against mistakes; it is not a security boundary. It needs
  `python3.14` on the PATH of Claude Code: without it every Bash command is blocked with a
  message that says so.
- Start Claude Code at the repository root. Claude Code loads `.claude/settings.json` from the
  folder it starts in, so a session started in a subfolder has neither the guard hook nor the
  shared allow list.
- Personal permissions go in `.claude/settings.local.json`, which is git-ignored.
- `.mcp.json` lists the project's MCP servers; it is generated from `.agents/mcp.json`. Each
  person approves and signs in to them once (`/mcp`). Sign in to the Workato server while the Dev
  environment is active in the browser. The `atlassian` server appears only when the workspace
  switches it on in `harness.json`; if your Claude account already provides an Atlassian
  connector, use one of the two, not both.

## Temporary files

The session scratchpad of Claude Code disappears with the session. Anything worth keeping between
sessions goes to `tmp/` (see "Working cache" in `AGENTS.md` and [tmp/README.md](tmp/README.md)).

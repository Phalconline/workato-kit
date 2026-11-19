# Instructions for GitHub Copilot

Follow `AGENTS.md` at the repository root. It is the single rules file of this repository; this
file only points to it. The kit configures no hook for Copilot, so the rules **No package
commands** and **Secrets** in `AGENTS.md` are the only guard against a forbidden `wk` command.
Not verified: the kit was not run with Copilot.

When reviewing a change, check these first:

- No secret and no API token in a tracked file, and no `profiles.env`, `.wk/`, `.env*`,
  `master.key` or `settings.yaml` file. Personal data from a job title or an error text, such as
  an e-mail address, is written as `<user>`.
- Nothing under `workato/workspaces/<workspace>/projects/`, and not
  `inventory/recipes-index.json`, was edited by hand: they change only through the scripts that
  generate them. `inventory/recipes.json`, an optional sheet of recipes, is kept by hand.
- No rows of lookup tables or data tables anywhere.
- No link to a file under `tmp/`, other than `tmp/README.md`.
- No file below the root is named `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`, in any letter case.
- A recipe doc cites no step numbers and names a called recipe by a link, not by a bare id.
- The generated harness files (`.claude/settings.json`, `.claude/skills/`, `.claude/agents/`,
  `.codex/agents/`, `.codex/config.toml`, `.cursor/mcp.json`, `.gemini/settings.json`,
  `.mcp.json`, `.agents/mcp_config.json`, `.agents/generated-files.json`) match their sources
  (`scripts/sync_harness.py --check`).
- A file the kit owns holds nothing of this workspace: no id, address, host or name.
  `scripts/check_kit_files.py` catches the shapes and the names the registry holds, not every
  name. Workspace facts go to the registry, to `notes/`, to the docs of a project or to the last
  section of `AGENTS.md`.
- A changed script follows `docs/conventions/python.md`: standard library only, typed, and with
  its tests in `tests/test_<script>.py`.

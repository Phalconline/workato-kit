# Updating from the kit

A workspace repository made as in [new-workspace.md](new-workspace.md) shares its history with
the kit and keeps it as the remote `kit`. Updates of the kit arrive by an ordinary git merge.
Changes of the workspace itself after setup, such as a new project, a rename or a new
maintainer, are in [maintaining.md](maintaining.md).

## Take an update

Fetch the kit:

```bash
git fetch kit
```

Read what changed before you merge. [CHANGELOG.md](../../CHANGELOG.md) of the kit lists each
change and the migration steps, for example a new registry key:

```bash
git diff HEAD...kit/main -- CHANGELOG.md
```

Merge on a clean working tree:

```bash
git merge kit/main
```

Regenerate the harness files from the merged sources. This rewrites the permissions of Claude
Code, so run it yourself or approve the run:

```bash
scripts/sync_harness.py
```

When `.claude/settings.json` changes, the script prints every permission rule it adds or removes
under `Permission rules of .claude/settings.json:`, for example
`  allow + Bash(scripts/check_kit_files.py *)`. When `.mcp.json` changes, it prints the servers
under `MCP servers of .mcp.json:`, as `  server + <name> <url>`. Read those lines: they are what
an update of the kit lets an agent run without asking, and where a harness connects. The script
compares with the file on disk, so after a conflict in one of these files read the diff
described under [Resolve a conflict](#resolve-a-conflict) instead.

Run the offline checks:

```bash
make check
```

If `sync_harness.py` changed files, commit them:

```bash
git add .claude .codex .cursor .gemini .mcp.json .agents/mcp_config.json \
  .agents/generated-files.json
```

```bash
git commit -m "Regenerate the harness files after the kit update"
```

Then push to your own repository:

```bash
git push
```

Never push to the kit: its push URL is set to `no-push`. Never use `git push --mirror` for an
update; it overwrites every branch of the target.

### When the update changes the workspace template

`scripts/init_workspace.py` copied `workato/workspace-template/` into your workspace folder once.
A kit update that changes the template, as its CHANGELOG entry says, does not reach that copy by
the merge. Run the script again with your workspace name and the two profiles. It adds the
template files your folder lacks and overwrites none. Like every re-run, it also reads the
project lists of both environments and registers what is new there
([new-workspace.md](new-workspace.md#create-the-workspace-folder)):

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
```

A changed template file that your folder already has stays as it is: copy what you want from
`workato/workspace-template/` by hand. The template's `{workspace}` stands for the name of your
workspace.

## Who owns which file

Every file has one owner. The kit changes only its own files, and a workspace changes only its
own, so a merge rarely conflicts. A generated file can; [Resolve a conflict](#resolve-a-conflict)
says what to do.

| Owned by the kit: a workspace repository does not edit them | Owned by the workspace repository |
|---|---|
| `scripts/` and `tests/` of the kit, `Makefile`, `pyproject.toml`, `.github/workflows/` except `ws-*.yml`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.python-version`, `.cursorignore`, `.geminiignore` | `workato/workspaces/<workspace>/`, all of it: registry, Prod copies, templates, connectors, lookup tables, inventory, `harness.json`, `notes/` |
| `.agents/`: skills except `ws-*`, roles, `agents.json`, `models.json`, `mcp.json`, `claude-settings.json`, licenses; `.codex/hooks.json` | `docs/<project-slug>/` of each project, and `docs/recipe-index.md` (generated; the kit ships none) |
| `AGENTS.md` except its last section, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` | the last section of `AGENTS.md`, "Rules of this workspace" |
| `README.md`, `LICENSE`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `docs/README.md`, `docs/setup/`, `docs/conventions/` except `decisions.md`, `docs/knowledge/workato/` | `docs/conventions/decisions.md` (the workspace's decision log), `docs/knowledge/workspace/` (its own notes) |
| `workato/workspace-template/`, `workato/workspaces/README.md`, `tmp/README.md` | its own scripts and tests: `scripts/ws_<name>.py`, `scripts/lib/ws_<name>.py`, `tests/test_ws_<name>.py` (also without a script of that name); its own skills `.agents/skills/ws-<name>/`; its own CI workflows `.github/workflows/ws-<name>.yml`. The kit never uses these names. |

A workspace has no subagent role of its own: `.agents/agents.json` is one file, and the kit owns
it.

The generated harness files (`.claude/`, `.codex/agents/`, `.codex/config.toml`, `.cursor/`,
`.gemini/`, `.mcp.json`, `.agents/mcp_config.json` and `.agents/generated-files.json`) belong to
neither: each repository commits its own render, made by `scripts/sync_harness.py` from the
sources above and the workspace's registry and `harness.json`. `.agents/generated-files.json`
lists them; the script deletes only a file that list names.

What follows from the table:

- A workspace says what it needs in its own files: the registry, `harness.json`, `notes/`, the
  last section of `AGENTS.md`, `decisions.md`. It never needs to edit a kit file for that.
- A change to a kit file in your repository will meet the next change of the kit to the same
  lines. If a kit file is wrong, send the fix to the kit (below) instead of keeping a local edit.

## Resolve a conflict

List the files in conflict:

```bash
git status
```

**A kit-owned file.** Take the kit's side, unless you changed that file on purpose:

```bash
git checkout --theirs -- <file>
```

```bash
git add -- <file>
```

In a merge, `--theirs` is `kit/main`. If you did change the file on purpose, merge the two by
hand, and send your change to the kit so that the next update does not conflict again.

**`AGENTS.md`.** Keep the kit's text above "Rules of this workspace" and your text in that
section. Then mark the file as solved:

```bash
git add -- AGENTS.md
```

**A generated file.** Each workspace commits its own render of `.claude/settings.json` and the
MCP files, so a kit change next to the workspace's lines can meet it. Take either side, then
regenerate it after the other conflicts are solved:

```bash
git checkout --theirs -- <file>
```

```bash
scripts/sync_harness.py
```

What the script prints now compares with the side you took, not with your last commit, so it
does not show what the update changes. Read that diff instead:

```bash
git diff HEAD -- .claude/settings.json .mcp.json
```

```bash
git add .claude .codex .cursor .gemini .mcp.json .agents/mcp_config.json \
  .agents/generated-files.json
```

**A workspace-owned file.** The kit ships none, except an empty
`docs/conventions/decisions.md` and the empty last section of `AGENTS.md`. Keep your side:

```bash
git checkout --ours -- <file>
```

```bash
git add -- <file>
```

Then finish the merge and run the checks:

```bash
git commit
```

```bash
make check
```

If `make check` fails in `JSON files and registry` after an update, the CHANGELOG names the
registry change and what to do. `scripts/check_data.py` rejects an unknown key, so a renamed key
shows up there, as `Invalid registry: workato/workspaces/<workspace>/registry.json: <slug>:
unknown key <old name>`.

## Send an improvement back to the kit

The kit is public; your repository is not. A change goes back only as kit-owned files, and only
without anything of your workspace: no id, address, host, name, process or date of it.

1. Clone the kit fresh, **outside** the folder of your repository. A copy inside it would be
   checked and loaded as part of your repository.
2. Make the change there, in kit-owned files only. Use the kit's invented examples, never your
   own names. Leave two places alone even though they are in the kit:
   `docs/conventions/decisions.md` and the first paragraph of the last section of `AGENTS.md`.
   Every workspace writes there, so a change would conflict in every workspace.
3. Run the checks of the kit. `scripts/check_kit_files.py` fails on a number of five or more
   digits, an e-mail address outside the example domains, a host that is not on its list of
   public hosts, a bracket code or a ticket key other than the examples, a date before 2030,
   non-Latin text, a home-directory path and a symbolic link. In your repository it also knows
   the names your registry holds; a fresh clone of the kit has no registry, so there it does not
   know them:

   ```bash
   make dev
   ```

   ```bash
   make check
   ```

4. Read your diff once more for what no check finds: the name of a project, a recipe, a
   connection or an app your workspace uses, a description of how your company works.
5. Propose the change as [CONTRIBUTING.md](../../CONTRIBUTING.md) describes.

Never push a branch of your workspace repository to the kit, and never open a pull request from
it: its history holds your workspace data.

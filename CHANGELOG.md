# Changelog

What changed in the kit, newest first. A workspace repository reads this file after it merges a
kit update ([docs/setup/updating.md](docs/setup/updating.md)).

Each entry lists what changed. When a merge needs a manual step in a workspace repository (a new
registry key, a renamed file, a changed command), the entry has a section "What a workspace
repository must do" with the exact steps. An entry without that section needs only the usual
steps after every merge:

```bash
scripts/sync_harness.py
```

```bash
make check
```

## Unreleased: after the first version

What a workspace learned in its first weeks on these rules, brought back to the kit.

- **Docs in step with Workato.** New rule **Sync the docs around a recipe** and new script
  `scripts/doc_sync.py`: `plan` lists a recipe, what it calls, its connections and tables and
  what shares them, each with its doc and whether the doc is stale; `stamp` records in
  `inventory/doc-sync.json` that a doc was compared with the live asset; `status` audits every
  recipe doc. Claude Code may run `plan` and `status` without asking, never `stamp`.
- **Step numbers are checked.** New script `scripts/check_step_numbers.py`, part of
  `make check`: it fails on "step 12" in a recipe doc and on a numbered list that does not count
  from 1 in a row.
- **The Jobs view.** New rule **A recipe has a Jobs view** and new page
  `docs/conventions/job-view.md`: a recipe gets a job report (the columns of its Jobs tab) with
  its first push, reviewed after every edit. New lint check `JOB_VIEW` for a project that lists
  it under `lint_checks`: `JOB_VIEW_MISSING`, `JOB_VIEW_STALE` and `JOB_VIEW_MASKED`.
- **Data masking.** New rule **Sensitive data stays out of job history** and new page
  `docs/conventions/data-masking.md`: a credential is masked in every step it passes through and
  never sent where a mask does not reach; personal data of people outside the organization is
  masked by default, unless the recipe doc says why it stays readable. New lint finding
  `UNMASKED_CREDENTIAL`, a warning, for a step that carries a credential by name and has no
  mask. The recipe doc template gains a "Masked steps" line.
- **Descriptions and comments describe the recipe as it is.** The rule **A description
  describes** now also keeps comparisons with an older version or a replaced system out of
  descriptions and comments. New registry key `lint_prose_patterns` and lint finding
  `PROSE_PATTERN` for the words a workspace does not want there.
- **Rows of a data table.** `scripts/wk_api.py --data-tables` calls the record API of data
  tables on the `data-tables` host of the profile's data center: a query reads, and creating,
  changing or deleting a record needs `--write`. No permission rule lets it run without asking.
- **Tables in the recipe index.** `scripts/build_index.py` now lists every table that a data
  table step or a lookup table step names by its id, as `data table <id>` or `lookup table <id>`,
  not only the tables the registry names. The "Used by" list of a lookup table therefore fills
  without an entry in the registry.
- **Skills.** `workato-recipe-edit`: the doc sync plan before an edit and the stamp after it, the
  job report, and no reliance on the `version` that `wk recipes get` shows. `recipe-docs`: the
  doc sync procedure. `workato-assets`: tags as part of a build where the workspace's rules say
  so, the record API, and what a column change keeps. `workato-prod-deploy`: what was observed at
  deployments (recipes restarted, a recipe left stopped, the second connection slot of one
  connector left empty) and the comparison of the run state afterwards.
  `confluence-recipe-pages`: a published page follows Prod, for every change that reaches Prod.
- **Roles.** `architect`: a plan for a new recipe, or for a change to the steps of one, names
  the columns of its Jobs tab.
- **Checks outside a git clone.** `check_data.py`, `check_secrets.py` and `check_kit_files.py`
  read the files git knows. In a folder that is no git clone, an unpacked archive for example,
  they now stop with one line that says so, instead of a traceback.
- **Platform notes.** Uploading a webhook trigger and a job report as raw JSON
  (`recipe-builder-traps.md`); switching from a webhook recipe to its replacement by recipe state
  (`platform-notes-queueing.md`).

### What a workspace repository must do

After the merge, besides the usual two steps:

1. `scripts/sync_harness.py` adds three allow rules to `.claude/settings.json`:
   `Bash(scripts/check_step_numbers.py *)`, `Bash(scripts/doc_sync.py plan *)` and
   `Bash(scripts/doc_sync.py status *)`. Read the lines it prints before you commit.
2. `make check` now fails on a step number in a recipe doc. List the findings and rewrite each
   one to say what the step does:

   ```bash
   scripts/check_step_numbers.py
   ```

3. Rebuild the recipe index and the lookup-table descriptions, because `tables` of an index
   entry gains the tables found by their steps:

   ```bash
   scripts/sync_recipes.py dev
   ```

   ```bash
   scripts/build_index.py
   ```

   ```bash
   scripts/sync_lookup_tables.py
   ```

4. The stamps start empty, so the first `scripts/doc_sync.py status` lists every recipe doc as
   never synced. Do not stamp them in bulk: a stamp says a doc was compared. Compare and stamp
   the docs around each recipe as you work on it, as the new rule says.
5. `scripts/lint_recipes.py` may now warn `UNMASKED_CREDENTIAL` on recipes you already have.
   A warning does not fail the run. Read each one: mask the step (the recipe must be stopped
   for that, so it needs a request), or note in the recipe doc why the name is no credential.
6. Optional, in the registry: add `JOB_VIEW` to `lint_checks` of a project once its recipes have
   job reports, and list under `lint_prose_patterns` the words you do not want in descriptions
   and comments (`docs/conventions/registry.md`).

## Unreleased: first version

The first version of the kit. It holds:

- **Rules for agents:** `AGENTS.md`, with named rules and an empty last section, "Rules of this
  workspace", for the rules of a workspace. `CLAUDE.md`, `GEMINI.md` and
  `.github/copilot-instructions.md` point at it.
- **Skills** in `.agents/skills/`: environment preflight, change impact review, connector
  development, recipe edit, start and stop, assets, Prod deployment, recipe JSON, job history and
  recipe docs. For the optional Atlassian integration: Confluence recipe pages and two pinned
  vendor skills under Apache-2.0. Each skill of the kit ends by pointing at the notes file of the
  workspace for that skill.
- **Subagent roles** in `.agents/roles/`: `architect`, `log-analyst`, `task-worker` and
  `workato-operator`, with default models in `.agents/models.json`.
- **Harness configuration** for Claude Code, Codex, Cursor, Gemini CLI, Antigravity CLI and
  GitHub Copilot, generated by `scripts/sync_harness.py` from `.agents/` and the workspace
  (`registry.json` and `harness.json`). `.agents/generated-files.json` lists the generated files;
  the script deletes no other file. The guard hook of Codex (`.codex/hooks.json`) and the ignore
  files `.cursorignore` and `.geminiignore` are written by hand.
- **Permissions of Claude Code:** read-only `wk` commands and most of the kit's scripts, none
  of which changes Workato, run without asking; in Manual mode every Workato write asks, unless
  you saved an approval for it. The deny list covers the package commands of `wk`, the token
  commands, and reading the credential files of `wk`, the `.env` files of the root and the
  secrets of a connector project.
- **Eighteen scripts** in `scripts/`, standard library only:
  - offline checks: `check.py` (what `make check` runs), `check_data.py`, `check_links.py`,
    `check_secrets.py`, `check_kit_files.py`;
  - setup: `init_workspace.py` (creates the workspace folder and the registry from two `wk`
    profiles, and adds what is new when run again), `doctor.py`, `sync_harness.py`;
  - Workato reads: `sync_recipes.py`, `lint_recipes.py`, `prod_drift.py`,
    `prod_jobs_report.py`, `sync_lookup_tables.py`;
  - local copies and docs: `link_prod_ids.py`, `render_recipe.py`, `build_index.py`;
  - `wk_api.py` for one API call that `wk` does not cover, with the token kept inside the process;
  - `guard_wk.py`, the hook that blocks six groups of commands: the package commands of `wk`
    (`pull`, `diff`, `clone`, `push`); every shell use of `wk auth token` and
    `wk mcp auth-header`; commands that name the token file `profiles.env`; `wk ... -o` with a
    file outside `tmp/`; `wk --verbose`; and `xargs wk` fed from standard input.
- **Tests** in `tests/`, one module per script, offline.
- **Docs:** setup for a new workspace and for a person joining one, kit updates, life after setup
  (`docs/setup/maintaining.md`), Workato and `wk`, the harnesses, the skills, the tools and the
  optional Atlassian integration; conventions (Python, the recipe doc template, the registry,
  the reasons behind each rule, an empty decision log); platform notes on Workato.
- **The workspace template** in `workato/workspace-template/`, copied by `init_workspace.py`:
  a README, `harness.json` and `notes/`.
- **Names a workspace owns**, which the kit never uses: `scripts/ws_*.py`,
  `scripts/lib/ws_*.py`, `tests/test_ws_*.py`, `.agents/skills/ws-<name>/` and
  `.github/workflows/ws-*.yml`.
- **CI:** `.github/workflows/check.yml` runs `make dev check`.
- **License:** the MIT License, in `LICENSE`. The two vendor skills stay under Apache-2.0.

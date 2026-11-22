---
name: workato-recipe-edit
description: Change a Workato recipe in Dev safely. Use before building, editing or pushing any recipe through the Workato MCP recipe builder or the wk CLI. Covers the project check, the pull-compare-push-verify procedure, comments and descriptions, connections, the job report, data masking, lint, and what to record afterwards.
---

# Change a recipe in Dev

Every recipe change is made in Dev. Prod changes only through a deployment: see the
`workato-prod-deploy` skill. This skill is the procedure behind rules **Push procedure**,
**One writer** and **Check the project first** of `AGENTS.md`.

`<dev-profile>` below is `environments.dev.profile` of
`workato/workspaces/<workspace>/registry.json`, for example `acme-dev`. At the first write of a
session, load `environment-preflight` first.

## 1. Know what you are editing

- Read the recipe with `recipe_get` and note its project id. Compare it with
  `projects.<slug>.dev.project_id` in the registry. A project with `"snapshots": true` is a
  managed project; any other recipe is in a Dev-only project or in none the registry knows.
- A name or a prefix does not tell you the project. Lint and doc location depend on it.
- Run `scripts/doc_sync.py plan <dev recipe id>` and refresh what it lists as stale
  (`recipe-docs`, rule **Sync the docs around a recipe**). You then edit against docs you can
  trust, and the docs of what the recipe calls, uses and shares are current before the change.
- Check `running` first. Workato refuses every change to a running recipe, the description
  included; only a tag can be added without a stop (observed:
  `docs/knowledge/workato/recipe-builder-traps.md`). A stop and a start need the request to say
  so: if it does not, say what the stop does and ask. See `workato-start-stop`.

```bash
wk -p <dev-profile> recipes get <id> -j
```

- If the last section of `AGENTS.md`, "Rules of this workspace", names this recipe, follow that
  rule and say in the same message as the push how you did.

## 2. Edit

- Pull a fresh recipe before preparing each change and use it as the base
  (`recipe_builder_pull`). Keep the raw JSON of that base, the file `wk recipes pull` writes, for
  the comparisons before and after the push:

```bash
mkdir -p tmp/edits/<YYYY-MM-DD>-<topic>
wk -p <dev-profile> recipes pull <id> -o tmp/edits/<YYYY-MM-DD>-<topic>/<id>-before.json
```

- A builder pull replaces local edits. Never pull an edited session and then push without
  reapplying the edits.
- Write from the main conversation, never from a subagent: a harness may run a subagent in the
  background, and a write must stay where the person sees it.
- Edits go through `recipe_builder_*`. What the builder cannot express (a datapill in a picklist
  or a code field, a toggle it resets) is patched in the raw JSON and uploaded with
  `wk recipes update`. The recipe must be stopped for that too.

```bash
wk -p <dev-profile> recipes update <id> <file>
```

- A file from `wk recipes pull` holds the platform defaults for `private` and `concurrency`
  (false and 1), not the recipe's values (`wk recipes pull --help`). Before `wk recipes update`,
  set those two keys in the file to the values `wk -p <dev-profile> recipes get <id> -j` shows.
  Not verified: whether the upload sends those two keys at all; setting them costs nothing.
- Never `wk pull`, `wk diff`, `wk clone` or `wk push` (rule **No package commands**).
- Step comments and descriptions follow rule **Comments and descriptions belong to people**.
  Adding a comment to a step that has none, or to a step you create, is fine. A comment goes
  stale when a step number or a recipe id it names changes: then say so in chat with the current
  text and a suggested replacement, and let the person make the edit.
- A description follows rule **A description describes**. Test notes and release to-dos go in a
  runbook or a backlog, not in the recipe. Neither a description nor a comment compares the
  recipe with an older version or with a system it replaced. Before you upload recipe JSON you
  generated, read every `comment` field and the comment lines of every code step for that.
- **The job report.** A recipe you create gets its job report (the columns of its Jobs tab) in
  the same push as its steps. After an edit, review the columns against the changed recipe and
  fix them in the same task: a step that was removed or renamed, a new key input, a new outcome
  (rule **A recipe has a Jobs view**). The columns are chosen for this recipe alone, never copied
  as a template. What to choose, the limits and the JSON keys are in
  `docs/conventions/job-view.md`.
- **Data masking** (rule **Sensitive data stays out of job history**,
  `docs/conventions/data-masking.md`). Every step that creates, reads or passes on a password, a
  passcode, a token, an API key or a client secret has "Mask data" on (`"mask_data": true` on
  the block in the raw JSON), and such a value never goes into a chat or e-mail message, a logger
  step, a job report column, a function's result or a `catch` message, unless a person receives
  it by design. A step that holds personal data of people outside the organization is masked
  too, unless the recipe doc says why it stays readable. Set the masks in the same push as the
  steps, and never remove a mask a person set unless the request says so.
- Bind only connections that rule **Connections stay in reach of a deployment** allows, even when
  the builder offers another one. See `workato-assets`.
- Common traps of the builder are in `docs/knowledge/workato/recipe-builder-traps.md`.

## 3. Push

- Immediately before pushing, read the remote recipe again and compare it with your base:

```bash
wk -p <dev-profile> recipes pull <id> -o tmp/edits/<YYYY-MM-DD>-<topic>/<id>-remote.json
diff <(python3.14 -m json.tool --sort-keys tmp/edits/<YYYY-MM-DD>-<topic>/<id>-before.json) \
     <(python3.14 -m json.tool --sort-keys tmp/edits/<YYYY-MM-DD>-<topic>/<id>-remote.json)
```

- No output means nothing changed. Compare the two files, not a version number. Observed:
  `wk recipes get <id> -j` reported `version` 0 for a recipe that had been saved many times. If
  the recipe changed, pull again (`recipe_builder_pull` and the raw JSON) and reapply the
  intended edits.
- Do not push while a person is editing that recipe in the UI.
- After the push, verify the saved changes with `recipe_get` and report them. The raw JSON is
  the source to trust over the render of the MCP pull:

```bash
wk -p <dev-profile> recipes pull <id> -o tmp/edits/<YYYY-MM-DD>-<topic>/<id>-after.json
```

- Compare the saved raw JSON with your base: every field that differs must be one you meant to
  change, except the three re-serializations of a builder push that
  `docs/knowledge/workato/recipe-builder-traps.md` lists ("A push changes things you did not
  touch"). Observed: the builder can reset a toggle or a picklist on its own. Any other
  unexpected difference is a finding to report, not something to leave.

```bash
diff <(python3.14 -m json.tool --sort-keys tmp/edits/<YYYY-MM-DD>-<topic>/<id>-before.json) \
     <(python3.14 -m json.tool --sort-keys tmp/edits/<YYYY-MM-DD>-<topic>/<id>-after.json)
```

`scripts/render_recipe.py <file>` prints a recipe file as a compact step tree, which helps to
read a difference.

## 4. Lint

- A recipe of a managed project: run the lint after every push.

```bash
scripts/lint_recipes.py --recipe <dev_recipe_id>
```

- Before a deployment, run it with no arguments: it checks every managed project.

```bash
scripts/lint_recipes.py
```

- The script refreshes the Dev copy into `tmp/wk/dev/` with one GET per recipe, runs `wk lint`
  with the kit's `scripts/wklintrc.json` (or the workspace's own `wklintrc.json`), drops the
  known false positives of three lint rules and adds the house checks: `PROPERTY_MISSING`,
  `MAGIC_LITERAL`, `UNFINISHED_STEP`, `SKIPPED_STEP` and `UNMASKED_CREDENTIAL`, and
  `PROSE_PATTERN` when the registry lists `lint_prose_patterns`. A project that lists them under `lint_checks` in the registry
  also gets `ACCOUNT_PROPERTY`, `NO_GUARD_PROPERTY` and `JOB_VIEW`.
- A recipe of a registered project that was never deployed (no Prod half in the registry): name
  the project, so the script finds it.

```bash
scripts/lint_recipes.py <slug> --recipe <dev_recipe_id>
```

- A recipe outside every registered project: run plain `wk lint` on its raw JSON, with the
  workspace's own configuration when `workato/workspaces/<workspace>/wklintrc.json` exists:

```bash
wk lint tmp/edits/<YYYY-MM-DD>-<topic>/<id>-after.json \
  --config-path workato/workspaces/<workspace>/wklintrc.json
```

  Otherwise use the kit's configuration:

```bash
wk lint tmp/edits/<YYYY-MM-DD>-<topic>/<id>-after.json --config-path scripts/wklintrc.json
```

## 5. Record and report

- Update the recipe's repo doc in the same task (`recipe-docs`), the "Jobs tab columns" and
  "Masked steps" lines of its Configuration section included. Then stamp what you compared:

```bash
scripts/doc_sync.py stamp recipe:<dev_recipe_id>
```

- Where the rules of the workspace say that tags are applied as part of a build, a recipe you
  created, or whose tags the change affects, gets its tags in the same task (`workato-assets`,
  "Tags as part of a build").
- Step numbers go in chat as Workato UI numbers (the JSON indexes the trigger as 0, so add 1).
  They never go into a recipe doc.
- Say in the same message what was pushed, started or stopped, naming each recipe.
- Nothing has changed in Prod yet. Name what a deployment will need there: a new project property
  value, a connection to authorize, a binding to restore.

## Do not

- Do not start a recipe only to produce a test job, and do not repeat a job, unless a person
  asked for that run (rule **No jobs on your own**). Build, verify from the raw JSON, then say
  what a run would prove and ask.
- Do not type secret values (rule **Secrets**). A person enters credentials in the Workato UI.

## This workspace

If `workato/workspaces/<workspace>/notes/workato-recipe-edit.md` exists, read it before you act: it
holds what this workspace adds to this procedure.

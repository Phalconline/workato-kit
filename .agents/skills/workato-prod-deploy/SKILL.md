---
name: workato-prod-deploy
description: Deploy a Workato project from Dev to Prod. Use when a person asks to deploy, release or move a change to Prod, and before any action that would change a Prod recipe. Covers the checks before a deployment, the deployment call, what does not travel with it, and the follow-up in Prod and in the repository.
---

# Deploy a project to Prod

A change reaches Prod only through a Workato deployment of the Dev project (**Prod changes only
by deployment**). A direct edit of a Prod recipe bypasses the deployment record, races with a
deployment that may already be pending, and is overwritten by the next one.

Deploy only when a person asks for that deployment (**Change only what was asked**). Without such
a request, name the recipes you changed in Dev and the follow-up Prod will need, and wait.

Deployments go from Dev to Prod. A workspace with the Environments feature also has a Test
environment (documented: <https://docs.workato.com/en/features/environments.html>); the
repository does not use it: never deploy to it.

Deploy from the main conversation, never from a subagent (**One writer**). The Prod copy in
`workato/workspaces/<workspace>/projects/` is refreshed with single-recipe GETs, never with the
package flow (**No package commands**).

The commands below use the registry: `scripts/wk_api.py dev|prod` and `scripts/sync_recipes.py`
pick the `wk` profile of that environment themselves. A `wk` command names the profile by hand:
`environments.dev.profile` or `environments.prod.profile` of the registry (for example
`acme-dev`, `acme-prod`).

## Before

When the deployment touches a shared asset (a connection of the project marked
`shared_connections`, a lookup table, a project property) or several projects, load
`change-impact-review` first.

**Was the project deployed before?** A project without a `prod` half in the registry was never
deployed, or was deployed after the last run of `scripts/init_workspace.py`. It has no Prod copy
and no drift check yet: `scripts/sync_recipes.py prod --check`
passes over it, and `scripts/prod_drift.py <slug>` refuses it with "is not synced in both Dev and
Prod". Lint it by name instead (`scripts/lint_recipes.py <slug>`), and read the follow-up of a
first deployment under "After".

**Is the Prod copy true?** A deployment overwrites the Prod logic of every recipe it carries.

```bash
scripts/sync_recipes.py prod --check
```

If it reports a difference, refresh the copy and read the diff next to the deployments since the
last sync, as **Keep the Prod copy true** says:

```bash
scripts/sync_recipes.py prod
git diff workato/workspaces/<workspace>/projects/
scripts/wk_api.py dev GET /deployments -q project_id=<dev project id>
```

A difference that no deployment explains is a direct Prod edit: stop and port it to Dev first, or
get a person's word to drop it.

**What will this deployment change?** For the whole project, or only for the recipes you changed:

```bash
scripts/prod_drift.py <project slug>
scripts/prod_drift.py --recipe <dev recipe id> [<dev recipe id> ...]
```

It lists differences in code, step comments, name, description and connection bindings, and the
project properties that are missing, blank or different in Prod (values are never printed).

| Finding | Meaning |
|---|---|
| `MISSING` | no Prod recipe with that folder and name: new, renamed or moved (not proof of new) |
| `PROD_ONLY` | a Prod recipe without a Dev counterpart; a deployment neither deletes nor moves it |
| `BINDING` | a connection slot the deployment cannot fill (see "What does not travel") |
| `COMMENT` | a step comment differs; people write them, so never overwrite one by accident |

For a reviewed rename or move pass `--pair DEV_ID:PROD_ID`. Exit `1` means differences to read;
exit `2` means the comparison could not be made. Never take a failed check for a clean one.

**Is a deployment already pending?**

```bash
scripts/wk_api.py dev GET /deployments -q project_id=<dev project id>
```

Not verified: that a pending deployment cannot be cancelled through the API and does not run on
its own. If an admin of the workspace switched on review and approval of deployments (Settings,
Deployments), the deployment follows that flow; its API endpoints are a private beta
(documented: <https://docs.workato.com/features/environments/deployment.html>).

**Are the changed recipes verified and linted?** That is part of `workato-recipe-edit`.

**Order.** Deploy the project marked `shared_connections` in the registry before a project that
uses its connections. Any further order the workspace needs is in its notes file (below).

**Privileges.** The deployment and the deployments list are calls of the Dev environment's API:
they run with the Dev profile. Workato lets only someone with access to the project and the
deployment privilege in both environments deploy (documented:
<https://docs.workato.com/features/environments/deployment.html>). For the API client of the Dev
profile, check its role screen in Workato for the privilege names.

The Prod API client may be read-only. Then every Prod-side step of this skill that writes (a
property value, a start, a stop, a tag) is done by a person in the Workato UI: name the step and
what to enter, and leave it to them.

## Deploy

```bash
scripts/wk_api.py dev POST /projects/<dev project id>/deploy --write \
  --json '{"environment_type": "prod"}'
```

Observed to work. Workato documents the form
`POST /projects/<id>/deploy?environment_type=prod`, which is `-q environment_type=prod` in place
of `--json` (<https://docs.workato.com/en/workato-api/projects.html>).

The script reads the Dev token inside its own process; `wk auth token` is never run in a shell
(**Secrets**). The call deploys the whole project. Observed: in the UI (Deploy, then Customize)
a person can choose single assets, and the review screen lists what the deployment adds and
updates; a custom connector can show there as updated although both environments hold the same
released code. Read the result in the deployments list:

```bash
scripts/wk_api.py dev GET /deployments -q project_id=<dev project id>
```

Say in the same message what was deployed and what it does in Prod:

- Observed: Workato stops the running recipes the deployment carries, updates them and starts
  them again. Not verified: that a call to a recipe function during its restart fails the caller
  with `WRF00409`.
- Observed: a recipe new to Prod arrives stopped. Starting it is a separate step that needs the
  request to say so (`workato-start-stop`).
- Observed: a recipe that ran before a deployment can be stopped after it, with no stop in the
  record. Compare the `running` state of every Prod recipe of the project after the deployment
  with the state before it (see "After").

## What a deployment does not do

- **It does not delete.** An asset removed in Dev stays in Prod. Remove it there as a separate,
  explicit step, after naming what depends on it (`workato-assets`, **Nothing destructive in
  silence**).
- **It does not move.** A recipe moved to another folder in Dev arrives as a second copy in Prod.
  Stop and remove the old Prod copy explicitly, or two recipes act on the same events.

Source: <https://docs.workato.com/features/environments/deployment.html>

## What does not travel

- **Project property values.** Not verified against Workato's documentation: a value does not travel
  with a deployment. `scripts/prod_drift.py` lists the properties that are missing, blank or
  different in Prod. Create or fill each one when the request covers it (not verified: `POST
  /properties` through `scripts/wk_api.py prod ... --write`). A person enters a secret. If the Prod API client is read-only, a person sets the value in
  the Workato UI.
- **A draft of a custom connector.** Not verified: a connector arrives as its latest released
  version.
- **Connection credentials.** Not verified: a connection new to Prod arrives without them; a
  person authorizes it in the Workato UI.
- **A binding to a connection the deployment cannot map.** Observed: a Dev recipe bound to a
  connection outside its own project and outside the project marked `shared_connections` leaves
  the Prod slot empty (**Connections stay in reach of a deployment**). `scripts/prod_drift.py`
  reports it as `BINDING`.
- **The second connection of one connector.** Observed on one recipe, at each of its
  deployments: a recipe that binds two connections of the same connector has a second slot in
  its `config` (`<provider>_secondary`), and that slot arrived empty in Prod although both
  connections belong to the recipe's own project. Read the bindings of such a recipe after every
  deployment.
- **Tags.** They travel only when the deployment includes them ("Include tags" in the UI,
  `include_tags` in the API; documented, see `docs/knowledge/workato/platform-notes-tags.md`).
  The call above does not include them. Tags in Prod are set as a separate step
  (`workato-assets`) when the request covers it.

## After

Restore what the deployment dropped: a property value, a binding, a credential. The workspace's
notes file lists the standing cases of each project. With a read-only Prod API client a person
makes these changes in the Workato UI.

**The first deployment of a project.** Before it, the registry has no `prod` half for the
project, so the next commands would skip it: without a project argument
`scripts/sync_recipes.py prod` passes over it, and named, it says "the registry has no prod ids
for this project, skipped". A person runs `scripts/init_workspace.py` again, with the same
arguments as the first time (it adds the Prod ids and sets `"snapshots": true`; it also rewrites
the harness files, which is why a person runs it):

```bash
scripts/init_workspace.py <workspace> --dev-profile <dev-profile> --prod-profile <prod-profile>
```

Add any `--pair` or `--slug` of the first run. Then the commands below copy the project like any
other.

Refresh the Prod copy and read what actually changed:

```bash
scripts/sync_recipes.py prod
git diff --stat workato/workspaces/<workspace>/projects/
```

The diff of each project's `index.json` shows the `running` state of every recipe: a recipe that
ran before the deployment and is stopped after it is a finding to report, and starting it again
needs the request to say so. A binding the deployment emptied shows in the `config` of the
recipe's JSON.

Commit it with the doc changes of the same task. If the deployment brought a recipe that is new
to Prod, refresh the Dev copies first and then write its `prod_recipe_id` into its doc:

```bash
scripts/sync_recipes.py dev
scripts/link_prod_ids.py
```

A connection's `success` status does not prove that it works (observed:
`docs/knowledge/workato/recipe-builder-traps.md`). Before a recipe that uses a new or
re-authorized connection is started, say which run would prove the connection and ask for it
(**No jobs on your own**).

If the team keeps pages about its recipes in Confluence, update every published page that states
something the deployment changed: the page of each changed recipe, and the project's main page
where it describes them, from the Prod recipes (`confluence-recipe-pages`). That is part of the
deployment, not a separate request. Report the pages and what changed.

## This workspace

If `workato/workspaces/<workspace>/notes/workato-prod-deploy.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

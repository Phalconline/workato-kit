# Why the rules exist

One section per named rule of [AGENTS.md](../../AGENTS.md), in the same order and under the same
name. Each gives the platform fact or the engineering reason behind the rule and, where it helps,
what goes wrong without it. The rules themselves stay in `AGENTS.md`; this page only explains
them.

A statement about Workato or `wk` says where it comes from: "documented" with the page,
"observed" for behavior seen in practice (most of it is collected in
[recipe-builder-traps.md](../knowledge/workato/recipe-builder-traps.md)), or "not verified".

A workspace records its own decisions, and the reasons for the rules it adds to the last section
of `AGENTS.md`, in [decisions.md](decisions.md).

## Writing to Workato

### Change only what was asked.

An agent acts with the Workato privileges of the person it works for. An edit to a Dev recipe
that the task names is the change the person asked for, so it needs no second confirmation. The
other writes are of another kind:

- A start makes a recipe act on real events.
- A stop strands the recipes that call it (see **A running recipe is locked**).
- A deletion removes something other recipes may depend on.
- A write in Prod changes live automation.

These need the request to say so in words. Their effects reach outside the repository and are
not undone by reverting a file: jobs that ran, events that were missed, callers that failed. So
the person decides each one when they ask for it, and nothing written once covers later cases. A
discussion explores options; acting on one before the person chose it is a change nobody asked
for. Saying what changed in the same message keeps the person's picture of Workato true.

### Prod changes only by deployment.

Workato deploys a project only from the Development environment, and a deployment overwrites the
Prod recipe logic with Dev's (documented:
<https://docs.workato.com/features/environments/deployment.html>). A direct edit of a Prod recipe
is therefore lost at the next deployment of that recipe, unless someone ports it to Dev first. It
also bypasses the deployment record (the project's Deployments tab and the activity audit log,
documented on the same page), so nobody can later tell why Prod differs from Dev.
`scripts/prod_drift.py` and the Prod copy in the repository exist to find such a difference
before a deployment overwrites it.

### No package commands.

`wk pull`, `wk diff` and `wk clone` use Workato's package export. In the source of `wk` 1.1.0 each
of them creates an export manifest (`POST /export_manifests`) on every run, and nothing in `wk`
deletes it. The API has a call to delete a manifest by id but none to list manifests, so a
manifest that was not recorded at creation cannot be found later. Workato's documentation does
not say whether manifests are visible in the UI or capped; the rule rests only on the fact that
they pile up. A later `wk` could clean up after itself; the rule holds until that is verified.

`wk push` imports a whole package into a folder. That bypasses the **Push procedure**, which
changes one recipe at a time and verifies each.

The kit reads recipes with `wk recipes pull <id>` and `scripts/sync_recipes.py`, which make one
plain `GET /recipes/<id>` per recipe. A deny rule in a harness's permissions does not catch every
spelling of a command (`wk -p acme-dev pull`, or `wk` called by its full path; Claude Code
documents this limit of its rules: <https://code.claude.com/docs/en/permissions>), which is why
`scripts/guard_wk.py`
runs as a hook in the harnesses that support one. The hook guards against mistakes; it is not a
security boundary: a command hidden in a variable, in `eval` or in another interpreter passes it.

### Push procedure.

- **A fresh base.** A push saves the whole recipe as you hold it. Anything saved since your pull,
  by a person in the UI or by another session, is overwritten.
- **Compare right before the push.** The same race, closed at the last moment: if the remote
  recipe changed, your base is stale.
- **Not while a person edits it in the UI.** Two writers to one recipe overwrite each other's
  work.
- **Verify the saved recipe.** Observed: the recipe builder does not always save what it
  accepted, and it can reset a toggle or a picklist on its own. The raw JSON is the source to
  trust: the MCP server's rendering of a pulled recipe is lossy (observed: pill arrays, call
  labels, step comments).
- **Lint.** `scripts/lint_recipes.py` finds what Workato accepts but a job gets wrong: a pill on a
  property that does not exist, a hardcoded value, an unfinished or skipped step.

### One writer.

A harness may run a subagent in the background. A chat message relayed to it can redirect it in
the middle of a write, out of the person's sight. Writing from the main conversation keeps every
write where the person sees it. One recipe at a time keeps each push and its verification
together, so a failed verification points at one change.

### Check the project first.

A name or a prefix is a convention, not a fact about where a recipe is: a recipe can be copied or
moved into another project and keep its name, prefix included. The project decides which lint
runs, where the doc lives and which Prod copy the recipe is compared with.

### A running recipe is locked.

Observed: Workato refuses every change to a running recipe, the description included; only a
tag can be added without a stop. So an edit of a running recipe is a stop, the edit, a check and
a start. A stop is not a pause:

- Observed: a call to a stopped recipe function, sync or async, does not run and does not queue:
  the caller's job fails at that step (`WRF00409`).
- Documented: a polling trigger parks its cursor where it stands, and a webhook trigger may lose
  the events that arrive while it is stopped
  ([platform-notes-queueing.md](../knowledge/workato/platform-notes-queueing.md), "Triggers
  across a stop").
- Not verified: a schedule skips the runs that fall in the stop.

Starting callees before callers means no caller's first call hits a stopped function.

### No jobs on your own.

A job acts on the systems its connections reach, and a Dev connection can reach a live system. A
repeated job repeats every side effect of the first one. Every successful action counts as a
task, which Workato bills (documented: the tasks page, see
[platform-notes-error-handling.md](../knowledge/workato/platform-notes-error-handling.md)).
Reading the raw JSON proves most of what a test run would prove, without those effects; when a
run is needed, the person decides.

### Nothing destructive in silence.

Recipes call one another and share connections, lookup tables, data tables and properties.
Removing one of them breaks what depends on it, and the break shows only when a job of the
dependent recipe runs. A deployment does not delete either: an asset removed in Dev stays in Prod
until someone removes it there (documented:
<https://docs.workato.com/features/environments/deployment.html>). Naming what is destroyed
before it happens lets the person stop it.

### Connections stay in reach of a deployment.

`shared_connections` is a mark of the kit's registry, not a Workato setting: it names the
project that holds the connections several projects use. Observed: a deployment maps a recipe's
connection to its Prod counterpart when the connection belongs to the recipe's own project or to
that project, and leaves the Prod slot of any other connection empty. Such a recipe stays unable
to reach the app until a person binds it in Prod. `scripts/prod_drift.py` reports such a binding
as `BINDING`. A connection of another project can also disappear with that project.

### Secrets.

- `wk auth token` and `wk mcp auth-header` print the API token. Whatever a shell command prints,
  or writes through a pipe, a substitution or a redirect, can end up in the agent's transcript.
  `scripts/wk_api.py` and `scripts/lib/wkrepo.py` read the token inside their own process and
  never print it.
- `wk --verbose` writes a debug log. Not verified: whether that log shows the request headers,
  the token among them. The rule treats it as if it did.
- The token is sent only to the host `wk` holds for the profile, and only when that is the plain
  https address of a Workato host (below `workato.com` or `workatoapp.cn`). A redirect is never
  followed, because a redirected request would carry the `Authorization` header to the new host.
  No file of the repository can therefore point a token somewhere else.
- A secret typed by an agent has passed through the chat. A person enters credentials in the
  Workato UI, in `wk auth login`, or in `profiles.env`. The shared permissions of Claude Code deny
  reading `profiles.env`, so an agent does not see the tokens stored there.
- Workato's API returns project property values as plain key and value pairs, and its
  documentation describes no masking of secret values (documented:
  <https://docs.workato.com/workato-api/project-properties.html>). Reading one to reuse it copies
  a secret into a transcript; that is why `scripts/wk_api.py` refuses a request for every
  property at once.

### Comments and descriptions belong to people.

People write step comments and descriptions in their own words; an agent that rewrites one makes
them recover that wording. `scripts/prod_drift.py` reports a changed comment (`COMMENT`) so that
a deployment does not overwrite one by accident. A stale comment is pointed out in chat, and the
person decides.

### A description describes.

Everyone who opens a recipe reads its description, and a deployment carries it to Prod. A test
note, a release to-do or a run-state note such as "Not run yet" is true for a short time and then
misleads. Observed: a running recipe's description cannot be changed without a stop, so a stale
note stays until the next one. Notes of that kind belong in a runbook or the backlog.

A description or a comment that compares the recipe with an older version, or with the system it
replaced ("as the old export did"), describes something the reader cannot see, and it is wrong
the day that system is gone. Generated recipes are where such comparisons slip in, a comment
inside a code step included. The comparison is history: it belongs in the repository docs.
`lint_prose_patterns` in the registry lets `scripts/lint_recipes.py` find the words a workspace
does not want in that text (`PROSE_PATTERN`).

### A recipe has a Jobs view.

Without custom columns every row of a recipe's Jobs tab looks the same, so finding the job of one
order or one customer means opening job after job. Documented: a job report can be created or
changed only while the recipe is stopped, and a change shows only on jobs created after it
(<https://docs.workato.com/recipes/jobs.html>). A report added later therefore costs a stop and
is missing on every earlier job; built with the recipe it costs nothing. Columns go stale the way
comments do: a column that reads a step that was removed stays blank and raises no error. That
is why the report is reviewed after every edit, and why a project can switch on the lint check
`JOB_VIEW`. The columns are chosen per recipe because a template fills the tab with columns that
say nothing about the job at hand.

### Sensitive data stays out of job history.

Workato keeps the input and the output of every step of a job, for 30 or 90 days by plan
(documented: <https://docs.workato.com/security/data-protection/data-retention.html>), and
everyone with access to job history reads them. A password or a token there works for each of
those readers. Data masking is set per step and hides that step's input and output (documented:
<https://docs.workato.com/features/data-masking.html>); the documentation does not say that a
later, unmasked step hides a value it received, so every step a credential passes through is
masked.

A mask covers the job log and the audit log, not what a step sends out. Not verified: whether the
`message` of a caught error quotes the request it answers. Some APIs echo the request in an error
body, so the rule treats a `catch` message posted to a chat channel as able to carry the
credential that a masked step protected. That is why the rule also says where a credential must
never go.

Personal data of people outside the organization is masked by default because nobody chose to
show it: it arrives with a form or a webhook and stays readable unless someone decides otherwise.
The rule does not forbid keeping it readable. Masking a trigger hides what started each job and
takes its fields out of the Jobs tab columns, which can cost more than it protects. It asks for
the reason in the recipe doc, so that the choice is made once and can be read later.

Everything else stays readable, because job history is what a failed job is debugged with. A mask
a person set is kept: it records a decision the agent does not know the reason for.
`scripts/lint_recipes.py` finds a step that carries a credential by name and is not masked
(`UNMASKED_CREDENTIAL`); it reads names only, so it finds candidates, not proof.

## Repository

### Generated files are never edited by hand.

The next run of the generating script overwrites a hand edit, and `make check` runs
`scripts/sync_harness.py --check`, which fails on a harness file that differs from its source.
The Prod copy in `projects/` is the reference for what Prod holds: a hand edit there would later
read as a change in Prod. `inventory/doc-sync.json` records the comparisons that were made; an
edit by hand would claim one that was not. `scripts/build_index.py` keeps the callers (`called_by`) that earlier
runs gathered, and every key it does not write itself, from the current index, so the index is
also its own input: deleting it loses them. The two vendor skills are pinned copies under
Apache-2.0, which requires a modified file to carry a notice of the change; the update procedure
in `docs/setup/skills.md` replaces them as a whole.

### No secrets and no table data in the repository.

Git keeps every version of every file it was given. A secret committed once stays in the history
and has to be revoked, not deleted. Rows of lookup tables and data tables change in Workato, so a
copy goes stale, and they can hold data about people. `scripts/sync_lookup_tables.py` therefore
reads the definition of each table and never its rows, and `scripts/check_secrets.py` fails on a
token-shaped string. A connection name points to the credential without being one.

### Real people stay out.

Job titles and error texts can hold personal data, such as the e-mail address of a customer or a
user. The repository is shared and its history permanent, so personal data copied in reaches
everyone who clones it. `scripts/prod_jobs_report.py` replaces each e-mail address with `<user>`
before it writes anything; other personal data is redacted by the person or agent who quotes it.

Docs give dates of runs and never run counts because a count goes stale the next time the recipe
runs, and it claims a precision that a sampled or filtered job list does not have. A date of a
run stays true.

### Keep the Prod copy true.

The Prod copy is how a direct Prod edit is found. After a sync, `git diff` shows what changed in
Prod since the last one; set against the deployments of the same period, a change that no
deployment explains is a direct edit. A deployment overwrites Prod recipe logic with Dev's, so
such an edit must be ported to Dev first or dropped on purpose; otherwise it is lost without
anyone deciding. A difference only in `running`, `version` or a connection's `authorized` flag is
state, not an edit. A difference found by `scripts/sync_recipes.py prod --check` means the copy is
stale; only the diff tells whether Prod was edited.

### Kit files hold no workspace data.

The kit is public, and a repository built from it is private. A file the kit owns can travel back
to the kit with a contribution, and everything in it then becomes public. Each file has one owner,
the kit or the workspace, so that an update of the kit rarely conflicts (a generated file can;
`docs/setup/updating.md` says what to do); workspace data in a kit file would conflict at every
update of that file.

`scripts/check_kit_files.py` runs in `make check` in the kit and in every workspace repository.
It finds what has a recognizable shape: ids, addresses, hosts, bracket codes, ticket keys, dates,
and the names the registry holds (profiles, workspace names, company domains, the maintainer,
project names of two or more words). A one-word name, a recipe's name or a connection's name has
no such shape and is not in the registry, so the check cannot know it. That is why a person reads
a change to a kit file before it leaves the repository.

## Documentation

### Never invent recipe behavior.

A doc is read as fact, by people and by agents in later sessions. A guess written as fact spreads
into every answer built on it. `verified` in the frontmatter tells the reader how far to trust
the text.

### One doc per recipe

Two docs of one recipe drift apart, and nobody knows which one is right. The recipe index
(`scripts/build_index.py`) keys docs by recipe id. A doc carries the **Dev** id because every
change is made in Dev; `scripts/link_prod_ids.py` adds the Prod id. A doc sits under the project
its recipe is in, so that a project's docs are in one folder next to its slug in the registry.

### A recipe doc has no step numbers

Step numbers change whenever a step is added or removed above, and nothing updates a doc when
they do. The recipe JSON also counts from 0 where the UI counts from 1. A bare id of a called
recipe says nothing to a reader and differs between Dev and Prod; a name, the call type and the
fields passed say what the call does. A provenance line repeats what `verified` and
`last_reviewed` in the frontmatter hold.

A rule that only a reader enforces erodes: step numbers come back with the next doc written from
a step tree. `scripts/check_step_numbers.py` runs in `make check` and finds the word "step" with
a number, and a numbered list that does not count from 1 in a row, the shape of an outline
numbered by step. A recipe name that carries such a number is not a finding. A datapill alias
with a number is left to people, because a column name such as `col_1` looks the same.

### A decommission proposal states the blast radius

A recipe function that is stopped or removed fails every caller at the call step, and the
failure shows only when a caller runs. Naming the callers first lets the reader weigh the risk
before the recommendation.

### Sync the docs around a recipe.

A doc is only as true as its last comparison with Workato, and nothing tells a reader when that
was: a recipe changes in the UI, and its doc is not told. A change planned from a stale doc is
planned against a recipe that no longer exists. The docs around a recipe matter as much as its
own, because what it calls, what calls it and what shares a table with it is where a change
breaks something.

`scripts/doc_sync.py` makes staleness visible. A stamp keeps the `updated_at` Workato showed when
the doc was compared, so a later change in Workato shows as stale without anyone remembering it.
A connection keeps its name; a table has no marker the script reads, so for those the age of the
stamp is the only signal, which is why a stamp older than 24 hours counts as stale. The limit of
15 assets keeps a widely shared connection or table from turning one edit into a review of the
whole workspace: beyond it a person chooses.

A stamp without a comparison makes the next reader trust a doc nobody read, which is worse than
no stamp. That is why only what was really compared is stamped, and why `stamp` is not among the
commands a harness may run without asking.

## Working cache

### Reserved file names.

A harness loads a file named `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` as instructions for the
folder it sits in, whatever the file holds, and some file systems ignore letter case. A saved
file under such a name, a note, an export or a download, becomes instructions for every session
that works in that folder, text copied from elsewhere included. A full copy of the repository
inside the tree brings its own `AGENTS.md` along, so it goes outside.

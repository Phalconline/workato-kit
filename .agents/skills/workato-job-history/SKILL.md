---
name: workato-job-history
description: Read and analyze Workato job history and logs. Use when asked when a recipe last ran, who calls a recipe, why a job failed, what happened in Prod over a period, or who stopped, started or edited something. Covers the sources of job data, the caller seen in job titles, redaction of personal data and what may be quoted in docs.
---

# Job history and logs

Every source below only reads. A `wk` command names the profile of the environment you ask
about: `environments.dev.profile` or `environments.prod.profile` of the registry (for example
`acme-dev`, `acme-prod`). Recipe ids differ per environment: take the Prod id from the Prod copy's
`index.json` or from `prod_recipe_id` in the recipe doc.

## Sources

**The Workato MCP server: `job_list` and `job_get`.** They need no browser session. The server
acts in the environment it was authorized for, which is Dev in this repository, so it shows Dev
jobs. Observed for recipes called through the callable-recipes trigger: their job titles carry
the caller as `Calling recipe ID=<n>`, which makes job history an empirical index of who calls
such a recipe. Not verified for recipe functions.

**`wk` per recipe**, in either environment:

```bash
wk -p <prod-profile> recipes jobs <recipe id> --status failed --limit 20 -j
wk -p <prod-profile> recipes jobs get <recipe id> <job id> -j
```

The second command returns one job with its step traces.

**A window of Prod:**

```bash
scripts/prod_jobs_report.py --since <ISO 8601 time>
```

`<ISO 8601 time>` has the form `2030-01-31T08:00:00Z`. The script reads with the Prod profile of
the registry: the jobs of every recipe in the window, the failing step of each failed job and the
audit log (starts, stops, edits, connection changes). `--until` ends the window (default: now);
without `--since` the window is the 24 hours before it. It replaces e-mail addresses in titles
and errors with `<user>` and writes one JSON file into `tmp/wk/prod-jobs/` (`--out` takes only a
file under `tmp/`). Each job keeps the `calling_recipe_id` and `root_recipe_id` fields of the
API's job list, empty when Workato does not fill them. A recipe whose jobs could not be read is
listed under `errors` and the run goes on.

**The audit log** answers who stopped, started or edited something:

```bash
wk -p <prod-profile> workspace audit-log --since <ISO 8601 time> -j
scripts/wk_api.py prod GET /activity_logs
```

Observed: a recipe's `updated_at` does not date a start or a stop
(`docs/knowledge/workato/recipe-builder-traps.md`).

**The web app's job endpoint**, `<app_url>/web_api/recipes/<recipe id>/jobs` in a browser that is
signed in to Workato. Observed: it gives the `calling_recipe_id` and `root_recipe_id` fields and
the `error` body of each job. It belongs to the web app, is not part of the public API and can
change without notice. `app_url` is in the registry.

## Reading a job

- A job can end as `succeeded` although a step inside a Handle errors block failed and the
  on-error branch ran (not stated in Workato's documentation:
  `docs/knowledge/workato/platform-notes-error-handling.md`, "Final job status"). When the
  question is whether something really happened, read the step outputs of the job (`job_get`,
  `wk recipes jobs get`), not only its status.
- Not verified: in a job list of the MCP server, `job_count` is the lifetime count and
  `job_scope_count` the count of the filtered window.

## What may be written down

- Job titles and error texts can contain personal data, such as the e-mail address of a
  customer or a user. Never copy it into a tracked file; write `<user>` when you quote an error
  (**Real people stay out**). `scripts/prod_jobs_report.py` replaces e-mail addresses only: a
  name or another identifier in a title is yours to redact.
- Docs give dates of runs, never run counts: quote neither `job_count` nor `job_scope_count`.
- Raw job dumps and your working notes go to `tmp/`, for example
  `tmp/analysis/<YYYY-MM-DD>-<topic>/`. Only the conclusion goes into `docs/`, redacted.

## Before a ticket

When the workspace switched the Atlassian server on, load `triage-issue` before you propose or
file a ticket for a failure: it searches for one that already covers it. Add what you found to
that ticket instead of opening a second one.

## Do not

- Do not repeat a job (`wk recipes jobs retry`) and do not start a recipe to produce one, unless a
  person asked for that run (**No jobs on your own**). If a run would prove something, say what it
  would prove and ask.

## This workspace

If `workato/workspaces/<workspace>/notes/workato-job-history.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

# The Jobs view of a recipe

Every recipe has a **job report**: custom columns on its Jobs tab that tell one job from another
and show how it ended. Without them every row of the tab looks the same, and finding the job of
one order or one customer means opening job after job. This page is the convention behind the
rule **A recipe has a Jobs view** of [AGENTS.md](../../AGENTS.md).

The columns are **chosen for that recipe alone**. There is no shared template: two recipes share
a column only when it is the most useful one for both.

## What Workato fixes

Documented: <https://docs.workato.com/recipes/jobs.html>.

| Topic | Fact |
|---|---|
| Columns | up to ten custom columns, next to the ones Workato always shows |
| Values | datapills of the trigger or of any step, mixed with text; at most 256 characters per value and 5 KB per report |
| Data masking | a datapill of a step with data masking cannot be used: masking covers the whole step, so the editor blocks all its datapills |
| When | the recipe must be stopped to create or change the report, and a change shows only on jobs created after it |
| Where in the UI | the Jobs tab, the ellipsis in the header row of the table, then "Customize job report" |

Observed, in the raw recipe JSON:

- The report is two keys of the trigger block. `job_report_schema` is the list of columns, each
  with a `name` (`custom_column_1`, `custom_column_2`, ...) and a `label`. `job_report_config`
  maps each column name to its value.
- A value is text with datapills in the form
  `#{_('data.<provider>.<step as>.<path.joined.with.dots>')}`, where `<step as>` is the `as` of
  the step in the recipe JSON (the trigger has one too).
- The report is part of the recipe code: a deployment carries it to Prod, and
  `scripts/prod_drift.py` reports a report that differs as a difference in the code.
- A column that reads a step the job did not reach stays blank.

Not verified: whether a column that reads a variable shows the value the variable had at the end
of the job, and which formulas a column value may hold. Check a new column on the first jobs, and
replace one that stays blank where it should not by the output of a step.

## Choosing the columns

Ask what a person would search for, or need to see, in **this** recipe's list of jobs:

- **The thing the job is about**, in the form people search for it: the order number, the
  customer account, the event type of a webhook, the key of a ticket.
- **How it ended**, when a step exposes it on most paths: the outcome a function returns, the
  message of an error handler, a count of what a scheduled run did. Workato already shows whether
  the job succeeded or failed.
- Nothing long, no whole objects, no secrets, nothing from a step with data masking
  ([data-masking.md](data-masking.md)), and no personal data beyond what tells the jobs apart.
- Labels are short words in title case. Use as few columns as tell the jobs apart, usually three
  to five.

For example, `[SO] LF | Create invoice` shows `Order` (the `order_id` it was called with),
`Account` and `Invoice` (the number the ERP returned):

```json
"job_report_schema": [
  {"name": "custom_column_1", "label": "Order"},
  {"name": "custom_column_2", "label": "Account"},
  {"name": "custom_column_3", "label": "Invoice"}
],
"job_report_config": {
  "custom_column_1": "#{_('data.workato_recipe_function.execute_0f1e.parameters.order_id')}",
  "custom_column_2": "#{_('data.workato_recipe_function.execute_0f1e.parameters.account_id')}",
  "custom_column_3": "#{_('data.erp.create_invoice_1a2b.number')}"
}
```

## When it is done

- **A new recipe** gets its job report in the same push as its steps. The recipe is stopped
  then, so nothing extra has to be stopped.
- **After every edit** the report is reviewed: a step that was renamed, removed or moved out of
  the main path, a new key input or a new outcome means the columns change in the same task.
- **The recipe doc** lists the columns in its Configuration section, as "Jobs tab columns".
- The columns reach Prod with the next deployment of the recipe. Jobs created before it keep the
  old columns.

Building the report through the UI is a person's step. In the raw JSON it is the two keys above,
uploaded with the rest of the recipe (`workato-recipe-edit`).

## What the lint checks

A project that lists `JOB_VIEW` under `lint_checks` in the registry
([registry.md](registry.md)) gets three findings from `scripts/lint_recipes.py`:

| Finding | Level | Meaning |
|---|---|---|
| `JOB_VIEW_MISSING` | warning | the recipe has no job report |
| `JOB_VIEW_STALE` | error | a column reads a step that is no longer in the recipe |
| `JOB_VIEW_MASKED` | error | a column reads a step with data masking, which Workato blocks |

Switch the check on once the recipes of the project have their reports; until then every recipe
would warn. The lint cannot tell whether a column is useful: that stays a person's review.

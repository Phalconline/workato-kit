# Recipe doc template

One doc per recipe, at `docs/<project-slug>/recipes/<dev_recipe_id>-<kebab-name>.md`, under the
Workato project the recipe sits in. Copy the template below, fill it from the recipe's JSON or
from the Workato UI, and delete the sections that do not apply. The skill `recipe-docs` has the
procedure; the rules **Never invent recipe behavior**, **One doc per recipe** and **A recipe doc
has no step numbers** in [AGENTS.md](../../AGENTS.md) apply.

## Template

```markdown
---
recipe_id:
prod_recipe_id:
name:
status:            # Active | Inactive
verified:          # unverified | read-from-json | read-in-ui
severity:          # Critical | High | Medium | Low
owner:
path:
last_job:
last_reviewed:
verdict:           # optional: Keep | Merge | Rewrite | Investigate | Decommission
---

# <name>

## Purpose
One paragraph: what the recipe achieves for the business, not the list of its steps.

## Trigger
What starts it: a schedule, a webhook, a polling trigger, an API endpoint, or a call from another
recipe. For a recipe function, list its inputs instead, under the heading Inputs.

## Called by
The recipes that call it, each as a link with the call type (sync or async).

## Calls
The recipes it calls, each as a link, with the call type and the fields it passes.

## Result
What it changes in which system, and what it returns to a caller.

## Configuration
Connections, project properties, lookup tables and data tables it reads.

## Known limitations
What it does not handle, and how that shows.
```

Optional sections, only where they carry something:

| Section | When |
|---|---|
| `## How it works` | a part of the logic that the sections above cannot explain in a sentence, such as a branch map or a field mapping. Describe what happens, never where in the recipe |
| `## Findings` | a numbered list of problems found while reading the recipe. `scripts/build_index.py` counts its items for the recipe index |
| `## Cleanup assessment` | keep, merge, rewrite or decommission, with the reason; the outcome also goes into `verdict` in the frontmatter. A decommission proposal names the callers (the blast radius) before the recommendation |

## Frontmatter

| Field | What it holds | Who fills it |
|---|---|---|
| `recipe_id` | the recipe's **Dev** id; the file name starts with it | you |
| `prod_recipe_id` | the id of its Prod copy; absent while the recipe is not in Prod | `scripts/link_prod_ids.py` |
| `name` | the recipe's name in Workato, quoted when it holds a `|` | you |
| `status` | `Active` when the recipe runs, `Inactive` when it is stopped | you |
| `verified` | where the description comes from: `read-from-json`, `read-in-ui`, or `unverified` when it was not read from either. An unverified doc says in the text what is assumed | you |
| `severity` | how much breaks when the recipe fails | you |
| `owner` | who answers for the recipe | you |
| `path` | the Workato folder path of the recipe inside its project | you |
| `last_job` | the date of the last job you saw, never a count of jobs | you, optional |
| `last_reviewed` | the date of this review | you |
| `verdict` | the outcome of a cleanup assessment: `Keep`, `Merge`, `Rewrite`, `Investigate` or `Decommission`. The recipe index sorts by it | you, optional |

`scripts/build_index.py` reads `recipe_id` (or, without it, the number the file name starts
with), `name`, `path`, `severity`, `owner`, `last_job` and `verdict` from the frontmatter into
the recipe index. The `name` of the doc wins over the name in the Dev recipe JSON.

An entry of the recipe index (`inventory/recipes-index.json` of the workspace) holds `recipe_id`,
`name`, `url`, `doc`, `project`, `path`, `severity`, `owner`, `trigger_type`, `step_count`,
`connectors`, `calls`, `called_by`, `tables`, `properties`, `last_job`, `findings_count`
and `verdict`. The script fills the others from the registry, the doc, the Dev recipe JSON and
the current index, and carries over untouched a key it does not write itself.

## What a doc never holds

- A Workato step number. Step numbers change when a step is added or removed above, and the JSON
  counts from 0 where the UI counts from 1.
- A bare id of a called recipe. Write its name as a link, the call type and the fields passed.
- A provenance line such as "documented from the JSON on 2030-01-31". Where the description comes
  from is `verified` and `last_reviewed` in the frontmatter.
- An e-mail address of a real user (write `<user>`), a run count, or a link into `tmp/`.

## Example

A recipe function of the invented workspace in [registry.md](registry.md), at
`docs/sales-orders/recipes/3002-so-lf-create-invoice.md`:

```markdown
---
recipe_id: 3002
prod_recipe_id: 4002
name: "[SO] LF | Create invoice"
status: Active
verified: read-from-json
severity: High
owner: the maintainer
path: "[SO] Functions"
last_job: 2030-01-31
last_reviewed: 2030-01-31
---

# [SO] LF | Create invoice

## Purpose
Creates the invoice of a confirmed order in the ERP, so that billing starts the day the order
is confirmed.

## Inputs
- `order_id`: the order in the ERP.
- `account_id`: the customer account the invoice is for.

## Called by
- [[SO] REC | New order](https://app.workato.com/recipes/3001), sync call, passes `order_id`
  and `account_id`.

## Calls
None.

## Result
One invoice in the ERP. It returns the invoice number to the caller.

## Configuration
- Connection `[SO] ERP`.
- Project property `protected_accounts`: an order of a listed account gets no invoice.
- Project property `orders_channel`: where a failure is posted, through `[CM] Slack`.

## Known limitations
An order with no line items fails the job; the caller's job shows the ERP's error text.
```

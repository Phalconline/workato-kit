# Conventions

| File | What it is |
|---|---|
| [registry.md](registry.md) | every key of the workspace's `registry.json` and `harness.json`, and which script reads it |
| [recipe-doc-template.md](recipe-doc-template.md) | the template of a recipe doc, with an example |
| [job-view.md](job-view.md) | the job report of a recipe: the columns of its Jobs tab, chosen per recipe |
| [data-masking.md](data-masking.md) | which steps are masked in job history: credentials, and personal data of people outside the organization |
| [python.md](python.md) | how the scripts and their tests are written: layout, style, linter, type checker |
| [rationale.md](rationale.md) | why each rule of `AGENTS.md` exists |
| [decisions.md](decisions.md) | the workspace's own decision log; it starts empty |

The rules themselves are in [AGENTS.md](../../AGENTS.md). The procedures are the skills in
`.agents/skills/`. Everything in this folder belongs to the kit except `decisions.md`, which
belongs to the workspace.

## Naming in Workato

Documented: Workato publishes naming patterns for projects, folders, recipes and connections at
<https://docs.workato.com/recipes/naming-conventions.html>. Not verified: the patterns below were
not re-read on the live page for this version of the kit. The scripts do not depend on them.

| Asset | Workato's pattern | Example of the kit |
|---|---|---|
| project | `[DEPARTMENT_CODE] [PROJECT_CODE] Name` | the examples use plain names: `Sales Orders`, `Common` |
| folder | `[PROJECT_CODE] Name` | `[SO] Functions`, `[CM] Connections` |
| recipe | `PROJECT_CODE ASSET_CODE \| Name`, with an optional sequence number. The asset codes are `REC` (a recipe), `GF` (a recipe function reused across projects), `LF` (a recipe function inside one project) and `API` (an API trigger) | `[SO] REC \| New order`, `[SO] LF \| Create invoice` |
| connection | `APP_NAME (USERNAME)`, with no environment in the name | `[CM] Slack`, `[SO] ERP` |

A project code is two to five capital letters.

The examples of the kit differ from Workato's patterns in two places, by choice: they put the
project code of a recipe in brackets, and they give a connection the bracket code of the project
that holds it (`[CM] Slack`). A workspace follows Workato's patterns, the kit's examples or its
own; it records the choice in [decisions.md](decisions.md).

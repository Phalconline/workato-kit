# Platform notes: error handling

How the "Handle errors" block (the error monitor) behaves, and what that means for building
recipes. Each fact names its source: a page of the Workato documentation, or "observed" for
something seen in practice in one workspace.

## The monitor block

| Topic | Fact | Source |
|---|---|---|
| Control flow | The block is not a terminator. When no error occurs, the recipe runs the monitored steps and goes on with the step after the block. The on-error branch holds steps that let the workflow continue; stopping the job is an optional step you add inside it. | documented: best practices for error handling |
| Retry scope | A retry runs the **whole monitored block** again, not only the step that failed. The documentation's example: a failure in the second step of a three-step block retries all three. Every action placed before the failing step inside the block runs again. | documented: best practices for error handling |
| Retry settings | Retry is off by default: the on-error branch runs at once. At most 3 retries, an interval of 1 to 10 seconds, and an optional "Retry IF" condition. | documented: best practices for error handling |
| Which errors retry | There is no built-in list of retryable errors. Every action failure is retried. To retry only some, write the "Retry IF" condition on the error datapills (`error_type`, `error_message`, `http_response` and the like). | documented: best practices for error handling |
| Cost | The block itself is a free control statement. Every successful action counts as a task, so a retry bills again the actions that had already succeeded in the block, and the steps of the on-error branch are ordinary tasks. | documented: tasks page, worked examples |
| API recipes | In an API recipe a timeout of the API request ends the job, and the monitor block never runs. | documented: best practices for error handling |
| Final job status | Not stated. The documentation defines a failed job as one that ended because of an error, and makes "failed" or "successful" a setting of the Stop job step. Both suggest that a job whose on-error branch ran without a Stop job step ends as successful, but no page says so. | not verified |

Pages: `docs.workato.com/en/recipes/best-practices-error-handling.html`, the job statuses on
`recipes/jobs.html`, the Stop job step on `recipes/steps.html`, and the examples on
`recipes/tasks.html`.

**Observed:** the error-handling reference that the Workato MCP server returns from `docs_get`
can disagree with the documentation site on the block names and on retry intervals. Where the
two differ, follow `docs.workato.com`.

## What this means for a recipe

- **Monitor after an irreversible side effect, fail fast before one.** A retry inside the job
  helps when an earlier step did something that a re-run of the whole job would repeat or change,
  such as sending a message or creating a record with a new value. Steps before any side effect
  (reads, lookups, formulas) gain nothing from a monitor: let them fail. The job is red, nothing
  happened, and a repeat of the job is clean.
- **Keep each monitored block narrow**: one side-effecting action per block. A retry replays every
  action before the failing step inside the block.
- **Put retries only on errors that can pass.** A rate limit or a timeout can pass; a validation
  error or a missing record cannot. Write the "Retry IF" condition, or every failure is retried
  and each retry bills the block again.
- **Decide the job status yourself.** An on-error branch that only logs leaves the job looking
  successful (see "Final job status" above). End the branch with a Stop job step set to "failed"
  when the failure must be seen in the job history and by a job-failure monitor.
- **An error text is not always the API's code.** A connector can turn an API error into words.
  A condition written against the raw code then never matches. Read the text of a real failed job
  before you branch on it ([recipe-builder-traps.md](recipe-builder-traps.md)).

## Editing a monitor block

- **Observed:** the recipe builder can accept a step added inside the on-error branch and lose it
  at the push: the recipe pulled again shows an empty branch. After an edit inside an on-error
  branch, read the saved recipe again (`recipe_get`, or the raw JSON with `wk recipes pull <id>`)
  instead of trusting the push result.
- More traps of the builder are in [recipe-builder-traps.md](recipe-builder-traps.md).

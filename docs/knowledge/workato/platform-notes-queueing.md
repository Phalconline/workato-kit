# Platform notes: queueing, scheduling and concurrency

What the platform offers for ordering work, holding it for later and keeping two jobs apart, and
where each building block stops. Read this before you design a queue, a deferred action or a
recipe that must not run twice at once. Each fact names its source: a page of the Workato
documentation, "observed" for something seen in practice, or "not verified".

## Concurrency 1 is not a lock

- **A long action releases the next job.** When an action is put on hold, Workato no longer keeps
  the job sequence: the next job starts although the previous one has not finished, even at
  recipe concurrency 1. Source: documented, `recipes/long-actions.html`.
- **Data table writes are long actions.** The long-actions page lists the Create, Update and
  Upsert record actions of Workato Data Tables (the search and batch actions are not listed). A
  recipe that writes to a data table therefore cannot rely on concurrency 1 to keep its jobs
  apart. Source: documented, `recipes/long-actions.html`.
- **Concurrency is a setting of one recipe**, not of a table or a resource. A second recipe that
  touches the same records runs next to the first one whatever both are set to.
- **A wait inside a job overlaps the job with the next one**, for the same reason. To defer work,
  store it with a due time and pick it up later; do not sleep inside the job.

Consequence: the correctness of a recipe must not depend on the order of its jobs or on one job
finishing before the next starts. Make each job idempotent, and decide from the current state of
the target system at processing time rather than from the order in which events arrived.

## No atomic claim

There is no conditional update, no compare-and-swap, no lease and no ETag in the data table
connector.

| Building block | Fact | Source |
|---|---|---|
| Update record | addresses one record by its Record ID; there is no "update where" | documented: data tables connector |
| Delete | the only write that takes a condition is delete by condition | documented: data tables connector |
| Upsert | matches on a column used as the key; atomicity is not documented, and since no column can be unique (next row), two concurrent upserts on the same key can both insert | documented, and the conclusion drawn from it |
| Unique columns | a user-defined column cannot be marked unique; the only unique value is the Record ID, which Workato generates on insert and which cannot be set | documented: create column dialog, column types; observed in the API schema of a table (column name, type, required, field id) |
| Column type | cannot be changed after the column is created | documented: edit column |

So a "claim" is always a search followed by an update by id: an unguarded read-then-write. Two
consumers both see the row and both claim it. A queue in a data table is safe only with one
consumer recipe, idempotent handlers, and no reliance on job order.

## Data tables and lookup tables

| | Data tables | Lookup tables |
|---|---|---|
| Search | filters joined by AND only (no OR, in recipes and in the API), sort field and direction, page size 100 by default and at most 1 thousand, with a next-page token | "Search entries" has no ordering and no result cap; "Lookup entry" returns the first entry that matches |
| Comparison | dates: on or before, on or after; numbers: greater or less than or equal | exact match |
| REST query API | `$eq $ne $gte $gt $lte $lt $in $starts_with $and`, `select`, `order`, `limit`; order by `$record_id`, `$created_at`, `$updated_at` | none documented |
| Trigger | real-time "New record" and "New/updated record" triggers; no delivery delay is promised | none |
| Size | 100 tables per workspace, 1 million rows, 100 columns, 100 KB per record, 1 GB per table; batch actions take at most 1 thousand rows; only 10 thousand rows can be exported or deployed | 100 thousand rows, 10 columns; "Get all entries" returns only the first 10 thousand |
| Text | 10 thousand characters per text column; sorting and filtering use only the first 756 | |

Sources: documented, the data tables pages (connector actions, query API, limits, column types)
and the lookup tables pages. The lookup tables documentation itself says they are not a
relational database solution.

Consequences:

- A query such as "status is pending AND due time is on or before now, oldest first" is
  expressible in a data table, so a table can hold deferred work for one consumer.
- A lookup table cannot serve as a queue: "the oldest due items" cannot be asked for.
- A real-time data table trigger usually fires soon after an insert, but its delay is not
  documented. The general note that real-time triggers fall back to slower polling applies.
  Design for "usually prompt, sometimes late".
- **A row that waits produces no job.** No job means no failed job, so a monitor that watches
  failed jobs never sees work that is stuck in a table. A table-backed queue needs its own
  watcher that looks for rows that are overdue.

## Event Streams

Event Streams is the platform's message queue (older Pub/Sub documentation addresses now lead to
the Event Streams pages). Source: documented, Event Streams connector pages, unless marked
otherwise.

- **Delivery** is described as guaranteed and persistent. The documentation uses no
  at-least-once or exactly-once wording.
- **Order**: messages are ordered by the time they were published. Delivery in sequence is
  described for a consumer at concurrency 1; behavior at higher concurrency is not documented.
- **Fan-out**: several recipes can consume one topic, and each gets every message, with its own
  cursor. Consumers do not compete for messages.
- **Stop and start**: a stopped consumer resumes from the last processed message when started
  again, but only within the retention period. Stopped for longer than the retention, it no
  longer picks up new messages. Whether that is permanent (and needs a copy of the recipe) is
  not verified.
- **Retention**: 168 hours by default, configurable, at most 90 days.
- **Not offered**: delayed delivery, visibility timeout, dead-letter queue, redrive and a lag
  metric. Publishing takes only the message body. Message history is a tab in the UI that needs
  its own permission.
- **Limits**: 20 topics per workspace, 10 MB per message, a batch trigger of 1 to 100 messages
  polled at most every five minutes.

Consequence: a queue in Workato does not have to be serial, but Event Streams cannot hold work
for later, and a consumer that stays stopped past the retention stops receiving without an
error.

## Triggers across a stop

Source: documented, `recipes/triggers.html`, the start and stop page and `recipes/jobs.html`.

- **A polling trigger keeps a durable cursor.** Started again, it picks up the events of the stop
  window in chronological order.
- **A webhook (real-time) trigger may miss the events** that arrive while the recipe is stopped.
- **Workato keeps the trigger event of a job**, so a failed job can be repeated from the job
  history with the original input. A queue of your own loses that unless it stores the raw event.
- **Pending jobs fail** after a recipe has been stopped for 30 days.
- **A recipe stops itself** after 60 consecutive errors while fetching trigger events.

## Batch and scheduled triggers

Source: documented on the scheduled batch trigger of a connector, and in the general trigger
pages. Check the page of the trigger you use.

- **A batch trigger gives one job per batch**, not one per event: 420 events in batches of 100
  become 5 jobs. One documented scheduled trigger returns batches of 100 by default and at most
  1 thousand.
- **A scheduled trigger can return events it already returned** in an earlier run. A recipe on
  such a trigger needs an idempotency guard of its own.
- **A trigger condition on a batch trigger looks at the first record only.** If the first record
  matches, the whole batch is processed. Filter in the trigger's own query, or in a step.
- **Not verified**: whether each run of a scheduled trigger starts where the previous run ended,
  or searches again from the "when first started" time.

## Scheduling

Source: documented, the Scheduler connector and the trigger pages.

- **Scheduler "New recurring event"**: the shortest interval is five minutes, and the cron option
  has the same floor.
- **Scheduled times are approximate**: a run can start a little late because of the trigger queue.
  A recipe started after its scheduled time runs at once.
- **Polling intervals depend on the plan**: five minutes on higher plans, ten on the base plan.
- **No queue-drain pattern is documented.** Batch processing in the documentation means one job
  that handles many rows (a batch trigger followed by batch actions). A drain loop is assembled
  from documented parts.
- **Limits that bound a loop**: "Repeat while" repeats its steps at most 50 thousand times, a
  job times out after 90 minutes (an administrator can change it), and a recipe holds at most
  1 thousand steps.

How a schedule behaves when you start a recipe is an observation, not documented: see "A schedule
does not fire when you start the recipe" in [recipe-builder-traps.md](recipe-builder-traps.md).

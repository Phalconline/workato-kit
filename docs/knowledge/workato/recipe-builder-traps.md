# Traps of the recipe builder, `wk` and the API

These are observations from one workspace, not statements of Workato. None of them is in the
Workato documentation as far as we found; what was read in `wk ... --help` says so where it
stands. Behavior changes with versions of the platform, of `wk` and of the MCP server: check a
trap before you rely on it, and tell the kit when one no longer holds.

"The builder" below is the recipe builder of the Workato MCP server (`recipe_builder_*` tools).
"The raw JSON" is the recipe JSON `wk recipes pull <id>` writes, by one GET, or
`scripts/sync_recipes.py dev --recipe <id>` through it. It is wk's project format: the code of
the recipe as Workato stores it, while `private` and `concurrency` are platform defaults there
(`wk recipes pull --help`), not the recipe's own values. When the raw JSON and a rendering
disagree on the code, the raw JSON is right.

Most traps share one lesson: **a successful push proves nothing**. After every push, read the
raw JSON again and compare it with your base: every field that differs must be one you meant to
change. The skill `workato-recipe-edit` makes that part of the procedure.

## Locked and stopped recipes

### A running recipe refuses every change

- **What happens:** Workato rejects a push to a running recipe, and also a change of its
  description alone, with an error such as `can't modify running recipe`. `wk recipes update`
  says the same: the recipe must be stopped. Tags are the exception: a tag can be added to a
  running recipe.
- **How to notice:** check `running` before you plan an edit: `wk recipes get <id> -j`.
- **What to do:** stop, edit, verify, start again, or keep the text change in a file until the
  next planned stop. The MCP server has no start or stop tool: use `wk recipes stop <id>` and
  `wk recipes start <id>`. A stop and a start need the request to say so (rule **A running
  recipe is locked**; skill `workato-start-stop`).

### A call to a stopped recipe function fails the caller

- **What happens:** a call to a stopped recipe function, synchronous or asynchronous, fails the
  **caller's** job at that step: "Can't call a stopped recipe", error type "Recipe function is not
  running" (`WRF00409`). Nothing runs in the callee and nothing waits in a queue.
- **How to notice:** failed jobs of the callers while a function is stopped.
- **What to do:** say before a stop which callers will fail. Start callees before callers. In a
  recipe that makes several asynchronous calls in a row, a stopped callee ends the job at that
  call after the earlier calls already ran, so a repeat of the job runs those earlier calls again.

### "Respond to API request" ends the job

- **What happens:** in an API platform recipe, the steps after "Respond to API request" do not
  run. An early answer (400, 401, 422) ends the job.
- **What to do:** do not add a Stop job step after an early response, and do not report its
  absence as a bug.

## What the renderings hide

### The builder pull is not the stored recipe

- **What happens:** `recipe_builder_pull` renders the recipe as a DSL that loses information:
  - an array field that holds a datapill shows as `[{}]`;
  - a recipe-function call can show the stale name of its target (for example the name of a copy)
    while the stored id points elsewhere;
  - step comments can be missing from the pull;
  - the channel of a Workbot "Post message" step can show as one stale name on every such step,
    although the steps store different channels;
  - unset fields show their schema default (for example a limit), as if they were set.
  A skipped step does show, as a `# skip=True` line above the step.
- **How to notice:** a finding that rests on the pull alone, such as "malformed request body" or
  "this calls a copy".
- **What to do:** confirm with `recipe_builder_show`, `recipe_get` or the raw JSON before you call
  something a bug. Read an existing step comment from the raw JSON before you edit near it, so
  nothing is overwritten unseen. Never push a session whose pull showed stale values in fields
  you did not mean to change: the push writes them back.

### A pull replaces your edits

- **What happens:** `recipe_builder_pull` replaces the local session, including edits you have not
  pushed.
- **What to do:** never pull an edited session and push without applying the edits again.

### A push changes things you did not touch

- **What happens:** a builder push re-serializes the steps it touches. It drops the `uuid` of each
  condition, can turn a missing `skip` into `skip: false`, and rewrites every datapill in its own
  form. None of this changes the logic.
- **What to do:** compare old and new steps with the datapill JSON normalized, and ignore these
  three differences. Anything else that differs is a finding.

### Recipe lists collapse line breaks in descriptions

- **What happens:** `recipe_list` and the text of `recipe_get` show a line break in a description
  as two spaces. A description rebuilt from that text loses its paragraphs and lists.
- **What to do:** read the description from the raw JSON (field `description`), keep every `\n`,
  and after the update count the line breaks in a fresh pull. A harness that asks for approval may
  show a line break as `[U+000A]`; in Workato it is an ordinary line break.

## Fields the builder writes wrong

### A datapill in a picklist field becomes a broken string

- **What happens:** a picklist field (schema `control_type: select`, usually with
  `pick_list_name`) set to a datapill or formula without switching it to its free-text control is
  stored as a literal Ruby interpolation, such as `"/orders/#{_dp('{...}')}/lines"`. The push
  reports success, and the pull and `recipe_get` render it exactly like a correct value. The job
  then fails at runtime (for example with `bad URI`).
- **How to notice:** read the field schema with `recipe_builder_get_input_schema` before you set
  it. A correctly switched field comes back as `control_type: text`, with the label of the
  free-text control.
- **What to do:** pass `toggle_config` with the value: `False` selects the secondary control,
  `True` the primary one. Which of the two is the free text differs per connector and per field,
  so read the schema of a working sibling step and set the new step until its schema matches.
  When you do want the picklist, pass the option id, never its display title. If a person says a
  step looks wrong in the UI, believe the UI: it renders the stored value.

### The builder can ignore `toggle_config`

- **What happens:** replacing a literal with a datapill in a toggle field can store the toggle as
  `false` while working steps store `true`, with and without `toggle_config`. It happens on the
  `channel` field of the Workbot "Post message" action.
- **What to do:** after every push that touches a toggle field, compare the raw `toggleCfg` of the
  step with a working sibling. To fix it, set the value and `toggleCfg` in the raw JSON and upload
  it with `wk recipes update <id> <file>` (below).

### A code field with a datapill cannot be edited in the builder

- **What happens:** a field of control type `code` (for example a SOQL query) accepts only plain
  text in the builder. Datapill mode is refused, and so is plain text that contains the stored
  datapill syntax `#{_dp(...)}`. Datapills already in the field survive moves and renumbering of
  other steps.
- **What to do:** push everything else with the builder. Then pull the raw JSON, replace the text
  in the field and keep each `#{_dp('...')}` part byte for byte, and upload with
  `wk recipes update <id> <file>`. The recipe must be stopped. Pull again and compare. Say in the
  report that the field was written with `wk recipes update`.

### A whole object as a value keeps its datapills as text

- **What happens:** `recipe_builder_set_input_field` with a whole object as the value (for example
  the input of a code step with its schema and data) stores the inner strings as literal text,
  even in f-string form. An object with only a schema can even store the whole input as a string
  and break the step's schema refresh; removing and adding the step again repairs it.
- **What to do:** set the schema first, then each subfield by its own dot path
  (`code_input.data.<field>`). A list mapping works as one list comprehension string on the dot
  path. A raw JSON body works as an f-string with doubled braces (`f"{{\"k\": \"{pill}\"}}"`),
  which is stored with single braces.

### Typed controls refuse formula mode

- **What happens:** integer and date-time controls (for example parameters of a data table
  action) accept only datapill or literal mode from the builder, although recipes built in the UI
  hold formulas in such fields.
- **What to do:** compute a number in a string variable and pass that variable as a datapill;
  Workato casts it. For "now" in a date-time field, use a time datapill of the trigger instead of
  a formula.

### Literals in conditions

- **What happens:** the right-hand side of `recipe_builder_set_condition` and of the error-handling
  configuration is a literal unless it parses as a datapill. A quoted `"429"` keeps its quotes, and
  `"True"` becomes the string "True".
- **What to do:** write numbers bare (`429`) and test a boolean with the unary `is_true` or
  `is_not_true`.

### Order of calls when a field depends on another

- `declare_variable` shows its `value` field only after `type` is set: two calls.
- A field can depend on another (an item cannot be set before its parent); the input schema shows
  the order.
- A list whose items have different keys: set the list with the shared key first, then set the
  other key by path (`list.0.<key>`) in the same call.

## Variables

### Update variables does nothing against a scalar variable

- **What happens:** a variable created in the scalar form (`name`, `type`, `value`) and changed by
  an "Update variables" step is not changed. The update's output shows an empty value, the readers
  see the old value, and no error appears anywhere. A list that collects failures stays empty, so
  a check on it never fires.
- **How to notice:** the output of the Update step in a real job does not name the variable.
- **What to do:** declare a variable that is ever updated in the `variables` form
  (`variables.schema`, a default in `variables.data.<var>`); the Update step's `name` is then
  `<uuid>:<as>:<var>`, which the builder's picklist offers once the declaration is in that form,
  and readers use the path `[<var>]`. To convert an existing step: remove `name`, `type` and
  `value`, set `variables.schema` as a JSON string in plain-text mode, then set each Update step
  and each reader again. A variable that is never updated may stay scalar.
- **Also:** one Update step may change several variables only when they come from the same
  declaration. References to two declarations pass the builder and fail the start check with
  "Variable referred is undeclared in input field"; use one Update step per declaration.

### An object variable needs the `variables` form

- A new `declare_variable` step offers only `name` and `type`, which hold scalars. Set both and
  remove them again; the input schema then offers `variables.schema` (a JSON string, plain-text
  mode; objects and arrays without `control_type`; each field with a `parent` path). Values go by
  dot path (`variables.data.<var>.<a>.<b>`), and readers use `declare_variable_N['<var>'][...]`.

## Formulas

### The builder's formula check is stricter than the runtime, and looser

- **Refused by the builder:** `.size` ("Function 'size' is not supported"); use the list-size
  datapill instead. `.presence`; use `x.present? ? x : fallback`. String interpolation inside
  `ruby()`; concatenate with `+`.
- **Accepted:** `.pluck`, `.join`, `.include?`, `.split`, `.first`, `.last`, `.gsub` with a regular
  expression, `.downcase`, `.to_s`, `.present?`, `a ? b : c`, `+`. "Two or more records" without a
  count: `list.pluck('Id').join(',').include?(',')`.
- **Accepted by the builder, refused when the recipe starts:** a leading `!` in an IF condition
  fails with `Lhs expression is unsafe`; write `== false`, or `x.present? ? ... : true` instead of
  `(x || [])`. A JSON-body array field that holds a datapill as a one-item list fails with
  "must be an array of static expressions"; set the whole field as the formula `=[pill.to_s]`.
- **What to do:** prefer forms that run in recipes you already have. For a gate, two `include?`
  conditions joined by the IF's own `and` with `is_not_true` are safer than one formula with `!`
  or `&&`. A raw JSON body is a `=` formula with `content_type: application/json`; quote strings
  with `.to_s.to_json` and write `null` out.
- A formula field can take bindings: `ruby("expr with bindings.x", bindings={"x": step['pill']})`.

### Start errors use another step number

- `wk recipes start` reports an activation error as `step N` with the step number of the JSON,
  where the trigger is 0. The UI counts the trigger as 1: add 1.
- The DSL names steps `<action>_<UI number>` (`foreach_31`, `catch_37`), not by the `as` ids of
  the raw JSON. A datapill path element `current_item` renders as `[0]`.

## Properties and schemas

### Renaming a project property breaks its datapills silently

- **What happens:** a datapill keeps the property name it was made with. After a rename, case-only
  renames included, every such datapill reads blank at runtime, with no builder error.
- **How to notice:** `scripts/lint_recipes.py` reports `PROPERTY_MISSING` for a datapill on a
  property that does not exist.
- **What to do:** after a rename, run the lint on every project and point each stale datapill at
  the new name. If a called function no longer declares a parameter, remove the call parameter.

### A caller keeps the old parameter schema of a function

- **What happens:** after new parameters are added to a recipe function, the builder session of a
  caller still refuses the new fields.
- **What to do:** push the function first, then pull the caller again, read the call step's input
  schema, and map the new fields.

### A mapper step needs a common data model

- A Mapper step needs a common data model (`workato_schema_id`), and such a model can only be
  created in the Workato UI. A model is shared by every mapper that uses it. If all its fields are
  required, a new field makes every other mapper on it report a missing field (a conclusion, not
  verified).

## Recipes from raw JSON

### Uploading and importing

- `wk recipes update <id> <file>` replaces a recipe's code and configuration (`PUT
  /api/recipes/:id`); the recipe must be stopped (`wk recipes update --help`). Workato may rewrite
  a call step's description label to the real name of the callee, and regenerates the
  description label of a trigger.
- A file from `wk recipes pull` holds platform defaults for `private` and `concurrency`. Before
  you upload it with `wk recipes update`, set those two keys to the values
  `wk recipes get <id> -j` shows. Not verified: what the upload does with them.
- A whole recipe can be composed from steps of sibling recipes and created with
  `wk recipes import <file> --folder <id>`: give each copied step a new `uuid` and an `as` of the
  form `<name>_<first 4 hex characters of the uuid>`, point the datapills at the new `as`, and
  number the steps depth-first. The recipe lands stopped, with the connections of its `config`
  bound. Run `wk lint` on the file before the import and `scripts/lint_recipes.py` after it.

## Schedules and test copies

### A schedule does not fire when you start the recipe

- **What happens:** a scheduler trigger with a months, weeks or days interval waits for its
  `trigger_at` time after a start. A minutes or hours interval fires at once, but only on the
  first start; a restart waits for the next slot. An hours interval without `trigger_at` is
  refused at start with "Trigger at can't be blank".
- **What to do:** for a one-off run of a daily recipe, keep the days interval and set `trigger_at`
  a few minutes ahead, in the recipe's time zone, in the raw JSON; upload, start, and restore the
  saved JSON afterwards. Run a recipe only when a person asked for that run (rule **No jobs on
  your own**).

### Swapping the trigger of a copy

- `recipe_builder_update_step` on the trigger step with the scheduler connector replaces the
  trigger; adding a second trigger is refused. The old trigger condition stays, with a datapill
  that no longer resolves: clear it with `recipe_builder_set_condition` and an empty list.
- A replayed payload is not a replay of the world: an API read in the copy returns the current
  state of the record, not its state when the original event happened.

### Repeating a job

- `wk recipes jobs retry <recipe-id> <job-id>` repeats jobs with the latest recipe version (read
  in `wk recipes jobs --help`; not tried). The job page in the UI has "Repeat this job", which
  also uses the latest version. The MCP server cannot repeat a job. A repeat gets a new job id.
- Repeat a job only when a person asked for it (rule **No jobs on your own**).

## Connections

### "Success" does not prove that a connection works

- **What happens:** the status `success` (`authorization_status: success`) does not prove a
  working connection. A connection can report it while the UI says the connection is no longer
  valid, and a connection with a misconfigured authentication type can still report it while
  every call fails. The API does not show which authentication type a connection uses.
- **What to do:** before a start or a release, prove each bound connection with a real call: a
  job, an API read through it, or a person checking its page in the UI. Name every connection that
  could not be proven before anything starts.
- **Also:** a changed credential may leave the connection's `updated_at` and the activity audit
  log untouched. An unchanged audit trail does not prove that a credential is the old one.

### Salesforce: a new connection can invalidate an old one

- **What happens:** Salesforce keeps a limited number of approvals per user for one connected
  app, and a further approval revokes the oldest (not verified here: the number is five).
  Authorizing one more Workato connection as the same Salesforce user can therefore invalidate an
  older one, also one in another project or environment.
- **What to do:** share one Salesforce connection through the project marked
  `shared_connections` instead of one per project. Count the connections of the user before you
  authorize another, and read the status of every Salesforce connection afterwards.

### Workbot "Post message" errors are words

- **What happens:** a Workbot for Slack "Post message" (`post_bot_message`) to a channel the bot
  cannot see fails with the text `Channel not found`, not Slack's code `channel_not_found`. For a
  private channel, "the bot is not a member" and "the id is wrong" give the same error. A
  condition written against Slack's codes never matches.
- **What to do:** branch on the text of a real failed job. Not verified: the text for a public
  channel the bot has not joined.

### Google Sheets with a spreadsheet id from a datapill

- The action needs `sheet_name` and `column_headers` (the exact header order of the sheet), not
  the `sheet` picklist.

## History and audit

### `updated_at` does not date a start or a stop

- A recipe's `updated_at` does not change when it is started or stopped. Who started, stopped or
  edited a recipe or a connection is in the activity audit log, with a `stop_reason` on a stop.
- Read the log through the API, with the Dev or the Prod profile, for example:

  ```bash
  scripts/wk_api.py dev GET /activity_logs -q from=2030-01-31T00:00:00Z -q to=2030-02-01T00:00:00Z
  ```

  Filters are `include_event_types[]` and `include_resource_types[]`; the page size is
  `page[size]`, and `page[after]=<last id>` gives the next page. `scripts/prod_jobs_report.py`
  collects the Prod audit events of a time window together with the jobs.
- The audit page in the browser follows the environment the person's session is in, so it can
  show Prod only. Do not switch a person's environment to read it.
- The versions of a recipe (author and time, no code): `GET /recipes/<id>/versions`.

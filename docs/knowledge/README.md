# Platform knowledge

Notes on how the Workato platform, the `wk` CLI and the Workato MCP server behave: things that
cost time to find out and that the next person should not have to find out again. One file per
topic. Every fact says how it is known:

- **documented**: read on a page of the Workato documentation; the page is named next to it;
- **observed**: seen in practice, in one workspace, and not found in the documentation. An
  observation can be specific to a connector, a plan or a version. Check it before you design
  around it.
- **not verified**: an open question. Do not rely on it.

A fact read in `wk ... --help` names that command instead.

| File | Topic |
|---|---|
| [workato/platform-notes-error-handling.md](workato/platform-notes-error-handling.md) | the error monitor block: control flow, retries, cost, job status |
| [workato/platform-notes-queueing.md](workato/platform-notes-queueing.md) | concurrency, long actions, data tables, lookup tables, Event Streams, schedules |
| [workato/platform-notes-tags.md](workato/platform-notes-tags.md) | tags: limits, scope, deployment, permissions and how to read and write them |
| [workato/recipe-builder-traps.md](workato/recipe-builder-traps.md) | traps of the recipe builder, `wk` and the API that the documentation does not mention |

The rules that follow from these notes are in [AGENTS.md](../../AGENTS.md) and in the skills.
This folder holds the background that explains them.

## Notes of your workspace

The kit owns `docs/knowledge/workato/` and this README, and replaces them when you merge a kit
update. Keep the notes of your own workspace in `docs/knowledge/workspace/`, with their own index
there instead of rows in the table above: the kit never writes there, and
`scripts/check_kit_files.py` does not check it, so a note there may name your projects, recipes
and connections.

A platform fact that holds for every workspace belongs in the kit. Propose it there (see
[CONTRIBUTING.md](../../CONTRIBUTING.md)), written without anything of your workspace.

## Adding a note

- Write the behavior and how it is known (a job, a documentation page, `--help`, a test), not
  the story of how you found it.
- Platform behavior changes, so a note must be possible to check again. In
  `docs/knowledge/workspace/`, add the date. A note for the kit names the `wk` version or the
  documentation page instead: `scripts/check_kit_files.py` reports a date before 2030 in a file
  of the kit.
- Say what to do about it: the working pattern, not only the trap.
- No personal data such as e-mail addresses, no secrets, no table data.
- A rule that every agent must follow belongs in `AGENTS.md` or in a skill, not here.

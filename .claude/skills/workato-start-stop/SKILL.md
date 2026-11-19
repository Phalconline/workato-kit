---
name: workato-start-stop
description: Stop or start a Workato recipe correctly. Use before any wk recipes stop or wk recipes start, and whenever an edit needs a running recipe to be stopped first. Covers what a stop does to callers, triggers and schedules, the start order, and what to say in the same message.
---

# Stop and start a recipe

Stop or start a recipe only when the request says so in words (rule **Change only what was
asked** of `AGENTS.md`). If an edit you were asked to make needs a stop first, say what the stop
does (below) and ask, unless the request already covers it. In Prod the same holds for every
write.

## Why a stop is needed

Workato refuses every change to a running recipe, the description included. Only a tag can be
added without a stop (observed: `docs/knowledge/workato/recipe-builder-traps.md`). So check
`running` first:

```bash
wk -p <dev-profile> recipes get <id> -j
```

`<dev-profile>` is `environments.dev.profile` of the registry, for example `acme-dev`; for Prod
use `environments.prod.profile`. An edit to a running recipe is: stop, edit, verify, start again.
The exception is a recipe that is meant to stay stopped; the workspace's rules or notes say which
recipes those are. Say which case it is in your message.

## What a stop does

A stop halts automation and never acts on an event. But it strands callers rather than just
pausing work, so state the consequences in the same message as the stop:

- A call to a stopped recipe function, sync or async, does not run and does not queue. The
  caller's job fails at that step with `WRF00409` (observed:
  `docs/knowledge/workato/recipe-builder-traps.md`).
- A polling trigger parks its cursor where it stands, and picks up the events of the stop window
  when started again (documented: `docs/knowledge/workato/platform-notes-queueing.md`, "Triggers
  across a stop").
- A webhook trigger may lose the events of the stop window (documented, same page).
- A scheduled recipe skips the runs that fall while it is stopped (not verified).

## Starting

Starting is the opposite direction: the recipe begins acting on real events.

- Start callees before callers.
- Name the recipe, and say in the same message that it was started and what it now acts on.
- Never start a recipe only to produce a test job, unless a person asked for that run (rule
  **No jobs on your own**).
- Before a start, check that no other running recipe would process the same events: two recipes
  that handle one event both act on it. If the workspace keeps a recipe stopped on purpose, its
  rule is in the last section of `AGENTS.md`, "Rules of this workspace".

## Commands

```bash
wk -p <dev-profile> recipes stop <id>
```

```bash
wk -p <dev-profile> recipes start <id>
```

`wk recipes start` waits until the recipe is active (`wk recipes start --help`). Read `running`
again afterwards with `wk recipes get`. Use `<prod-profile>` only for a stop or a start in Prod
that the request names; if the Prod API client is read-only, a person does it in the Workato UI.
The Workato MCP server has no start or stop tool. Run both commands from the main conversation,
never from a subagent (rule **One writer**).

## This workspace

If `workato/workspaces/<workspace>/notes/workato-start-stop.md` exists, read it before you act: it
holds what this workspace adds to this procedure.

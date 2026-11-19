---
name: environment-preflight
description: Prove which Workato environment the wk profiles and the Workato MCP server are really connected to. Use at the first Workato write of a session, after signing in to or re-authorizing the MCP server or a wk profile, and when CLI and MCP answers disagree. Not needed before each edit of a recipe whose project id you have just read.
---

# Check the environment before the first write

The registry, `workato/workspaces/<workspace>/registry.json`, names the two environments. For each
one it holds the `wk` profile (`environments.dev.profile`, `environments.prod.profile`), the name
of the Workato workspace that profile must reach (`environments.<env>.workspace`), and the
project ids (`projects.<slug>.dev.project_id`, `projects.<slug>.prod.project_id`). A profile
name, a recipe name or a name prefix proves nothing about the environment.

## The CLI

The profile of an environment is `environments.<env>.profile`; `WK_PROFILE_DEV` and
`WK_PROFILE_PROD` override it for the scripts. Below, `<dev-profile>` and `<prod-profile>` stand
for the two names, for example `acme-dev` and `acme-prod`.

```bash
wk auth list --json
```

It lists each profile with its base URL, its environment (`dev` or `prod`), its workspace and
its credential store (`store_type`), and prints no token. Observed: a profile of the file store
(`profiles.env`) is found only with `--store-type file`. The scripts add that flag themselves; a
`wk` command you type for such a profile needs it too:

```bash
wk -p <dev-profile> --store-type file recipes get <id> -j
```

That form asks for approval in Claude Code: the shared allow rules cover the form
`wk -p <profile> <command>` only. A person who wants it allowed adds the rule to their own
`.claude/settings.local.json`. The commands below take the flag the same way for such a profile.

```bash
wk -p <dev-profile> auth status
```

It must show the workspace the registry names for Dev (observed: it also prints
`API: connected`). Run it with `<prod-profile>` before a write in Prod. `scripts/doctor.py` runs
the same check for both profiles, fails when wk holds a profile as signed in to the other
environment, and checks that each API client may read what the scripts read; it changes nothing
in Workato.

## The MCP server

The Workato MCP server acts in the environment that was active in the browser when it was
authorized; a CLI profile says nothing about it. Call `project_list` and compare the project ids
with the registry: Dev ids mean Dev.

## The asset

Read the recipe or the connection by its id and confirm that its project id is the one the
registry gives for that project and environment. Use `recipe_get`, or the CLI:

```bash
wk -p <dev-profile> recipes get <id> -j
```

## On a mismatch

Stop. Say what you saw and from which tool, and ask the person to sign in again from the right
environment. Never switch a profile (`wk auth switch`) or authorize another environment yourself.
Check again after a new sign-in or a profile override.

This check grants no permission: rule **Change only what was asked** of `AGENTS.md` still
decides what may be written.

## This workspace

If `workato/workspaces/<workspace>/notes/environment-preflight.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

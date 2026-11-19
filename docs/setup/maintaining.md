# Maintaining a workspace repository

Short procedures for the life of a workspace repository after
[new-workspace.md](new-workspace.md). Updates of the kit itself are in [updating.md](updating.md).

The examples use the workspace `acme` and the profiles `acme-dev` and `acme-prod`; a re-run of
`scripts/init_workspace.py` needs only these three:

```bash
scripts/init_workspace.py acme --dev-profile acme-dev --prod-profile acme-prod
```

It reads Workato and changes nothing there. What it does on a re-run is in
[new-workspace.md](new-workspace.md#create-the-workspace-folder). A step in the Workato UI is
done by a person whose Workato role allows it, never by an agent on its own.

## A new project later

1. Create the project in Dev in Workato.
2. A workspace admin adds the project to the project list of the Dev API client. A client that
   cannot see a project leaves it out of the registry. Not verified: the menu path; Workato's
   page on API clients is <https://docs.workato.com/en/workato-api/api-clients.html>.
3. Run `scripts/init_workspace.py` again (above). It prints `registered: <slug>` and lists the
   project under `In Dev only.`
4. Copy the project's Dev recipes into your cache and lint them. Without a project argument
   both scripts cover the managed projects only, so name it:

   ```bash
   scripts/sync_recipes.py dev <slug>
   ```

   ```bash
   scripts/lint_recipes.py <slug>
   ```

5. Commit the registry:

   ```bash
   git add workato/workspaces/acme/registry.json
   ```

   ```bash
   git commit -m "Register the project <slug>"
   ```

## The first deployment of a project

Until its first deployment a project is in Dev only: the registry has no Prod ids for it, so it
has no Prod copy and nothing to compare with Prod. The deployment itself follows the
`workato-prod-deploy` skill, when a person asks for it. After it:

1. A workspace admin checks that the Prod API client lists the new Prod project, and adds it
   when it does not. Not verified: whether a deployment that creates a project in Prod adds it
   to the Prod client's project list.
2. Run `scripts/init_workspace.py` again (above). It prints `now also in Prod (snapshots
   switched on): <slug>`. If the Prod project is listed under `In Prod only, not registered:`
   instead, its name differs from the Dev one: run it again with `--pair DEV_ID=PROD_ID`.
3. Take the Prod copy, refresh the Dev copy and link the recipe docs to their Prod ids:

   ```bash
   scripts/sync_recipes.py prod
   ```

   ```bash
   scripts/sync_recipes.py dev
   ```

   ```bash
   scripts/link_prod_ids.py
   ```

4. Commit the registry, the new `workato/workspaces/acme/projects/<slug>/` and the changed docs.

From now on the project is a managed project: `scripts/sync_recipes.py prod` and
`scripts/lint_recipes.py` cover it without a project argument.

## A project renamed in Workato

Run `scripts/init_workspace.py` again (above). It finds the project by its Dev project id,
updates `name` in the registry and keeps the slug:

```text
  renamed in Workato, slug kept: sales-orders: now '<new name>' in Workato
```

Commit the registry. The slug, the folders named by it and every link stay as they are.

## Renaming a slug

The slug names the registry entry and three folders, so a new slug is a change by hand. A slug is
lower-case Latin words and digits joined by dashes, unique, and not `setup`, `conventions`,
`knowledge` or `kit`. Here `<old-slug>` becomes `<new-slug>`:

1. Rename the key of the project in `workato/workspaces/acme/registry.json`. Its settings move
   with it.
2. Move the docs (if the project has any) and the Prod copy:

   ```bash
   git mv docs/<old-slug> docs/<new-slug>
   ```

   ```bash
   git mv workato/workspaces/acme/projects/<old-slug> workato/workspaces/acme/projects/<new-slug>
   ```

3. Delete your Dev cache of the project; the next Dev sync rebuilds it under the new name:

   ```bash
   rm -rf tmp/wk/dev/<old-slug>
   ```

4. Find what still names the old slug, such as links, notes files and the last section of
   `AGENTS.md`, and change it:

   ```bash
   git grep -n "<old-slug>"
   ```

5. Refresh the copies, rebuild the index and check the links:

   ```bash
   scripts/sync_recipes.py prod
   ```

   ```bash
   scripts/sync_recipes.py dev
   ```

   ```bash
   scripts/build_index.py
   ```

   ```bash
   scripts/check_links.py
   ```

6. Run `make check` and commit everything in one commit.

For a Dev-only project, skip the Prod copy in step 2 and the Prod sync in step 5, and name the
project in the Dev sync: `scripts/sync_recipes.py dev <new-slug>`.

## A project deleted in Workato

`scripts/init_workspace.py` reports a registered project that Workato no longer lists for the
Dev profile, and removes nothing:

```text
Registered, but Workato does not list it for the Dev profile any more (deleted, or the API client lost access). Nothing was removed; see docs/setup/maintaining.md:
  <slug> (Dev project 1005)
```

First rule out lost access: a workspace admin checks that the Dev API client still lists the
project. If the project is gone:

1. Remove its entry from `workato/workspaces/acme/registry.json`.
2. For a managed project, remove its Prod copy:

   ```bash
   git rm -r workato/workspaces/acme/projects/<slug>
   ```

3. Decide about `docs/<slug>/`. Keep it as a record of what the project did, or remove it:

   ```bash
   git rm -r docs/<slug>
   ```

4. Delete your Dev cache of the project:

   ```bash
   rm -rf tmp/wk/dev/<slug>
   ```

5. Rebuild the index, check the links and the rest, then commit:

   ```bash
   scripts/build_index.py
   ```

   ```bash
   scripts/check_links.py
   ```

   ```bash
   make check
   ```

`scripts/init_workspace.py` compares the Dev project list only. A project deleted only in Prod is
not reported there. Not verified: the message of `scripts/sync_recipes.py prod` when a registered
Prod project is gone; its exit status is 2 when Workato cannot be read, and the projects after
the failing one stay unchanged.

## A renamed `wk` profile

`wk` has no rename: you sign in under the new name and delete the old profile. The registry names
the two profiles for everyone, and the permissions of Claude Code are written for those names.
Before the change, agree on it with the people who use the repository.

1. Change `environments.dev.profile` or `environments.prod.profile` in
   `workato/workspaces/acme/registry.json`.
2. Regenerate the harness files. This rewrites the permissions of Claude Code, so a person runs
   it or approves the run. It prints the rules it adds and removes:

   ```bash
   scripts/sync_harness.py
   ```

3. Commit the registry and the harness files:

   ```bash
   git add workato/workspaces/acme/registry.json .claude .codex .cursor .gemini .mcp.json \
     .agents/mcp_config.json .agents/generated-files.json
   ```

   ```bash
   git commit -m "Rename the wk profile"
   ```

4. Each person signs in under the new name, makes it the default when it is the Dev profile,
   and deletes the old profile. For a renamed Dev profile, with your region instead of `us`:

   ```bash
   wk auth login --name <new-profile> --environment dev --region us
   ```

   ```bash
   wk auth switch <new-profile>
   ```

   ```bash
   wk auth delete acme-dev
   ```

One person who only wants another name on their own machine changes nothing here: they set
`WK_PROFILE_DEV` or `WK_PROFILE_PROD` in their shell
([README.md](README.md#sign-wk-in-for-dev-and-for-prod)).

## A new maintainer

1. Write the new maintainer into `maintainer` in the registry, by hand or with `--maintainer` on
   a re-run of `scripts/init_workspace.py`. A role or a team is enough.
2. Hand over what the maintainer holds outside the repository: the admin role on the git host,
   and the say over the API clients, which a workspace admin manages in Workato.
3. Commit the registry.

## A person leaving

1. Remove their access to the repository on the git host.
2. Remove their user from the Workato workspace, or lower their role, in the Workato UI. Their
   sign-in to the Workato MCP server acts as their own Workato user. Not verified: whether
   Workato lists a user's MCP authorizations for an admin to revoke one by one.
3. They held the tokens of both API clients, as everyone who signed `wk` in does. A workspace
   admin regenerates both tokens. Documented
   (<https://docs.workato.com/en/workato-api/api-clients.html>): regenerating a token makes the
   old one invalid.
4. Everyone else signs in again with the new tokens, under the same profile names and with
   their region instead of `us`. `wk` asks before it overwrites an existing profile:

   ```bash
   wk auth login --name acme-dev --environment dev --region us
   ```

   ```bash
   wk auth login --name acme-prod --environment prod --region us
   ```

5. If the person can still reach their machine, they delete their profiles, and `profiles.env`
   if they used the file store, and their clone with its `tmp/`, which can hold personal data
   from jobs.

## Stopping use of the kit

The repository holds no running automation: recipes keep running in Workato without it.

1. Each person removes the sign-ins of the project's MCP servers in their harness
   ([harnesses.md](harnesses.md)). Not verified: the command for that in each harness.
2. Each person deletes their two `wk` profiles, and `profiles.env` if they used the file store:

   ```bash
   wk auth delete acme-dev
   ```

   ```bash
   wk auth delete acme-prod
   ```

3. A workspace admin deletes the two API clients in Workato. Not verified: that a deleted
   client's token stops working at once.
4. Archive the repository on the git host, or delete it. An archive keeps the Prod copy, the docs
   and the decisions readable.

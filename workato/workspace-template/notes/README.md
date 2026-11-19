# notes/: what this workspace adds to the skills

The skills of the kit (`.agents/skills/<name>/SKILL.md`) describe procedures that hold for every
workspace. What only this workspace knows goes here, in one Markdown file per skill, named like
the skill: `notes/workato-prod-deploy.md` for the skill `workato-prod-deploy`. Every skill of the
kit points at its notes file (the two vendor skills in their "Local rules" block, the others at
their end); when the file exists, an agent reads it with the skill.

The kit never changes a file in this folder after it was created, so an update of the kit never
conflicts with it. Edit the notes, never the skill.

## Which files the skills read

| File | What it holds |
|---|---|
| `notes/<skill>.md` | for every skill of the kit, such as `workato-prod-deploy.md`, `workato-recipe-edit.md`, `workato-start-stop.md`, `workato-assets.md` or `recipe-docs.md`: what this workspace adds to that procedure |
| `notes/confluence-recipe-pages.md` | for the optional Atlassian integration: the Confluence space, the folder of the recipe pages, and optionally which page belongs to which recipe |
| `notes/triage-issue.md` | for the optional Atlassian integration: the Jira project and the fields a ticket must carry. The skill asks the person when this file does not exist |
| `notes/search-company-knowledge.md` | for the optional Atlassian integration: what this workspace adds to that vendor skill |

## What belongs in a notes file

- the names of the shared connections and the project that holds them, for example `[CM] Slack`
  in the project `Common`;
- the release order of the projects, for example `common` before `sales-orders`;
- the connections to rebind in Prod after a deployment, for example `[SO] ERP`;
- what a project property means, for example that `protected_accounts` lists the accounts
  automation must not touch;
- where the wiki pages of the recipes live, and the fields a ticket must carry.

Use names and pointers. A secret, a token or a row of table data never goes into a notes file.

## What does not belong here

- A rule. A notes file never weakens a rule of `AGENTS.md`: it adds facts and steps to a
  procedure. A rule of this workspace goes into the last section of `AGENTS.md`, "Rules of this
  workspace".
- A setting that a script reads. That goes into `registry.json` or `harness.json`.
- The docs of a project. Those are in `docs/<project-slug>/`.

## Example

`notes/workato-prod-deploy.md` of the workspace `acme` could read:

```markdown
# workato-prod-deploy: notes of this workspace

- Deploy `common` before `sales-orders`: the shared connections live in `Common`.
- After a deployment of `sales-orders`, rebind `[SO] ERP` in Prod to the production account.
- The release checklist is `docs/sales-orders/runbooks/release.md`.
```

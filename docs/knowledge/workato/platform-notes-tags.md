# Platform notes: tags

What Workato fixes about tags, and how to read and write them with the tools of this repository.
How a workspace names and uses its tags is its own decision: write it in
`docs/conventions/decisions.md` or in `docs/knowledge/workspace/`, not here.

**Workato publishes no naming convention for tags.** Its tags page explains what tags are; its
naming-conventions page covers projects, folders, recipes and connections only. The tag names in
Workato's own examples are plain words without a prefix.

## What Workato fixes

| Topic | Fact | Source |
|---|---|---|
| Title | Required, at most 30 characters. No character rules are documented. | tags API |
| Description | Optional, at most 150 characters. | tags API |
| Color | One of 12: blue, violet, green, red, orange, gold, indigo, brown, teal, plum, slate, neutral. Random when none is given. | tags API |
| Count | At most 1 thousand tags per workspace; an asset can carry several tags. | tags page |
| Scope | Workspace-wide: one set of tag names shared by all projects and all environments. An assignment of a tag to an asset belongs to one environment. | tags page, tag assignments API |
| What can be tagged | Recipes, connections, data tables and Workflow app pages. The API assigns tags to recipes and connections only. Lookup tables, folders and projects cannot be tagged. | tags page, activity audit log reference |
| Filters | The Assets page, a project's Assets tab and the Operations hub dashboard filter by tag. The RecipeOps triggers "Job failed" and "Recipe stopped by Workato" can watch recipes by tag (besides all recipes or selected ones; there is no project option). | tags page, RecipeOps docs |
| Deployment | Tags do not travel with an export, an import or a project deployment unless "Include tags" (`include_tags` in the API) is on. | recipe lifecycle management and projects API |
| Deletion | A deleted recipe that is restored gets its tags back. | tags page |
| Permissions | With "Restrict tag management" on, only administrators create tags; otherwise anyone can. Assigning a tag needs edit rights on the asset. | tags page |

Pages:

- Tags: <https://docs.workato.com/recipes/tags.html>
- Naming conventions: <https://docs.workato.com/recipes/naming-conventions.html>
- Tags API (title, description, colors):
  <https://docs.workato.com/workato-api/environment-management.html>
- Tag assignments API: <https://docs.workato.com/workato-api/tag-assignments.html>
- RecipeOps "Job failed": <https://docs.workato.com/connectors/recipeops/triggers/new-failed-job>
- Activity audit log (which assets record tag changes):
  <https://docs.workato.com/workato-api/activity-reference.html>

### Observed

- Square brackets and `/` are accepted in a tag title.
- A tag can be added to a running recipe. Every other change to a running recipe is refused,
  its description included ([recipe-builder-traps.md](recipe-builder-traps.md)).

### Not verified

- Whether `&` is accepted in a tag title.
- Whether tag titles must be unique.
- Whether selecting several tags in a filter matches assets with any of them or with all of them.
- Whether tags show on job pages.

## What this means

- A tag means the same thing in every project, because the names are shared. Before you rename or
  delete a tag, list what carries it in every project and in both environments.
- Tags you assign in Dev are not in Prod after a deployment unless the deployment includes tags.
  Either deploy with "Include tags", or assign the tags in Prod by hand after the deployment.
- A tag is a filter for people and for RecipeOps. Nothing in the repository's scripts reads tags.

## Reading and writing tags

| Task | How |
|---|---|
| List the tags | `wk tags list --json` |
| Create, change, delete a tag | `wk tags create <title> --color <color> --description <text>`, `wk tags update`, `wk tags delete` |
| Put a tag on assets, take it off | `wk tags apply <handle> --to recipe:3001,connection:6001`, `wk tags remove` |
| See which tags a recipe carries | `scripts/wk_api.py dev GET /recipes -q folder_id=<id> -q 'includes[]=tags'` |
| See which tags a connection carries | `scripts/wk_api.py dev GET /connections -q 'includes[]=tags'` |

Creating, changing, deleting and assigning tags are writes to Workato: the rule **Change only
what was asked** applies, and **Nothing destructive in silence** applies to a deletion.

Observed traps:

- **`wk tags apply` reports success for a handle that does not exist.** Read the assignments back
  after every apply.
- **`wk recipes list`, `wk recipes get` and the MCP server do not show the tags of an asset.** Read
  them from the API with `includes[]=tags`, as in the table above. `/recipes` pages with
  `-q per_page=100 -q page=<n>`; `/connections` ignores paging and returns every connection at
  once.
- **The raw `GET /tags` answer wraps the list** in `data.tags`.
- **HTTP 401 on `/tags`** comes when the role of the API client lacks the Tags privilege under
  Admin, Environment management. The Tag assignments privilege under Projects alone is not
  enough. Members and the audit log are separate administrator privileges.
- The same reads work with the Prod profile (`scripts/wk_api.py prod ...`). An HTTP 400 on such a
  read can be transient: retry before you conclude anything.

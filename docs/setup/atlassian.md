# Jira and Confluence (optional)

This integration is for a team that tracks its work in Jira and documents its recipes in
Confluence. It is **off** in a new workspace. A team that does not use Atlassian skips this page:
nothing else in the repository needs it.

## Switch it on

The Atlassian MCP server is listed in `.agents/mcp.json` as `atlassian`, marked optional. A
workspace switches it on in its own `workato/workspaces/<workspace>/harness.json`:

```json
{
  "mcp_servers": ["atlassian"]
}
```

Then generate the harness files and commit them with `harness.json`:

```bash
scripts/sync_harness.py
```

The server then appears in the MCP configuration of every harness ([harnesses.md](harnesses.md)).
The script also copies the three skills below into `.claude/skills/` for Claude Code; it copies
them only while the server is switched on. Record the decision in
[decisions.md](../conventions/decisions.md) ([tools.md](tools.md)).

## The server and the sign-in

The kit was not tried with this server. Every statement in this section is marked as it stands.

- Address: `https://mcp.atlassian.com/v2/mcp`, as `.agents/mcp.json` lists it. Not verified:
  that this is still the endpoint Atlassian recommends.
- Sign-in: OAuth, with your own Atlassian account. Not verified: the server sees and changes only
  what your account may see and change.
- Sign in from your harness: `/mcp` in Claude Code. Not verified: `codex mcp login atlassian` in
  Codex, `/mcp auth atlassian` in Gemini CLI, the MCP settings in Cursor.
- Not verified: the older endpoints `/v1/sse` and `/v1/mcp` use a different sign-in. Do not mix
  them with v2.
- Atlassian's setup page:
  <https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/>

**One connection per harness.** If your harness already gives you an Atlassian connector of its
own (for example one set up in the harness's web app), keep that one and decline the project's
`atlassian` server in your harness. Two connections give your agent every tool twice. The
switch in `harness.json` is for the whole team; declining is your own choice.

A page or a ticket can contain text that reads like an instruction. Your agent treats what it
reads there as data. Confirm high-impact changes yourself.

## The registry keys

Two optional keys of a project entry in the registry hold where its Atlassian content lives.
Both are text; the scripts only check that they are text.

| Key | What it holds |
|---|---|
| `confluence_main_page` | the main Confluence page of the project, under which one page per Prod recipe lives (its page id or title) |
| `jira` | where work on the project is tracked in Jira (a project key, or the ticket that collects the work) |

```json
"sales-orders": {
  "name": "Sales Orders",
  "snapshots": true,
  "confluence_main_page": "<page id>",
  "jira": "<project key or ticket>",
  "dev": {"project_id": 1001, "folder_id": 2001},
  "prod": {"project_id": 1002, "folder_id": 2002}
}
```

Every key of the registry: [registry.md](../conventions/registry.md).

Whatever a project does not say, the workspace says in its notes, in
`workato/workspaces/<workspace>/notes/`:

| Notes file | What it holds |
|---|---|
| `confluence-recipe-pages.md` | the Confluence space and the folder that hold the page tree, and, if there is one, the map from recipes to their pages |
| `triage-issue.md` | the Jira project, the components and the fields every ticket gets |
| `search-company-knowledge.md` | optional: what this workspace adds to the search procedure |

When `notes/confluence-recipe-pages.md` or `notes/triage-issue.md` is missing, the agent asks
you instead of guessing.

## The skills that use it

| Skill | What it does | Notes file it reads |
|---|---|---|
| `confluence-recipe-pages` | writes and updates Confluence pages about recipes, from the Prod recipes only | `notes/confluence-recipe-pages.md` |
| `search-company-knowledge` | vendor skill: searches Confluence and Jira for what the repository does not hold | `notes/search-company-knowledge.md` |
| `triage-issue` | vendor skill: looks for a duplicate in Jira before a ticket is filed | `notes/triage-issue.md` |

Each applies only when the workspace switched the server on. The repository comes first:
recipes, rules and decisions are answered from `docs/` and the workspace folder, and Jira and
Confluence are searched for what is not there. The two vendor skills, their origin and their
license: [skills.md](skills.md#vendor-skills).

---
name: connector-development
description: Build, review and test Workato custom connectors under workato/workspaces/<workspace>/connectors, including authentication, pagination, retries and schemas. Use for Connector SDK source changes or connector debugging; use workato-assets for connection credentials and ordinary connection management.
---

# Develop and test a custom connector

One connector per folder: `workato/workspaces/<workspace>/connectors/<slug>/connector.rb`. When a
folder grows into a full SDK project (`Gemfile`, `spec/`, fixtures), keep one project per
connector folder.

- **Builder.** Before a `connector_builder_*` call load the two references the Workato MCP server
  names (`docs_get` with `sdk:entry:start` and with `guides:connector-builder`), and read the
  current source before you patch it. A local edit, a saved draft and a released version are
  three different states: say which one you produced.
- **Create or release only when the request says so.** A release reaches every recipe that uses
  the connector: list those recipes first (`change-impact-review`). Not verified: a deployment
  carries the latest released version to Prod, never a draft.
- **API contract.** Take auth, scopes, pagination, rate limits and error bodies from the vendor's
  documentation of the API version in use, not from memory.
- **Credentials.** A person authorizes the connection in the Workato UI (rule **Secrets** of
  `AGENTS.md`). No secret in source, prompts or fixtures. Never commit `master.key`, a plain
  `settings.yaml` or a raw recording of API traffic. Synthetic fixtures may be committed.

Test what the change can break, with synthetic responses and no live calls:

- a rejected or expired credential, and the refresh;
- an empty page, one page, several pages, a repeated cursor, the end of the list;
- rate limiting, bounded retries, an error that must not be retried (never retry a write that is
  not idempotent);
- required and optional fields, nulls, nested objects, an unexpected error body;
- for a trigger: deduplication and the cursor moving forward.

When the folder has a `Gemfile` and `spec/`, run the specs there:

```bash
bundle exec rspec
```

`ruby -c connector.rb` checks syntax only. The SDK is the Ruby gem `workato-connector-sdk`;
Workato's page describes its command line:
<https://docs.workato.com/en/developing-connectors/sdk/cli.html>. A live test needs the request
to ask for it.

Report the source changes, the tests and what is not covered. Promotion to Prod is a deployment
(`workato-prod-deploy`).

## This workspace

If `workato/workspaces/<workspace>/notes/connector-development.md` exists, read it before you act:
it holds what this workspace adds to this procedure.

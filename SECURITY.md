# Security

## Reporting a problem

Report a security problem of the kit privately, through a security advisory on the repository's
host. Do not open a public issue for it, and do not send it by e-mail: the kit publishes no
address.

Worth reporting:

- a way for a script to print, log or write an API token or a property value it was not asked
  for;
- a way for a token to reach a host other than the one `wk` holds for the profile, or a host
  outside Workato;
- a command that `scripts/guard_wk.py` is meant to block and lets through;
- a script that changes Workato without saying so in its help;
- a kit-owned file that carries data of a real workspace.

**Never paste real workspace data into an issue, a pull request or an advisory of the public
kit:** no recipe JSON, no ids, no connection or project names, no job output, no e-mail
addresses, no host names of your company. Reproduce the problem with the invented examples of
[CONTRIBUTING.md](CONTRIBUTING.md), or describe it in words.

## What the kit protects, and what it does not

| Topic | What holds | What does not |
|---|---|---|
| API tokens | `wk auth login` keeps a token in the OS keychain by default. The scripts take it from `wk` inside their own process and never print it or write it to disk. | With the file store of `wk` (`--store-type file`) a token is plain text. Not verified: `wk` then keeps it in `profiles.env` in the repository root. Use the file store only where no keychain exists, and protect the machine. |
| Where a token goes | A script sends a token only to the base URL that `wk` holds for the profile, and only when that is the plain https address of a host below `workato.com` or `workatoapp.cn`. It follows no redirect. No URL in a file of the repository can change the destination. | A `wk` profile signed in to the wrong Workato host sends its token there; check `wk auth list`. |
| Credential files | `profiles.env`, `.wk/`, `.env`, `.env.*`, and the `master.key` and `settings.yaml` of a connector project are git-ignored, and `.cursorignore` and `.geminiignore` list the same names. The Claude Code settings deny reading `profiles.env`, `.env` and `.env.*` in the repository root, everything below `.wk/`, and `master.key` and `settings.yaml` below `workato/workspaces/`. Documented (<https://code.claude.com/docs/en/permissions>): such a rule also blocks an edit of the file. | Not verified: that Cursor and Gemini CLI honor their ignore files. A `.env` file below the root, or a connector secret outside `workato/workspaces/`, is not in the deny list of Claude Code. None of this stops a person or a program that reads the file directly. |
| Property values | `scripts/sync_recipes.py` copies property names, never values. No script prints a property value, except `scripts/wk_api.py` when it is asked for one property by its full name. | A recipe can still write a secret into a job's output; job data stays out of the repository by rule, not by a check. |
| The guard | Where a harness runs it as a hook (Claude Code; Codex is configured to, not verified), `scripts/guard_wk.py` blocks `wk pull`, `wk diff`, `wk clone` and `wk push`; every shell use of `wk auth token` and `wk mcp auth-header`; commands that name `profiles.env`, also by a glob, or hand its name to `xargs`; `wk ... -o` with a file outside `tmp/`; `wk --verbose`; and `xargs wk` fed from standard input. It also looks inside `sh`, `bash`, `zsh`, `dash`, `ksh`, `fish`, `csh` and `tcsh -c`, and `env -S`. | It is a guard against mistakes, not a security boundary. It does not interpret `eval`, a command piped into a shell, a command in a variable, aliases, scripts, or a program handed to another interpreter (`python3 -c`, `perl -e`). A command that reads every file of a folder (`grep -r`) is not recognized as reading the token file, and the guard does not watch `.env` files or connector secrets. A harness without hooks is covered only by the rules in `AGENTS.md`. |
| Allowed scripts | The shared allow list of Claude Code runs most of the kit's scripts, `make check` and `make test` without asking; none of the allowed calls changes Workato. `make test` is allowed only exactly, because a variable on the `make` command line reaches the shell. | The scripts are files of the working tree. In a mode that accepts file edits without asking, or after the answer "Yes, and don't ask again" to a file edit (it holds until the session ends), an agent could change a script and then run it under its allow rule. Keep automatic acceptance of edits off in this repository. |
| Approvals in Claude Code | In Manual mode, with no saved approval for it, every Workato write needs your approval: no allowed command or tool changes Workato. Documented (<https://code.claude.com/docs/en/permission-modes>): deny rules block in every mode. Observed: the guard hook also runs in Bypass permissions mode. | A saved approval ("Yes, and don't ask again") for an interpreter, such as `python3 -c *`, or for a Workato write, such as `wk recipes start *`, lets it run without asking from then on. In Auto mode a classifier decides instead of you, and in Bypass permissions mode Claude Code asks almost nothing, a Workato write included. The kit sets none of this and switches no mode off: [docs/setup/harnesses.md](docs/setup/harnesses.md#approvals). |
| The Workato MCP server | Each person signs in with their own account; the repository stores no credentials for it. | A sign-in with an API token acts as the workspace owner: the role and the project list of the API client do not limit it. A restricted client role does not make the MCP server read-only. |
| Secrets in files | `scripts/check_secrets.py` reports known token shapes (Slack, AWS, GitHub, JWT, a bearer token, a Workato API token, a Workato webhook address), `token`, `secret`, `api_key` or `password` assigned a long mixed value in any text file, and a literal value under a secret-looking key in recipe JSON. | A token without a known shape can pass it. |
| Workspace data in the kit | `scripts/check_kit_files.py` reports, in every file the kit owns (the copyright line of `LICENSE` apart: it names the copyright holder): a number of five or more digits (NUMBER), an e-mail address outside the example domains (ADDRESS), a host that is not public documentation or an example, and the webhook and API endpoint hosts of Workato (HOST), a bracket code other than the examples' (CODE), a ticket key other than the examples' `SO-<n>` and `CM-<n>` (TICKET), a date before 2030 (DATE), text in a non-Latin script (SCRIPT), a home directory (PATH), a name the registry holds (NAME: both profiles, both Workato workspace names, the company domains, and a maintainer or a project name of two or more words) and a symbolic link (LINK). | It recognizes shapes and the names it can read, not meaning. A one-word project name, a recipe, connection, property or company name in plain words passes it. Read a change to a kit-owned file before it leaves your repository. |

## A workspace repository must be private

A repository built from the kit holds the Prod recipe JSON of a workspace, its connection,
project and property names, and its docs. Keep it private. A fork of the public kit cannot be
made private, which is why [docs/setup/new-workspace.md](docs/setup/new-workspace.md) creates the
repository by clone and push.

The repository holds no secrets and no table data by the rule **No secrets and no table data in
the repository** of `AGENTS.md`, and `scripts/check_secrets.py` looks for known token shapes. A
token without a known shape can pass that check.

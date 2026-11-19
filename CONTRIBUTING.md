# Contributing

This page is about changing the kit itself. To change your own workspace repository, follow
[AGENTS.md](AGENTS.md) and [docs/setup/README.md](docs/setup/README.md) there.

## Set up and check

You need Python 3.14 and git; no Workato account. Install the development tools once (Ruff and
mypy, pinned in `pyproject.toml`, into `.venv/`):

```bash
make dev
```

Before every commit, format and run the offline checks. CI runs the same checks.

```bash
make format
```

```bash
make check
```

`make check` runs Ruff, mypy, the unit tests, the JSON and registry checks, the generated harness
files, the Markdown links, the secret patterns and `scripts/check_kit_files.py`. It needs no
workspace and no network. One test module alone:

```bash
make test TESTS=test_check_links.py
```

## How a change is made

- **Scripts** follow [docs/conventions/python.md](docs/conventions/python.md): Python 3.14,
  standard library only, one flat `scripts/` folder, shared code in `scripts/lib/`, a docstring
  with the usage and the exit status, and `main(argv: list[str] | None = None) -> int`.
  `tests/test_scripts.py` enforces most of this.
- **One test module per script** and per library module: `tests/test_<script>.py`. A test never
  reaches Workato and never reads a real workspace: it patches the calls to `wk` and to the API,
  and builds an invented workspace with the helpers in `tests/support.py`
  (`fake_workspace`, `fake_repository`).
- **A script that reads Workato says so** in its docstring. A script that changes Workato says so
  too and asks for an explicit flag, as `scripts/wk_api.py` does with `--write`.
- **Skills, roles, models and MCP servers** are edited in `.agents/`, never in the generated
  copies. Run `scripts/sync_harness.py` after the edit and commit both.
- **Rules** in `AGENTS.md` have names, not numbers. Refer to a rule by its name. A new rule gets
  its reason in [docs/conventions/rationale.md](docs/conventions/rationale.md).
- **A change that needs a manual step** in workspace repositories (a new registry key, a renamed
  file or command) gets an entry in [CHANGELOG.md](CHANGELOG.md) with the section "What a
  workspace repository must do".
- **Docs** follow the style of the kit: plain English, short sentences, present tense, a command
  in its own fenced `bash` block, Markdown wrapped by hand at 100 columns, American spelling. A
  statement about Workato, `wk`, GitHub or a harness comes from its official documentation, its
  `--help` output or its source. Where it does not, it carries a label where it stands:
  "Observed:" for behavior seen in practice (state the behavior, not the episode), "Documented:"
  with the page, or "Not verified:".
- **License.** The kit is under the [MIT License](LICENSE). A contribution comes in under the
  same license: by sending a change you agree to that.

## No workspace data in the kit

The kit is public. A file the kit owns holds nothing of a real workspace: no company, product or
person name, no domain or host of a company, no e-mail address, no Workato id, no name of a
project, folder, recipe, connection, property, table or tag, nothing from job data. The one real
person the kit names is its copyright holder, with links to their public profiles, in the
copyright line of `LICENSE`; `scripts/check_kit_files.py` does not check that line.

`scripts/check_kit_files.py`, part of `make check`, reports these kinds of finding in a
kit-owned file:

| Kind | What it finds |
|---|---|
| NUMBER | a number of five or more digits, the shape of a Workato id |
| ADDRESS | an e-mail address outside the example domains |
| HOST | a host that is not public documentation or an example, and the webhook and API endpoint hosts of Workato |
| CODE | a bracket code other than `[SO]` and `[CM]` (a regular expression's character class in two capitals reads as one too) |
| TICKET | a ticket key other than `SO-<n>` and `CM-<n>` |
| DATE | a date before 2030 (`CHANGELOG.md` is exempt) |
| SCRIPT | text in a non-Latin script |
| PATH | the home directory of a person |
| NAME | a name the registry of the repository holds: both `wk` profiles, both Workato workspace names, the company domains, and a maintainer or a project name of two or more words |
| LINK | a symbolic link |

It cannot know a one-word project name, a recipe, connection, property or table name, or a
company name the registry does not hold. In the kit itself there is no registry, so NAME finds
nothing there. Those names are your responsibility: read the diff before you send it.

Every example uses this invented set and nothing else:

| Thing | Example |
|---|---|
| company, domain, workspace folder | Acme, `acme.example`, `acme` |
| `wk` profiles | `acme-dev`, `acme-prod` |
| Workato workspace names | `Acme (Dev)`, `Acme` |
| projects (name, slug, ids) | `Sales Orders` / `sales-orders`, Dev `1001` / Prod `1002`, folders `2001` / `2002`; `Common` / `common`, `1003` / `1004`, folders `2003` / `2004` (holds the shared connections); `Sandbox` / `sandbox`, Dev only `1005`, folder `2005` |
| folders | `[SO] Functions`, `[CM] Connections` |
| recipes | `[SO] REC \| New order` (Dev `3001`, Prod `4001`), `[SO] LF \| Create invoice` (Dev `3002`, Prod `4002`) |
| data table | `Open orders` (`5001`) |
| connections | `[CM] Slack` (`6001`), `[SO] ERP` (`6002`) |
| project properties | `orders_channel`, `protected_accounts` |
| ticket keys | `SO-1`, `SO-2` |
| people | none: write "the maintainer" or "a person" |
| dates and times | `2030-01-31`, times in UTC with `Z` |

An example never retells a process, a name or a number of a real organization.

## From a workspace repository back to the kit

An improvement made in a workspace repository travels to the kit only through files the kit
owns: `scripts/`, `tests/`, `.agents/`, the generic docs and the template, except the names a
workspace owns (`scripts/ws_*.py`, `scripts/lib/ws_*.py`, `tests/test_ws_*.py`,
`.agents/skills/ws-<name>/`, `.github/workflows/ws-*.yml`). Make a fresh clone of the kit outside
the workspace repository, copy the change into it, run `make check` there, and read the diff for
anything of your workspace before you open a pull request. Never bring over the registry, the
Prod copies, the docs of your projects, your notes files, `docs/conventions/decisions.md` or the
last section of `AGENTS.md`.

In the kit, never edit `docs/conventions/decisions.md` or the first paragraph of the last section
of `AGENTS.md`, "Rules of this workspace". Every workspace writes into both, so a change there
conflicts in every workspace at its next update.

## Out of scope

Anything that only one workspace needs stays in that workspace:

- a script for its own data is a `scripts/ws_*.py` with its tests in `tests/test_ws_*.py`, and
  shared code of such scripts is a `scripts/lib/ws_*.py` (the kit never uses that prefix);
- a skill of its own is `.agents/skills/ws-<name>/`, listed in the last section of `AGENTS.md`.
  There is no workspace-owned subagent role: `.agents/agents.json` is one kit file;
- a CI workflow of its own is `.github/workflows/ws-*.yml`;
- an addition to a procedure of the kit goes into
  `workato/workspaces/<workspace>/notes/<skill>.md`;
- a rule goes into the last section of `AGENTS.md`, "Rules of this workspace";
- a decision goes into `docs/conventions/decisions.md` of that repository.

The kit also does not run automation, host a server, or wrap Workato's package export: see
`AGENTS.md`, "No package commands".

# Python standard for `scripts/` and `tests/`

How the tooling of this repository is written, checked and tested. `make check` enforces most of
it, so the fastest way to follow it is to run `make format` and `make check` before you finish.

## In one screen

- Python 3.14, any patch release. At run time a script uses **the standard library only**.
- One language: a new helper is a Python script, not a shell or a JavaScript file.
- **Ruff** lints and formats, **mypy** checks types. Both are pinned in `pyproject.toml` and
  installed by `make dev` into `.venv/` of the repository. Nothing is installed globally.
- Every script is a command with the same skeleton, the same `--help` and the same exit status.
- Every script has its tests in `tests/test_<script>.py`. Tests never reach Workato or the network,
  and never read the workspace of the repository.
- The kit owns `scripts/` and `tests/`. A workspace adds its own scripts as `scripts/ws_<name>.py`,
  shared code of them as `scripts/lib/ws_<name>.py`, and tests as `tests/test_ws_<name>.py`. A
  `tests/test_ws_*.py` may also test the workspace's data without a script of that name. The kit
  never uses the prefix `ws_`, so an update of the kit never touches them.

| Command | When |
|---|---|
| `make dev` | once per clone, and after a tool version in `pyproject.toml` changed |
| `make format` | after editing Python: formatting, import order, the findings Ruff can fix |
| `make check` | before you finish: lint, format, types, tests and the other offline checks |
| `make test TESTS=test_<script>.py` | one test module while you work on it |
| `make lint`, `make typecheck` | Ruff or mypy alone |

`make check` runs `scripts/check.py`. CI runs `make dev check`, so it checks exactly what you
check.

## Layout

| Path | What it holds |
|---|---|
| `scripts/<name>.py` | one command per file, in one flat folder. The name is snake_case, a verb and an object where that reads naturally: `sync_recipes.py`, `check_links.py` |
| `scripts/ws_<name>.py`, `scripts/lib/ws_<name>.py` | a command of the workspace and its shared code, not the kit's. The same rules apply |
| `scripts/lib/cli.py` | exit codes, `Error`, the argument parser, `run` and `invoke` |
| `scripts/lib/wkrepo.py` | the workspace folder, the registry, `wk` calls and API reads |
| `scripts/wklintrc.json` | the kit's configuration of `wk lint` |
| `tests/test_<script>.py` | the tests of one script or one library module (`test_cli.py`, `test_wkrepo.py`) |
| `tests/support.py` | helpers the test modules share, and the invented workspace the tests use |
| `tests/test_scripts.py`, `tests/test_repository.py` | the conventions below, and the repository's own configuration, as tests |
| `pyproject.toml` | the configuration of Ruff and mypy, and their pinned versions as the `dev` dependency group. There is no `[project]` table: this is not a package |

File names are `snake_case`. A script is executable and starts with `#!/usr/bin/env python3.14`.
A module of `scripts/lib/` is not executable. Scripts do not import one another: what two of them
need goes into `scripts/lib/`, and one script uses another only by running it as a command.

`scripts/guard_wk.py` is the one exception to "shared code goes into `lib`": it is a hook and
imports nothing from `scripts/lib/`, so that it keeps working when the rest of the tooling is
broken.

## The skeleton of a script

```python
#!/usr/bin/env python3.14
"""Say in one line what the script does, and whether it reads or changes Workato.

    scripts/<name>.py            what the plain call does
    scripts/<name>.py --check    write nothing; exit 1 if something is out of date

A few sentences on what it reads, what it writes and what it never does.

Exit status: 0 done, or with --check nothing differs; 1 with --check otherwise; 2 when ...
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo


def main(argv: list[str] | None = None) -> int:
    """Do the work; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)
    ...
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)
```

- The module docstring is the `--help` text. It shows the calls as `scripts/<name>.py ...`, says
  what the script touches and ends with the line `Exit status: ...`.
- Nothing happens at import time: no reads, no argument parsing, no `sys.exit`. That is what lets
  a test import the script and call its functions.
- `main(argv)` parses its arguments first, so `--help` and a wrong argument never start any work.
- `cli.parser` turns off abbreviated options: `--ch` is not `--check`, nor `--w` `--write`.

## Command line

| Status | Meaning |
|---|---|
| `0` | done; with `--check`, nothing differs |
| `1` | the script ran and found something: a difference, a finding, a failed check |
| `2` | the script could not do its job, or an argument is wrong |

`scripts/guard_wk.py` is a hook, not a command: `0` lets the shell command run, `2` blocks it.

- **An expected problem raises `cli.Error`** with a message for the person: Workato cannot be
  read, an id is unknown, a file is not what it should be. `cli.run` prints it as one line on
  stderr, starting with `error:`, and exits with `2`. A traceback therefore always means a bug; it
  also ends with `2`, so that `1` never means anything but a finding.
- Results go to stdout, problems to stderr.
- The same words mean the same thing in every script: an environment is `dev` or `prod` and
  comes first, a positional argument that selects projects is a project slug, `--recipe ID ...`
  selects recipes by Dev id, `--check` compares and writes nothing. A flag is written out in full.
- Ids, names and profile names of Workato assets come from the registry through `wkrepo`: project
  and folder ids, data tables, the recipes a check exempts. A script hardcodes none of them. The
  keys of the registry are in [registry.md](registry.md).
- A script that needs a workspace and finds none stops with `wkrepo.NO_WORKSPACE` (exit `2`). The
  offline checks pass without a workspace.

## Workato and secrets

- A script only reads Workato. The one exception is `scripts/wk_api.py`: it sends anything but a
  GET only with `--write`, a flag that must be typed.
- Workato is reached through `wkrepo`: `wk(...)` and `wk_json(...)` for the CLI, `api(env).get(...)`
  for the developer API. A file profile of `wk` (`profiles.env`) needs `--store-type file`;
  `wkrepo` adds it, so a script never does.
- The API token is read inside the process by `wkrepo.token(...)` and is never printed, logged or
  written to a file. `wkrepo.Api` keeps it out of its `repr`, so out of tracebacks.
- The token goes only to the base URL that `wk auth list` holds for the profile, and only when
  that is the plain https address of a host below `workato.com` or `workatoapp.cn`; never to a
  host named in a file of the repository. Requests go through `wkrepo.OPENER`, which never follows a
  redirect: urllib would send the `Authorization` header on to the new host.
- Never print the value of a project property. Use `wkrepo.property_names(...)`; compare values,
  report states.
- Personal data from a job or an error text, such as an e-mail address, is replaced with
  `<user>` before it is written anywhere.

## Code style

Ruff's formatter decides the layout: 99 columns, double quotes, LF line endings, trailing commas.
The linter rules are listed in `pyproject.toml`; the ones that shape the code most:

| Rule | What it asks for |
|---|---|
| Type hints | on every function of a script, checked by mypy in strict mode. Untyped JSON from Workato is `wkrepo.Json` (`dict[str, Any]`) |
| Docstrings | a one-line summary on every module, class and function of a script, Google style; `Args:` and `Returns:` only when the signature does not say it |
| Names | `snake_case` functions and variables, `UPPER_CASE` constants, whole words: `recipe_id`, not `rid` |
| Constants | a number or a string with a meaning gets a name at the top of the module |
| Paths and files | `pathlib`, and `encoding="utf-8"` on every read and write |
| Subprocesses | an argument list, never a shell string; `check=` is always given; the program is a full path from `shutil.which`, for which `wkrepo.executable(...)` adds the message that says what to install |
| Functions | small enough for Ruff's limits (branches, statements, at most six arguments). Split a long one by what its parts do |
| Exceptions | catch the exceptions you expect, by name. Never a bare `except` |

In `tests/`, type hints and docstrings on test methods are optional: the name of a test is its
description. `pyproject.toml` has the exact exemptions.

A suppression is the last resort and says why, on the line it applies to:
`# noqa: S310 - base_url() gave an https URL`. A table that reads better aligned by hand ends with
`# fmt: skip`.

## Tests

- The standard library's `unittest`. Tests run with `make test`, or one module with
  `make test TESTS=test_sync_recipes.py`.
- `tests/__init__.py` puts `scripts/` on the import path: a test writes `import sync_recipes` and
  `from lib import cli, wkrepo`.
- One module per script and per library module, named after it. Test modules never import one
  another; what two of them need goes into `tests/support.py`.
- **No Workato, no network, no credentials.** Replace the edge, not the logic: patch a function of
  `wkrepo` (`wk_json`, `profiles`, `token`, `api`, `list_recipes`, `property_names`), or
  `subprocess.run` and `shutil.which` for a script that runs a program itself.
- **The invented workspace only.** `support.fake_workspace(self)` points `wkrepo` at a new
  temporary repository with the workspace `acme` and the registry `support.REGISTRY`;
  `support.fake_repository(self)` gives one without a workspace. Both remove every `WK_` variable
  from the environment for the test. A test never reads the workspace of the repository it runs
  in: the same tests must pass in the kit, which has none, and in every workspace repository.
- Files are written to a temporary folder (`support.temp_dir`), never into the repository.
- Call a script through `support.run_main(script.main, "--check")` to test what a person sees: the
  exit status, stdout and stderr. `support.run_script(name, ...)` runs it as a separate process.
- A test name is a sentence about behavior:
  `test_failed_second_pull_leaves_all_files_unchanged`.
- A bug fix comes with the test that would have caught it.
- **A test file of the kit passes `scripts/check_kit_files.py`.** A sample that has the shape of
  workspace data (an id of five or more digits, an e-mail address outside `*.example`, a token)
  is put together at run time, for example `"wrk" + "prod_" + "b" * 40` or `"9" * 6`, so the file
  itself holds nothing the check reports. Use the ids of the invented workspace (`1001`, `2001`)
  wherever an id is only an id. A workspace's own `tests/test_ws_*.py` is not checked.

## Adding a script

To the kit:

1. Create `scripts/<name>.py` from the skeleton and make it executable.
2. Write `tests/test_<name>.py`.
3. Add a line to `scripts/README.md`. If agents may run it without asking and it only reads, add
   it to the `allow` list in `.agents/claude-settings.json`, then run `scripts/sync_harness.py`.
4. Run `make format` and `make check`.

To a workspace: the same, with `scripts/ws_<name>.py` and `tests/test_ws_<name>.py`. Its docstring
is its documentation, because `scripts/README.md` belongs to the kit. An allow rule for it goes
into `claude_allow` of the workspace's `harness.json`, as `Bash(scripts/ws_<name>.py)` or
`Bash(scripts/ws_<name>.py *)` (see [registry.md](registry.md)), then `scripts/sync_harness.py`.

`tests/test_scripts.py` fails when a script lacks its shebang, its usage and exit status in the
docstring, the `main(argv)` signature, its test module, or answers `--help` or an unknown option
wrongly, or when it imports anything but the standard library and `lib`.

## Why these choices

| Choice | Reason |
|---|---|
| Standard library only | a script runs on a fresh clone and inside a hook, with nothing to install |
| Ruff | one tool and one configuration for linting, import order and formatting |
| mypy, strict | recipe JSON is deeply nested and untyped; the checker finds the `None` a reader misses |
| `unittest` | part of Python: tests run where the scripts run |
| Pinned tools in `.venv/` | everyone and CI check with the same versions, and nothing global changes |
| No packaging | the scripts are commands of this repository, not a library to install |
| The `ws_` prefix | the kit and a workspace never write the same file, so a kit update merges cleanly |

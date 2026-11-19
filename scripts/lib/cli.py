"""Command-line conventions every script follows: exit codes, expected failures, --help.

A script's `main(argv)` returns one of the exit codes below. When it cannot do its job it raises
`Error` with a message for the person; `run` turns that into one line on stderr and exit status
2, without a traceback. A traceback therefore always means a bug.
"""

import argparse
import sys
import traceback
from collections.abc import Callable
from typing import NoReturn

EXIT_OK = 0
EXIT_FINDINGS = 1  # the script ran and found differences, findings or files that are out of date
EXIT_ERROR = 2  # the script could not do its job (argparse uses the same status for bad arguments)

Main = Callable[[list[str] | None], int]


class Error(Exception):
    """An expected problem, worded for the person who ran the script."""


def parser(doc: str | None) -> argparse.ArgumentParser:
    """Return an argument parser whose --help text is the script's module docstring."""
    return argparse.ArgumentParser(
        description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,  # `--w` must not count as `--write`, nor `--ch` as `--check`
        suggest_on_error=True,
    )


def invoke(main: Main, argv: list[str] | None = None) -> int:
    """Call a script's main() and return its exit status; an Error becomes status 2."""
    try:
        return main(argv)
    except Error as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def run(main: Main) -> NoReturn:
    """Entry point of every script: `if __name__ == "__main__": cli.run(main)`.

    A crash is a bug: its traceback is shown and the status is 2. Python's own status for a
    crash is 1, which here means "the script ran and found something".
    """
    try:
        status = invoke(main)
    except Exception:  # noqa: BLE001 - whatever the bug is, it must not exit like a finding
        traceback.print_exc()
        status = EXIT_ERROR
    sys.exit(status)

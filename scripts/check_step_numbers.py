#!/usr/bin/env python3.14
"""Check that no recipe doc names a step by its number.

    scripts/check_step_numbers.py              every docs/<project>/recipes/*.md
    scripts/check_step_numbers.py docs/x.md    only these files

A step number moves whenever someone edits the recipe, so a recipe doc says what a step does and
never where it sits (rule "A recipe doc has no step numbers" of AGENTS.md). The check reports,
with the file and the line:

- the word "step" followed by a number: "step 12", "Steps 4-9", "step #3", "[Step 6]";
- a numbered list that does not count 1, 2, 3 ... in a row. A list that starts at 12 or jumps
  from 8 to 10 is an outline numbered by step. A list may go on under a later heading, and it
  may start again at 1.

A recipe name is not a step number. A name that carries one ("Import - Step 2: Load rows") is
ignored wherever a doc writes it out, and so is the target of every Markdown link, because a
file name is made from the recipe name. The names are the `name:` of the recipe docs.

A datapill alias with a number (`search_records_14`) holds a step number too, but `col_1` looks
the same, so the check leaves aliases to the person who writes the doc. Only recipe docs are
read: a changelog is where step numbers belong.

Exit status: 0 nothing found; 1 at least one finding; 2 a file cannot be read.
"""

import re
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
STEP_NUMBER = re.compile(r"\bsteps?[ -]*#?\d+", re.IGNORECASE)
LIST_ITEM = re.compile(r"(\d+)\.[ \t]")
LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
NAME_LINE = re.compile(r"^name:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
NOT_NEWLINE = re.compile(r"[^\n]")
FENCES = ("```", "~~~")
FRONTMATTER_FENCE = "---"
QUOTES = "\"'"

type Finding = tuple[int, str]  # the line number and what is wrong there


def recipe_docs() -> list[Path]:
    """Return every recipe doc: docs/<project>/recipes/*.md."""
    return sorted((ROOT / "docs").glob("*/recipes/*.md"))


def read(path: Path) -> str:
    """Return the text of a file, or fail with a message that names it."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        raise cli.Error(f"cannot read {path}") from None


def frontmatter(text: str) -> str:
    """Return the frontmatter block of a doc, or an empty string when it has none."""
    opening = FRONTMATTER_FENCE + "\n"
    if not text.startswith(opening):
        return ""
    end = text.find("\n" + FRONTMATTER_FENCE, len(opening))
    return text[:end] if end != -1 else ""


def recipe_name(text: str) -> str | None:
    """Return the `name:` of a recipe doc without its quotes, or None."""
    found = NAME_LINE.search(frontmatter(text))
    return found.group(1).strip(QUOTES) if found else None


def blank(found: re.Match[str]) -> str:
    """Replace a match with spaces. Its line breaks stay, so line numbers stay true."""
    return NOT_NEWLINE.sub(" ", found.group(0))


def name_pattern(name: str) -> str:
    """Return a regular expression that finds a recipe name the way a doc writes it.

    A line may wrap between two words, and Markdown may put a backslash before a bracket.
    """
    words = [
        re.escape(word).replace(r"\[", r"\\?\[").replace(r"\]", r"\\?\]") for word in name.split()
    ]
    return r"\s+".join(words)


def numbered_names() -> re.Pattern[str] | None:
    """Return a pattern for the recipe names that contain a step-like number, or None."""
    names = {recipe_name(read(path)) for path in recipe_docs()}
    numbered = sorted((name for name in names if name and STEP_NUMBER.search(name)), key=len)
    if not numbered:
        return None
    return re.compile("|".join(name_pattern(name) for name in reversed(numbered)))


def step_numbers(text: str, names: re.Pattern[str] | None) -> Iterator[Finding]:
    """Yield a finding for every "step <number>" outside a recipe name and a link target."""
    prose = LINK_TARGET.sub(blank, text)
    if names:
        prose = names.sub(blank, prose)
    for number, line in enumerate(prose.splitlines(), 1):
        for found in STEP_NUMBER.finditer(line):
            yield number, f'"{found.group(0)}" is a step number: say what the step does'


def numbering(text: str) -> Iterator[Finding]:
    """Yield a finding for every numbered list item that breaks the count 1, 2, 3 ..."""
    expected: int | None = None  # what the next item has to say; None before the first one
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(FENCES):
            fenced = not fenced
        if fenced:
            continue
        item = LIST_ITEM.match(line)
        if item is None:
            continue
        value = int(item.group(1))
        if value not in (1, expected):
            where = "starts at" if expected is None else f"jumps from {expected - 1} to"
            yield number, f"numbered list {where} {value}: an outline numbered by step?"
        expected = value + 1


def findings(path: Path, names: re.Pattern[str] | None) -> list[Finding]:
    """Return the findings of one doc in line order."""
    text = read(path)
    return sorted([*step_numbers(text, names), *numbering(text)])


def shown(path: Path) -> str:
    """Return a path the way a person knows it: relative to the repository when inside it."""
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    """Check the given recipe docs, or all of them; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "files", nargs="*", type=Path, help="recipe docs to check (default: all of them)"
    )
    args = parser.parse_args(argv)
    names = numbered_names()
    files = [path.resolve() for path in args.files] or recipe_docs()
    bad = 0
    for path in files:
        for number, problem in findings(path, names):
            print(f"{shown(path)}:{number}: {problem}")
            bad += 1
    print(f"checked {len(files)} recipe docs, {bad} findings")
    return cli.EXIT_FINDINGS if bad else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

#!/usr/bin/env python3.14
"""Check that every relative Markdown link in the repository points to an existing file.

    scripts/check_links.py              every Markdown file outside tmp/
    scripts/check_links.py docs/x.md    only these files

External links and anchors are skipped, and so is everything under tmp/ (the personal working
cache). A link that points into tmp/ fails, because that target exists for nobody else;
tmp/README.md is the one tracked file there and may be linked.

Exit status: 0 when every link resolves, 1 otherwise.
"""

import re
import sys
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
SKIP_DIRS = {".git", ".idea", ".venv", "tmp", "node_modules"}
LINK = re.compile(r"\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
INLINE_CODE = re.compile(r"`[^`]*`")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
FENCES = ("```", "~~~")
TMP_README = Path("tmp") / "README.md"


def markdown_files() -> Iterator[Path]:
    """Yield every Markdown file of the repository outside the skipped folders."""
    for path in ROOT.rglob("*.md"):
        if not SKIP_DIRS & set(path.relative_to(ROOT).parts):
            yield path


def broken_links(path: Path) -> Iterator[tuple[int, str, str]]:
    """Yield (line number, link target, reason) for every link of a file that does not resolve."""
    fenced = False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for number, raw in enumerate(lines, 1):
        if raw.lstrip().startswith(FENCES):
            fenced = not fenced
        if fenced:
            continue
        for match in LINK.finditer(INLINE_CODE.sub("", raw)):
            target = match.group(1).split("#", 1)[0]
            if not target or target.startswith("/") or SCHEME.match(target):
                continue
            resolved = (path.parent / urllib.parse.unquote(target)).resolve()
            relative = resolved.relative_to(ROOT) if resolved.is_relative_to(ROOT) else None
            if relative and relative.parts[:1] == ("tmp",) and relative != TMP_README:
                yield number, match.group(1), "points into tmp/"
            elif not resolved.exists():
                yield number, match.group(1), "missing"


def main(argv: list[str] | None = None) -> int:
    """Check the given files, or every Markdown file; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "files", nargs="*", type=Path, help="Markdown files to check (default: all)"
    )
    args = parser.parse_args(argv)
    files = [path.resolve() for path in args.files] or sorted(markdown_files())
    bad = 0
    for path in files:
        if not path.is_file():
            raise cli.Error(f"{path} is not a file")
        shown = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        for number, target, reason in broken_links(path):
            print(f"{shown}:{number}: {target} ({reason})")
            bad += 1
    print(f"checked {len(files)} files, {bad} broken links")
    return cli.EXIT_FINDINGS if bad else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

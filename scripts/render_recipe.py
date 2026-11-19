#!/usr/bin/env python3.14
"""Print a recipe JSON file as a compact step tree.

    scripts/render_recipe.py <file.recipe.json> [--full]

The Prod copies are in workato/workspaces/<workspace>/projects/<project>/, the Dev copies in
tmp/wk/dev/<project>/ after `scripts/sync_recipes.py dev`. Step numbers are Workato UI numbers
(the trigger is 1). Datapills are printed as the `#{...}` text they are stored as. Long input
values are cut unless --full is given.

Exit status: 0 done, 2 when the file cannot be read as a recipe.
"""

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli
from lib.wkrepo import Json

INPUT_LIMIT = 400
FILTER_LIMIT = 600
STEP_SETTINGS = ("mask_data", "retry_count", "retry_interval", "retry_on_error")


def short(value: Any, limit: int | None) -> str:
    """Return a value on one line, cut to `limit` characters unless the limit is None."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    if limit is None or len(text) <= limit:
        return text
    return f"{text[:limit]}…(+{len(text) - limit})"


def step_lines(node: Json, depth: int, *, full: bool) -> list[str]:
    """Return the printed lines of a step and of every step nested in it."""
    indent = "  " * depth
    number = node.get("number")
    ui_number = number + 1 if isinstance(number, int) else "?"
    head = f"{indent}[{ui_number}] {node.get('keyword')}"
    if node.get("provider") or node.get("name"):
        head += f" {node.get('provider') or ''}.{node.get('name') or ''}"
    if node.get("as"):
        head += f"  as={node['as']}"
    if node.get("title"):
        head += f"  title={node['title']!r}"
    if node.get("skip"):
        head += " SKIP"
    lines = [head]
    if node.get("comment"):
        lines.append(f"{indent}    comment: {node['comment']}")
    if node.get("filter"):
        lines.append(
            f"{indent}    filter: {short(node['filter'], None if full else FILTER_LIMIT)}"
        )
    for key, value in (node.get("input") or {}).items():
        lines.append(f"{indent}    {key}: {short(value, None if full else INPUT_LIMIT)}")
    lines += [
        f"{indent}    {key}: {node[key]}"
        for key in STEP_SETTINGS
        if node.get(key) not in (None, "", False)
    ]
    for child in node.get("block") or []:
        lines += step_lines(child, depth + 1, full=full)
    return lines


def render(recipe: Json, *, full: bool) -> list[str]:
    """Return the printed lines of a whole recipe: header, connections, steps."""
    code = recipe["code"] if isinstance(recipe["code"], dict) else json.loads(recipe["code"])
    title = f"# {recipe['name']}  (version {recipe.get('version')}"
    lines = [
        f"{title}, concurrency {recipe.get('concurrency')})",
        f"description: {recipe.get('description', '')}",
        "",
        "connections:",
    ]
    lines += [
        f"  - {connection.get('provider')} ({connection.get('name')}): "
        f"account_id={connection.get('account_id')}"
        for connection in recipe.get("config", [])
    ]
    return [*lines, "", *step_lines(code, 0, full=full)]


def main(argv: list[str] | None = None) -> int:
    """Print the step tree of a recipe file; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("file", type=Path, help="a .recipe.json file")
    parser.add_argument("--full", action="store_true", help="print every input value uncut")
    args = parser.parse_args(argv)
    try:
        recipe = json.loads(args.file.read_text(encoding="utf-8"))
        lines = render(recipe, full=args.full)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise cli.Error(f"{args.file} is not a recipe file ({type(error).__name__})") from None
    print("\n".join(lines))
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

#!/usr/bin/env python3.14
"""Write `prod_recipe_id` into the frontmatter of the recipe docs of the managed projects.

    scripts/link_prod_ids.py            update the docs
    scripts/link_prod_ids.py --check    write nothing; exit 1 if a doc is out of date

A recipe doc is named with the recipe's Dev id; the Prod copy has another id. The two copies are
paired by `match_key` (folder plus name) from the two index.json files:

    tmp/wk/dev/<project>/index.json                                 sync_recipes.py dev
    workato/workspaces/<workspace>/projects/<project>/index.json    sync_recipes.py prod

A doc whose recipe has no Prod copy gets no `prod_recipe_id`. Only that one frontmatter line is
touched. The Dev copy is a personal cache and may be behind: a link to a recipe that is still in
Prod is never removed, only reported, and a project without a Dev copy is skipped.

Exit status: 0 done, or with --check every doc is up to date; 1 with --check otherwise.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
DOC_ID = re.compile(r"\d+")
PROD_ID_LINE = re.compile(r"^prod_recipe_id: (\d+)$", re.MULTILINE)


def prod_ids(slug: str) -> tuple[dict[int, int] | None, set[int]]:
    """Return {Dev recipe id: Prod recipe id} and the set of Prod ids; None without both copies."""
    dev_index = wkrepo.snapshot_dir("dev", slug) / "index.json"
    prod_index = wkrepo.snapshot_dir("prod", slug) / "index.json"
    if not dev_index.exists() or not prod_index.exists():
        return None, set()
    prod_recipes = json.loads(prod_index.read_text(encoding="utf-8"))["recipes"]
    dev_recipes = json.loads(dev_index.read_text(encoding="utf-8"))["recipes"]
    by_key = {recipe["match_key"]: recipe["id"] for recipe in prod_recipes}
    paired = {
        recipe["id"]: by_key[recipe["match_key"]]
        for recipe in dev_recipes
        if recipe["match_key"] in by_key
    }
    return paired, set(by_key.values())


def relink(text: str, prod_id: int | None) -> str:
    """Return the doc with its `prod_recipe_id` line set to the id, or removed for None."""
    end = text.find("\n---", 4) if text.startswith("---\n") else -1
    if end < 0:  # no frontmatter, or one that is never closed: nothing to write the id into
        return text
    head, body = text[4:end], text[end:]
    lines = [line for line in head.split("\n") if not line.startswith("prod_recipe_id:")]
    if prod_id is not None:
        at = next((i for i, line in enumerate(lines) if line.startswith("recipe_id:")), -1)
        lines.insert(at + 1, f"prod_recipe_id: {prod_id}")
    return "---\n" + "\n".join(lines) + body


def main(argv: list[str] | None = None) -> int:
    """Update or check the docs of every managed project; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)

    changed, kept = [], []
    for slug in wkrepo.snapshot_projects("prod"):
        ids, in_prod = prod_ids(slug)
        if ids is None:  # nothing to pair with: leave the docs of this project as they are
            print(f"skipped {slug}: no Dev copy (run scripts/sync_recipes.py dev) or no Prod copy")
            continue
        for doc in sorted((ROOT / "docs" / slug / "recipes").glob("*.md")):
            match = DOC_ID.match(doc.name)
            if not match:
                continue
            text = doc.read_text(encoding="utf-8")
            prod_id = ids.get(int(match.group(0)))
            current = PROD_ID_LINE.search(text)
            if prod_id is None and current and int(current.group(1)) in in_prod:
                kept.append(doc.relative_to(ROOT).as_posix())
                continue
            new = relink(text, prod_id)
            if new != text:
                changed.append(doc.relative_to(ROOT).as_posix())
                if not args.check:
                    doc.write_text(new, encoding="utf-8")
    for path in kept:
        print(f"kept, not paired by the Dev copy (run scripts/sync_recipes.py dev): {path}")
    for path in changed:
        print(("out of date: " if args.check else "updated: ") + path)
    print(f"{len(changed)} doc(s) {'out of date' if args.check else 'updated'}.")
    return cli.EXIT_FINDINGS if args.check and changed else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

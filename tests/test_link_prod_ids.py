"""scripts/link_prod_ids.py: a doc gets the Prod id of its recipe; a stale cache removes none."""

import unittest
from unittest.mock import patch

import link_prod_ids as link
from lib import wkrepo
from tests import support


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "link-")
        self.docs = self.root / "docs" / "example" / "recipes"
        self.docs.mkdir(parents=True)
        support.start(
            self,
            patch.object(link, "ROOT", self.root),
            patch.object(wkrepo, "snapshot_projects", return_value=["example"]),
            patch.object(
                wkrepo, "snapshot_dir", side_effect=lambda env, slug: self.root / env / slug
            ),
        )

    def index(self, env, recipes):
        entries = [{"id": recipe_id, "match_key": key} for recipe_id, key in recipes]
        support.write_json(self.root / env / "example" / "index.json", {"recipes": entries})

    def doc(self, name, extra=""):
        text = f"---\nrecipe_id: {name[0]}\n{extra}name: x\n---\nbody\n"
        (self.docs / name).write_text(text, encoding="utf-8")

    def text(self, name):
        return (self.docs / name).read_text(encoding="utf-8")

    def test_link_is_written_and_a_stale_dev_copy_never_removes_a_valid_one(self):
        self.index("dev", [(1, "a")])
        self.index("prod", [(101, "a"), (102, "b")])
        self.doc("1-a.md")
        self.doc("2-b.md", "prod_recipe_id: 102\n")  # still in Prod, but not in the Dev copy
        self.doc("3-c.md", "prod_recipe_id: 999\n")  # no longer in Prod
        result = support.run_main(link.main)
        self.assertEqual(result.code, 0)
        self.assertIn("recipe_id: 1\nprod_recipe_id: 101\n", self.text("1-a.md"))
        self.assertIn("prod_recipe_id: 102\n", self.text("2-b.md"))
        self.assertIn("kept, not paired by the Dev copy", result.out)
        self.assertNotIn("prod_recipe_id", self.text("3-c.md"))

    def test_project_without_a_dev_copy_is_skipped_and_its_docs_stay(self):
        self.index("prod", [(101, "a")])
        self.doc("1-a.md", "prod_recipe_id: 101\n")
        result = support.run_main(link.main)
        self.assertEqual(result.code, 0)
        self.assertIn("skipped example", result.out)
        self.assertIn("prod_recipe_id: 101", self.text("1-a.md"))

    def test_check_reports_and_writes_nothing(self):
        self.index("dev", [(1, "a")])
        self.index("prod", [(101, "a")])
        self.doc("1-a.md")
        before = self.text("1-a.md")
        result = support.run_main(link.main, "--check")
        self.assertEqual(result.code, 1)
        self.assertIn("out of date: docs/example/recipes/1-a.md", result.out)
        self.assertEqual(self.text("1-a.md"), before)
        support.run_main(link.main)
        self.assertEqual(support.run_main(link.main, "--check").code, 0)

    def test_only_the_one_frontmatter_line_is_touched(self):
        text = "---\nrecipe_id: 1\nname: x\n---\nprod_recipe_id: in the body stays\n"
        linked = link.relink(text, 101)
        self.assertEqual(
            linked,
            "---\nrecipe_id: 1\nprod_recipe_id: 101\nname: x\n---\n"
            "prod_recipe_id: in the body stays\n",
        )
        self.assertEqual(link.relink(linked, None), text)
        self.assertEqual(link.relink("no frontmatter\n", 101), "no frontmatter\n")
        unclosed = "---\nrecipe_id: 1\nname: x\n"
        self.assertEqual(link.relink(unclosed, 101), unclosed)


if __name__ == "__main__":
    unittest.main()

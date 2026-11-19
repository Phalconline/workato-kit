"""scripts/check_links.py: relative Markdown links resolve, and none points into tmp/."""

import unittest
from unittest.mock import patch

import check_links
from tests import support


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "links-")
        (self.root / "docs").mkdir()
        (self.root / "tmp" / "notes").mkdir(parents=True)
        (self.root / "docs" / "other.md").write_text("# Other\n", encoding="utf-8")
        (self.root / "docs" / "with space.md").write_text("# Space\n", encoding="utf-8")
        (self.root / "tmp" / "README.md").write_text("# Cache\n", encoding="utf-8")
        (self.root / "tmp" / "notes" / "draft.md").write_text("[gone](missing.md)\n", "utf-8")
        support.start(self, patch.object(check_links, "ROOT", self.root))

    def broken(self, text):
        page = self.root / "docs" / "page.md"
        page.write_text(text, encoding="utf-8")
        return list(check_links.broken_links(page))

    def test_existing_targets_resolve(self):
        text = "[a](other.md) [b](other.md#section) [c](with%20space.md) [d](../docs/other.md)\n"
        self.assertEqual(self.broken(text), [])

    def test_missing_target_is_reported_with_its_line(self):
        self.assertEqual(self.broken("first\n\n[a](gone.md)\n"), [(3, "gone.md", "missing")])

    def test_external_links_anchors_and_absolute_paths_are_skipped(self):
        text = "[a](https://example.com) [b](mailto:x@example.com) [c](#top) [d](/absolute)\n"
        self.assertEqual(self.broken(text), [])

    def test_code_is_not_a_link(self):
        text = "`[a](gone.md)`\n\n```\n[b](gone.md)\n```\n\n~~~\n[c](gone.md)\n~~~\n"
        self.assertEqual(self.broken(text), [])

    def test_a_link_into_tmp_fails_even_when_the_file_exists(self):
        found = self.broken("[draft](../tmp/notes/draft.md)\n[readme](../tmp/README.md)\n")
        self.assertEqual(found, [(1, "../tmp/notes/draft.md", "points into tmp/")])

    def test_files_in_tmp_and_in_the_venv_are_not_scanned(self):
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "page.md").write_text("[gone](missing.md)\n", encoding="utf-8")
        scanned = {path.relative_to(self.root).as_posix() for path in check_links.markdown_files()}
        self.assertEqual(scanned, {"docs/other.md", "docs/with space.md"})

    def test_exit_status_counts_broken_links(self):
        self.assertEqual(support.run_main(check_links.main).code, 0)
        (self.root / "docs" / "page.md").write_text("[a](gone.md)\n", encoding="utf-8")
        result = support.run_main(check_links.main)
        self.assertEqual(result.code, 1)
        self.assertIn("docs/page.md:1: gone.md (missing)", result.out)

    def test_a_named_file_that_is_missing_or_outside_the_repository_does_not_crash(self):
        missing = support.run_main(check_links.main, str(self.root / "docs" / "no-such.md"))
        self.assertEqual(missing.code, 2)
        self.assertIn("is not a file", missing.err)
        outside = support.temp_dir(self, "outside-") / "page.md"
        outside.write_text("[a](gone.md)\n", encoding="utf-8")
        result = support.run_main(check_links.main, str(outside))
        self.assertEqual(result.code, 1)
        self.assertIn(f"{outside}:1: gone.md (missing)", result.out)


if __name__ == "__main__":
    unittest.main()

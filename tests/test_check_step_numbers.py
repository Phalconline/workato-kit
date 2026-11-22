"""scripts/check_step_numbers.py: a recipe doc never names a step by its number."""

import unittest
from unittest.mock import patch

import check_step_numbers
from tests import support

BAD_LINE = "A Slack alert follows step 12.\n"


class DocTestCase(unittest.TestCase):
    """A repository of temporary recipe docs, and helpers to check one."""

    def setUp(self):
        self.root = support.temp_dir(self, "step-numbers-")
        support.start(self, patch.object(check_step_numbers, "ROOT", self.root))

    def doc(self, text, name="100-demo.md", project="sales-orders"):
        path = self.root / "docs" / project / "recipes" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def findings(self, text, **where):
        path = self.doc(text, **where)
        return check_step_numbers.findings(path, check_step_numbers.numbered_names())

    def lines(self, text, **where):
        return [number for number, _problem in self.findings(text, **where)]


class StepNumberTests(DocTestCase):
    def test_a_step_number_is_reported_with_its_line(self):
        found = self.findings(f"first\n\n{BAD_LINE}")
        self.assertEqual([number for number, _ in found], [3])
        self.assertIn('"step 12"', found[0][1])

    def test_every_spelling_of_a_step_number_is_found(self):
        spellings = (
            "Step 12", "step 12", "STEP 12", "steps 4\u20139", "Steps 4-9", "(step 7)", "step #3",
            "step-11", "step12", "[Step 6] MissingRequiredField", "Steps 2 through 11",
        )  # fmt: skip
        for spelling in spellings:
            with self.subTest(spelling=spelling):
                self.assertEqual(self.lines(f"before {spelling} after\n"), [1])

    def test_a_step_number_in_code_is_found_too(self):
        self.assertEqual(self.lines("Linter says `[Step 6] MissingRequiredField`.\n"), [1])
        self.assertEqual(self.lines("```\nstep 12\n```\n"), [2])

    def test_the_word_step_without_a_number_is_fine(self):
        for text in (
            "this step", "the step comment", "a two-step check", "step-up authentication",
            "the steps below", "footstep 4",
        ):  # fmt: skip
            with self.subTest(text=text):
                self.assertEqual(self.lines(f"{text}\n"), [])

    def test_counts_ids_and_dates_are_not_step_numbers(self):
        text = "24 steps, 53 stages, recipe 3001, run of 2030-01-31, version 12.\n"
        self.assertEqual(self.lines(text), [])

    def test_the_frontmatter_is_read_too(self):
        text = "---\nname: Demo\nversion_documented: 503  # step-8\n---\n\nBody.\n"
        self.assertEqual(self.lines(text), [3])


class RecipeNameTests(DocTestCase):
    def setUp(self):
        super().setUp()
        self.named = self.doc(
            '---\nname: "Import - Step 2: Load rows"\n---\n\n# Import - Step 2: Load rows\n',
            name="1-import-step-2-load-rows.md",
        )

    def test_a_recipe_name_with_a_number_is_not_a_step_number(self):
        names = check_step_numbers.numbered_names()
        self.assertEqual(check_step_numbers.findings(self.named, names), [])
        text = (
            "Opens [Import - Step 2: Load rows](1-import-step-2-load-rows.md).\n"
            "The same, wrapped: Import - Step 2:\nLoad rows.\n"
            "Later, step 9 posts the alert.\n"
        )
        self.assertEqual(self.lines(text, name="2-caller.md", project="common"), [4])

    def test_a_part_of_a_name_is_still_a_step_number(self):
        self.assertEqual(self.lines('They are the ones named "Step 2".\n', name="2-b.md"), [1])

    def test_a_name_with_brackets_is_found_with_or_without_the_markdown_escape(self):
        self.doc('---\nname: "[SO] Step 3 sync"\n---\n', name="3-so-step-3-sync.md")
        for mention in ("[SO] Step 3 sync", r"\[SO\] Step 3 sync"):
            with self.subTest(mention=mention):
                self.assertEqual(self.lines(f"Calls {mention}.\n", name="4-caller.md"), [])

    def test_a_longer_name_wins_over_a_shorter_one_inside_it(self):
        self.doc('---\nname: "Sync - Step 2"\n---\n', name="5-sync-step-2.md")
        self.doc('---\nname: "Sync - Step 2: Extra"\n---\n', name="6-sync-step-2-extra.md")
        self.assertEqual(self.lines("Calls Sync - Step 2: Extra.\n", name="7-caller.md"), [])

    def test_the_target_of_a_link_is_not_read_but_its_text_is(self):
        self.assertEqual(self.lines("[Handler](12-step-3-handler.md)\n"), [])
        self.assertEqual(self.lines("[step 3](12-handler.md)\n"), [1])


class NumberedListTests(DocTestCase):
    def test_a_list_that_counts_from_one_is_fine(self):
        self.assertEqual(self.lines("1. a\n2. b\n3. c\n"), [])

    def test_a_list_that_skips_a_number_is_reported_once(self):
        found = self.findings("1. a\n2. b\n4. c\n5. d\n")
        self.assertEqual([number for number, _ in found], [3])
        self.assertIn("jumps from 2 to 4", found[0][1])

    def test_a_list_that_does_not_start_at_one_is_reported(self):
        found = self.findings("## Outline\n12. a\n13. b\n")
        self.assertEqual([number for number, _ in found], [2])
        self.assertIn("starts at 12", found[0][1])

    def test_a_list_may_go_on_under_a_later_heading(self):
        text = "## Activation\n1. a\n2. b\n\n## Deactivation\n3. c\n4. d\n"
        self.assertEqual(self.lines(text), [])

    def test_a_list_may_start_again_at_one(self):
        self.assertEqual(self.lines("1. a\n2. b\n\nText.\n\n1. c\n2. d\n"), [])

    def test_numbered_lines_in_a_code_block_are_not_a_list(self):
        self.assertEqual(self.lines("```\n12. a\n15. b\n```\n"), [])

    def test_decimals_and_dates_are_not_list_items(self):
        self.assertEqual(self.lines("1.5 seconds\n3.14 is pi\n2030-01-31 is a date\n"), [])

    def test_an_item_that_wraps_onto_the_next_line_is_one_item(self):
        self.assertEqual(self.lines("1. a long\n   item\n2. b\n"), [])


class MainTests(DocTestCase):
    def test_exit_status_and_report_name_the_file_and_the_line(self):
        self.doc("Fine.\n", name="1-fine.md", project="common")
        self.assertEqual(support.run_main(check_step_numbers.main).code, 0)
        self.doc(f"first\n\n{BAD_LINE}", name="2-bad.md")
        result = support.run_main(check_step_numbers.main)
        self.assertEqual(result.code, 1)
        self.assertIn("docs/sales-orders/recipes/2-bad.md:3:", result.out)
        self.assertIn("checked 2 recipe docs, 1 findings", result.out)

    def test_every_project_is_checked(self):
        for project in ("sales-orders", "common", "sandbox"):
            self.doc(BAD_LINE, name="1-bad.md", project=project)
        result = support.run_main(check_step_numbers.main)
        self.assertEqual(result.code, 1)
        self.assertIn("checked 3 recipe docs, 3 findings", result.out)

    def test_only_the_files_given_are_checked(self):
        self.doc(BAD_LINE, name="1-bad.md")
        fine = self.doc("Fine.\n", name="2-fine.md")
        result = support.run_main(check_step_numbers.main, str(fine))
        self.assertEqual(result.code, 0)
        self.assertIn("checked 1 recipe docs, 0 findings", result.out)

    def test_docs_outside_the_recipe_folders_are_not_read(self):
        # A changelog is where step numbers belong.
        for name in ("sales-orders/changelog.md", "conventions/decisions.md"):
            path = self.root / "docs" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(BAD_LINE, encoding="utf-8")
        self.doc("Fine.\n")
        result = support.run_main(check_step_numbers.main)
        self.assertEqual(result.code, 0)
        self.assertIn("checked 1 recipe docs", result.out)

    def test_a_file_that_cannot_be_read_is_status_2(self):
        self.doc("x\n").write_bytes(b"\xff\xfe step 1")
        result = support.run_main(check_step_numbers.main)
        self.assertEqual(result.code, 2)
        self.assertIn("cannot read", result.err)

    def test_a_missing_file_is_status_2(self):
        self.doc("Fine.\n")
        result = support.run_main(check_step_numbers.main, str(self.root / "gone.md"))
        self.assertEqual(result.code, 2)
        self.assertIn("cannot read", result.err)


if __name__ == "__main__":
    unittest.main()

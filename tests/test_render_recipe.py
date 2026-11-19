"""scripts/render_recipe.py: a recipe file is printed as a step tree with UI step numbers."""

import json
import unittest

import render_recipe
from tests import support

RECIPE = {
    "name": "[SO] LF | Example",
    "version": 7,
    "concurrency": 1,
    "description": "Does one thing.",
    "config": [{"provider": "erp", "name": "erp", "account_id": 12}],
    "code": {
        "number": 0,
        "keyword": "trigger",
        "provider": "clock",
        "name": "scheduled_event",
        "block": [
            {
                "number": 1,
                "keyword": "if",
                "filter": {"conditions": [{"lhs": "a", "operand": "present"}]},
                "block": [
                    {
                        "number": 2,
                        "keyword": "action",
                        "provider": "erp",
                        "name": "get_order",
                        "as": "order1",
                        "comment": "Read the order.",
                        "skip": True,
                        "retry_count": 3,
                        "input": {"id": "#{_dp('x')}", "long": "x" * 500, "multi": "a\nb"},
                    }
                ],
            }
        ],
    },
}


class RenderTests(unittest.TestCase):
    def test_header_connections_and_steps_are_printed_with_ui_numbers(self):
        text = "\n".join(render_recipe.render(RECIPE, full=False))
        self.assertIn("# [SO] LF | Example  (version 7, concurrency 1)", text)
        self.assertIn("description: Does one thing.", text)
        self.assertIn("  - erp (erp): account_id=12", text)
        self.assertIn("[1] trigger clock.scheduled_event", text)
        self.assertIn("  [2] if", text)
        self.assertIn("    [3] action erp.get_order  as=order1 SKIP", text)
        self.assertIn("        comment: Read the order.", text)
        self.assertIn("        id: #{_dp('x')}", text)
        self.assertIn("        multi: a\\nb", text)
        self.assertIn("        retry_count: 3", text)

    def test_long_values_are_cut_unless_full_is_asked_for(self):
        cut = "\n".join(render_recipe.render(RECIPE, full=False))
        self.assertIn("x" * render_recipe.INPUT_LIMIT + "…(+100)", cut)
        self.assertIn("x" * 500, "\n".join(render_recipe.render(RECIPE, full=True)))

    def test_code_stored_as_text_is_rendered_too(self):
        as_text = {**RECIPE, "code": json.dumps(RECIPE["code"])}
        self.assertEqual(
            render_recipe.render(as_text, full=False), render_recipe.render(RECIPE, full=False)
        )


class CommandLineTests(unittest.TestCase):
    def test_a_recipe_file_is_printed(self):
        path = support.write_json(support.temp_dir(self, "render-") / "1-x.recipe.json", RECIPE)
        result = support.run_main(render_recipe.main, str(path))
        self.assertEqual(result.code, 0)
        self.assertIn("[3] action erp.get_order", result.out)

    def test_a_file_that_is_not_a_recipe_is_an_expected_failure(self):
        folder = support.temp_dir(self, "render-")
        (folder / "broken.json").write_text("{", encoding="utf-8")
        support.write_json(folder / "other.json", {"no": "code"})
        for name in ("broken.json", "other.json", "missing.json"):
            with self.subTest(file=name):
                result = support.run_main(render_recipe.main, str(folder / name))
                self.assertEqual(result.code, 2)
                self.assertIn("is not a recipe file", result.err)


if __name__ == "__main__":
    unittest.main()

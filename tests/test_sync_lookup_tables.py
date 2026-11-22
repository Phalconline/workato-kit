"""scripts/sync_lookup_tables.py: only table definitions are read; hand-written text is kept."""

import json
import unittest
from typing import Any
from unittest.mock import patch

import sync_lookup_tables as tables
from lib import cli, wkrepo
from tests import support

ORDERS_TABLE: dict[str, Any] = {
    "id": 4001,
    "name": "[SO] Orders | Cache",
    "project_id": 1001,  # the Dev project of sales-orders in the test registry
    "schema": json.dumps(
        [
            {"label": "Order  id"},
            {"name": "customer email"},
            {"label": "Untitled column 3"},
            {"label": ""},
        ]
    ),
}
FILE_NAME = "4001-so-orders-cache.md"


class FakeApi:
    """Stands in for `wkrepo.api(env)`: records each GET and answers with the listed tables."""

    def __init__(self, test: FolderTests) -> None:
        self.test = test

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.test.reads.append((path, params))
        if self.test.failure:
            raise cli.Error(f"Workato answered HTTP 401 to GET {path}")
        if self.test.pages:
            number = (params or {}).get("page", 1)
            return self.test.pages[number - 1] if number <= len(self.test.pages) else []
        return self.test.listed


class PartsTests(unittest.TestCase):
    def test_columns_in_use_are_named_and_untitled_ones_are_left_out(self):
        self.assertEqual(tables.columns(ORDERS_TABLE), ["Order id", "customer email"])
        self.assertEqual(tables.columns({"schema": [{"label": "A"}]}), ["A"])
        self.assertEqual(tables.columns({}), [])

    def test_used_by_matches_the_table_id_as_a_whole_number_or_the_name(self):
        longer = "1" + str(ORDERS_TABLE["id"])
        index = [
            {"recipe_id": 1, "name": '"One"', "doc": "docs/x/1.md", "tables": ["4001"]},
            {"recipe_id": 2, "name": "Two", "doc": "docs/x/2.md", "tables": [longer]},
            {
                "recipe_id": 3,
                "name": "Three",
                "doc": "docs/x/3.md",
                "tables": [{"name": "[so] orders | cache"}],
            },
            {"recipe_id": 4, "name": "Four", "doc": None, "tables": ["4001"]},
            {"recipe_id": 5, "name": "Five", "doc": "docs/x/5.md"},
            {"recipe_id": 6, "name": "Six", "doc": "docs/x/6.md", "tables": ["lookup table 4001"]},
            # A data table with the same number is another table.
            {"recipe_id": 7, "name": "Seven", "doc": "docs/x/7.md", "tables": ["data table 4001"]},
        ]
        self.assertEqual(
            tables.used_by(ORDERS_TABLE, index),
            [("One", "docs/x/1.md"), ("Six", "docs/x/6.md"), ("Three", "docs/x/3.md")],
        )

    def test_personal_data_is_guessed_from_field_names_until_a_person_answers(self):
        kept = {"personal_data": None}
        self.assertEqual(tables.personal_data(["Order id", "customer email"], kept), "yes")
        self.assertEqual(tables.personal_data(["Order id", "user"], kept), "yes")
        self.assertEqual(tables.personal_data(["Order id"], kept), "no")
        self.assertEqual(tables.personal_data(["customer email"], {"personal_data": "no"}), "no")

    def test_a_missing_file_has_nothing_hand_written_yet(self):
        missing = support.temp_dir(self, "tables-") / "none.md"
        self.assertEqual(
            tables.existing(missing),
            {
                "purpose": tables.EMPTY,
                "fields": {},
                "verified": "unverified",
                "personal_data": None,
            },
        )


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.root = support.fake_workspace(self)
        self.out = self.root / "workato" / "workspaces" / "acme" / "lookup-tables"
        self.index = support.write_json(
            self.root / "workato" / "workspaces" / "acme" / "inventory" / "recipes-index.json",
            [
                {
                    "recipe_id": 3001,
                    "name": "[SO] REC | New order",
                    "doc": "docs/sales-orders/recipes/3001-new-order.md",
                    "tables": ["[SO] Orders | Cache (4001)"],
                }
            ],
        )
        self.listed: list[dict[str, Any]] = [ORDERS_TABLE]
        self.failure = False
        self.pages: list[list[dict[str, Any]]] = []
        self.reads: list[tuple[str, Any]] = []
        self.environments: list[str] = []
        support.start(
            self,
            patch.object(tables, "ROOT", self.root),
            patch.object(wkrepo, "api", side_effect=self.api),
        )

    def api(self, env, prof=None):
        self.environments.append(env)
        return FakeApi(self)

    def file(self):
        return self.out / FILE_NAME

    def test_a_table_file_and_the_index_are_written_from_the_definitions_only(self):
        result = support.run_main(tables.main)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.out, "1 lookup tables, 2 file(s) written.\n")
        self.assertEqual(self.environments, ["dev"])
        self.assertEqual(
            self.reads, [("/lookup_tables", {"page": 1, "per_page": wkrepo.PAGE_SIZE})]
        )
        text = self.file().read_text(encoding="utf-8")
        self.assertIn('table_id: 4001\nname: "[SO] Orders | Cache"\nscope: Sales Orders\n', text)
        self.assertIn("personal_data: yes\nverified: unverified\n", text)
        self.assertIn("| `Order id` |  |\n| `customer email` |  |\n", text)
        self.assertIn(
            "- [[SO] REC \\| New order](../../../../docs/sales-orders/recipes/3001-new-order.md)",
            text,
        )
        readme = (self.out / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith(tables.README_HEAD))
        self.assertIn(
            f"| [[SO] Orders \\| Cache]({FILE_NAME}) | Sales Orders | 2 | 1 | yes | no |", readme
        )

    def test_every_page_of_the_table_list_is_read_before_a_file_is_removed(self):
        def table(number):
            return {"id": 5000 + number, "name": f"Table {number}", "schema": "[]"}

        first = [table(number) for number in range(wkrepo.PAGE_SIZE)]
        self.pages = [first, [table(wkrepo.PAGE_SIZE), ORDERS_TABLE]]
        result = support.run_main(tables.main)
        self.assertEqual(result.code, 0)
        self.assertIn(f"{wkrepo.PAGE_SIZE + 2} lookup tables", result.out)
        self.assertTrue(self.file().is_file())
        self.assertEqual([params["page"] for _path, params in self.reads], [1, 2])

    def test_an_api_that_repeats_its_first_page_ends_the_listing(self):
        first = [
            {"id": 5000 + number, "name": f"Table {number}", "schema": "[]"}
            for number in range(wkrepo.PAGE_SIZE)
        ]
        self.pages = [first, first, first]
        self.assertEqual(support.run_main(tables.main).code, 0)
        self.assertEqual(len(self.reads), 2)

    def test_a_rename_in_workato_keeps_the_hand_written_text(self):
        support.run_main(tables.main)
        text = self.file().read_text(encoding="utf-8")
        self.file().write_text(
            text.replace(tables.EMPTY, "Remembers the orders that were processed."), "utf-8"
        )
        self.listed = [{**ORDERS_TABLE, "name": "[SO] Orders | Cache v2"}]
        check = support.run_main(tables.main, "--check")
        self.assertIn(f"{FILE_NAME} (its table was renamed)", check.out)
        self.assertEqual(support.run_main(tables.main).code, 0)
        self.assertFalse(self.file().exists())
        renamed = self.out / "4001-so-orders-cache-v2.md"
        self.assertIn("Remembers the orders that were processed.", renamed.read_text("utf-8"))

    def test_without_a_recipe_index_no_table_is_used_by_a_recipe(self):
        self.index.unlink()
        self.assertEqual(support.run_main(tables.main).code, 0)
        text = self.file().read_text(encoding="utf-8")
        self.assertIn(
            "## Used by\n\nThe recipe index names no documented recipe for this table.\n", text
        )

    def test_hand_written_text_survives_a_run_and_new_fields_are_added(self):
        support.run_main(tables.main)
        text = self.file().read_text(encoding="utf-8")
        text = text.replace(tables.EMPTY, "Remembers the orders that were processed.")
        text = text.replace("| `Order id` |  |", "| `Order id` | The id of the order. |")
        text = text.replace("verified: unverified", "verified: read-in-ui")
        text = text.replace("personal_data: yes", "personal_data: no")
        self.file().write_text(text, encoding="utf-8")
        self.listed = [
            {**ORDERS_TABLE, "schema": [{"label": "Order id"}, {"label": "Added later"}]}
        ]

        self.assertEqual(support.run_main(tables.main).code, 0)
        text = self.file().read_text(encoding="utf-8")
        self.assertIn("Remembers the orders that were processed.", text)
        self.assertIn("| `Order id` | The id of the order. |\n| `Added later` |  |\n", text)
        self.assertIn("personal_data: no\nverified: read-in-ui\n", text)
        self.assertNotIn("customer email", text)
        self.assertIn("| no | yes |\n", (self.out / "README.md").read_text(encoding="utf-8"))

    def test_check_reports_what_is_out_of_date_and_writes_nothing(self):
        result = support.run_main(tables.main, "--check")
        self.assertEqual(result.code, 1)
        self.assertIn(
            f"out of date: workato/workspaces/acme/lookup-tables/{FILE_NAME}\n", result.out
        )
        self.assertFalse(self.out.exists())
        support.run_main(tables.main)
        self.assertEqual(support.run_main(tables.main, "--check").code, 0)

    def test_the_file_of_a_table_that_no_longer_exists_is_removed(self):
        support.run_main(tables.main)
        self.listed = []
        check = support.run_main(tables.main, "--check")
        self.assertEqual(check.code, 1)
        self.assertIn(f"{FILE_NAME} (table no longer exists)", check.out)
        self.assertTrue(self.file().exists())
        support.run_main(tables.main)
        self.assertFalse(self.file().exists())
        self.assertTrue((self.out / "README.md").exists())

    def test_a_table_outside_the_registered_projects_is_global(self):
        for project_id in (None, 1002, 1999):  # no project, a Prod project, an unknown one
            with self.subTest(project_id=project_id):
                self.listed = [{**ORDERS_TABLE, "project_id": project_id}]
                support.run_main(tables.main)
                self.assertIn("scope: global\n", self.file().read_text(encoding="utf-8"))

    def test_a_table_of_a_dev_only_project_takes_its_name(self):
        self.listed = [{**ORDERS_TABLE, "project_id": 1005}]
        support.run_main(tables.main)
        self.assertIn("scope: Sandbox\n", self.file().read_text(encoding="utf-8"))

    def test_a_failed_read_writes_nothing_and_ends_with_status_two(self):
        self.failure = True
        result = support.run_main(tables.main)
        self.assertEqual(result.code, 2)
        self.assertIn("HTTP 401", result.err)
        self.assertFalse(self.out.exists())

    def test_without_a_workspace_the_run_says_how_to_create_one(self):
        support.fake_repository(self)
        result = support.run_main(tables.main)
        self.assertEqual(result.code, 2)
        self.assertIn("scripts/init_workspace.py", result.err)
        self.assertEqual(self.reads, [])


if __name__ == "__main__":
    unittest.main()

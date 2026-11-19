"""scripts/build_index.py on an invented workspace: docs, a Dev copy and an old index."""

import copy
import json
import re
import unittest
from typing import Any
from unittest.mock import patch

import build_index
from lib import wkrepo
from tests import support

TABLE_ID = "4001"
CALLER: dict[str, Any] = {
    "name": "[SO] REC | New order",
    "code": {
        "number": 0,
        "provider": "clock",
        "name": "scheduled_event",
        "block": [
            {
                "number": 1,
                "provider": "workato_recipe_function",
                "name": "call_recipe_async",
                "input": {
                    "flow_id": "3002",
                    "parameters": {"order_id": "x", "customer_email": "y"},
                },
            },
            {
                "number": 2,
                "provider": "slack",
                "name": "post",
                "input": {
                    "channel": '#{_dp(\'{"property_name":"slack_orders_channel"}\')}',
                    "text": '#{_dp(\'{"property_name":"orders_channel"}\')}',
                },
            },
            {"number": 3, "provider": "workato_db_table", "input": {"table_id": TABLE_ID}},
        ],
    },
}
CALLEE: dict[str, Any] = {
    "name": "[SO] LF | Create invoice",
    "code": {"number": 0, "provider": "workato_recipe_function", "name": "execute"},
}


def registry() -> dict[str, Any]:
    """Return the test registry with a data table on each of two projects."""
    data = copy.deepcopy(support.REGISTRY)
    data["projects"]["sales-orders"]["tables"] = {TABLE_ID: "Orders cache"}
    data["projects"]["common"]["tables"] = {"4002": "Shared log"}
    return data


class TextTests(unittest.TestCase):
    def test_frontmatter_is_read_as_flat_strings(self):
        text = (
            "---\nrecipe_id: 3001\nname: \"[SO] A: B\"\n# note\nseverity: 'low'\nempty:\n---\n"
            "body: no\n"
        )
        self.assertEqual(
            build_index.frontmatter(text),
            {"recipe_id": "3001", "name": "[SO] A: B", "severity": "low", "empty": ""},
        )
        self.assertEqual(build_index.frontmatter("no frontmatter"), {})

    def test_a_comment_after_a_frontmatter_value_is_not_the_value(self):
        # The template explains the allowed values in a comment; a copy of it must not index them.
        text = (
            "---\nseverity:          # Critical | High | Medium | Low\n"
            'verdict: Keep  # optional\nname: "[SO] A #1"\npath: [SO] Functions #2\n---\n'
        )
        self.assertEqual(
            build_index.frontmatter(text),
            {"severity": "", "verdict": "Keep", "name": "[SO] A #1", "path": "[SO] Functions"},
        )
        self.assertEqual(build_index.frontmatter("---\nnever: closed\n"), {})

    def test_numbered_items_are_counted_in_their_section_only(self):
        text = "## Findings\n\n1. one\n2. two\n\n## Other\n\n1. not a finding\n"
        self.assertEqual(build_index.numbered_items(text, "Findings"), 2)
        self.assertEqual(build_index.numbered_items(text, "Missing"), 0)

    def test_the_trigger_type_comes_from_the_provider_or_else_from_the_name(self):
        cases = {
            "callable": {"provider": "workato_recipe_function", "name": "execute"},
            "schedule": {"provider": "clock", "name": "scheduled_event"},
            "api endpoint": {"provider": "workato_api_platform", "name": "receive_request"},
            "webhook": {"provider": "workato_webhooks", "name": "new_event"},
        }
        for kind, code in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(build_index.trigger_type(code), kind)
        self.assertEqual(
            build_index.trigger_type({"provider": "erp", "name": "order_hook"}), "webhook"
        )
        self.assertEqual(
            build_index.trigger_type({"provider": "erp", "name": "new_order"}), "other"
        )
        self.assertEqual(build_index.trigger_type({}), "other")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.root = support.fake_workspace(self, registry())
        self.docs = self.root / "docs"
        self.inventory = wkrepo.inventory()
        self.dev = wkrepo.DEV_CACHE
        self.doc("sales-orders", 3001, "new-order")
        self.doc("sales-orders", 3002, "create-invoice", findings="## Findings\n\n1. one\n")
        support.write_json(self.inventory / "recipes-index.json", self.old_index())
        support.write_json(self.dev / "sales-orders" / "3001-new-order.recipe.json", CALLER)
        support.write_json(self.dev / "sales-orders" / "3002-create-invoice.recipe.json", CALLEE)
        support.start(
            self,
            patch.object(build_index, "ROOT", self.root),
            patch.object(build_index, "DOCS", self.docs),
            patch.object(build_index, "INDEX_MD", self.docs / "recipe-index.md"),
        )

    def doc(self, slug, recipe_id, name, findings="", extra=""):
        path = self.docs / slug / "recipes" / f"{recipe_id}-{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = f"---\nrecipe_id: {recipe_id}\nseverity: high\n{extra}---\n"
        path.write_text(head + findings, "utf-8")

    def old_index(self):
        return [
            {
                "recipe_id": 3001,
                "name": "[SO] REC | New order",
                "verdict": "Keep",
                "last_job": "2030-01-31",
                "last_job_status": "succeeded",
                "external_systems": ["ERP"],
                "called_by": ["3009"],
                "step_count": 99,
            },
            {"recipe_id": 3002, "name": "[SO] LF | Create invoice", "verdict": "Rewrite"},
            {"recipe_id": 3009, "name": "Old caller", "verdict": "Decommission"},
        ]

    def built(self):
        index = build_index.build(self.old_index())
        return {entry["recipe_id"]: entry for entry in index}

    def test_the_dev_copy_recomputes_what_the_recipe_json_holds(self):
        caller = self.built()[3001]
        self.assertEqual(caller["trigger_type"], "schedule")
        self.assertEqual(caller["step_count"], 4)
        self.assertEqual(
            caller["connectors"], ["clock", "workato_recipe_function", "slack", "workato_db_table"]
        )
        self.assertEqual(
            caller["calls"],
            [
                {
                    "recipe_id": 3002,
                    "name": "[SO] LF | Create invoice",
                    "mode": "async",
                    "fields": ["customer_email", "order_id"],
                }
            ],
        )
        self.assertEqual(caller["properties"], ["orders_channel", "slack_orders_channel"])
        self.assertEqual(caller["url"], "https://app.workato.com/recipes/3001")
        self.assertEqual(self.built()[3002]["trigger_type"], "callable")

    def test_the_tables_of_every_project_in_the_registry_are_looked_for(self):
        self.assertEqual(
            build_index.registry_tables(),
            {TABLE_ID: "Orders cache (4001)", "4002": "Shared log (4002)"},
        )
        self.assertEqual(self.built()[3001]["tables"], ["Orders cache (4001)"])
        self.assertEqual(self.built()[3002]["tables"], [])

    def test_a_table_id_inside_a_longer_number_is_not_a_use_of_the_table(self):
        longer = copy.deepcopy(CALLER)
        longer["code"]["block"][2]["input"]["table_id"] = "9" + TABLE_ID
        support.write_json(self.dev / "sales-orders" / "3001-new-order.recipe.json", longer)
        self.assertEqual(self.built()[3001]["tables"], [])

    def test_without_tables_in_the_registry_no_table_is_looked_for(self):
        support.write_json(wkrepo.registry_path(), support.REGISTRY)
        self.assertEqual(build_index.registry_tables(), {})
        self.assertEqual(self.built()[3001]["tables"], [])

    def test_a_verdict_in_a_doc_wins_over_the_one_carried_over(self):
        self.doc("sales-orders", 3001, "new-order", extra="verdict: Merge\n")
        built = self.built()
        self.assertEqual(built[3001]["verdict"], "Merge")
        self.assertEqual(built[3002]["verdict"], "Rewrite")  # its doc states none

    def test_keys_the_script_does_not_write_are_carried_over_untouched(self):
        caller = self.built()[3001]
        self.assertEqual(caller["verdict"], "Keep")
        self.assertEqual(caller["external_systems"], ["ERP"])  # a key of the workspace's own
        self.assertEqual(
            (caller["last_job"], caller["last_job_status"]), ("2030-01-31", "succeeded")
        )
        self.assertNotIn("external_systems", self.built()[3002])

    def test_the_doc_states_the_last_job_and_the_name(self):
        self.doc(
            "sales-orders",
            3001,
            "new-order",
            extra='last_job: 2030-02-28\nname: "[SO] REC | New order (renamed)"\n',
        )
        caller = self.built()[3001]
        self.assertEqual(caller["last_job"], "2030-02-28")
        self.assertEqual(caller["name"], "[SO] REC | New order (renamed)")

    def test_a_rename_in_workato_reaches_the_index_through_the_dev_copy(self):
        renamed = {**CALLEE, "name": "[SO] LF | Create invoice v2"}
        support.write_json(self.dev / "sales-orders" / "3002-create-invoice.recipe.json", renamed)
        built = self.built()
        self.assertEqual(built[3002]["name"], "[SO] LF | Create invoice v2")
        self.assertEqual(built[3001]["calls"][0]["name"], "[SO] LF | Create invoice v2")

    def test_a_call_step_without_a_target_yet_does_not_stop_the_index(self):
        for flow_id in (None, "", '#{_dp(\'{"pill_type":"output"}\')}'):
            unfinished = copy.deepcopy(CALLER)
            step_input = unfinished["code"]["block"][0]["input"]
            if flow_id is None:
                del step_input["flow_id"]
            else:
                step_input["flow_id"] = flow_id
            path = self.dev / "sales-orders" / "3001-new-order.recipe.json"
            support.write_json(path, unfinished)
            with self.subTest(flow_id=flow_id):
                built = self.built()
                self.assertIsNone(built[3001]["calls"][0]["recipe_id"])
                self.assertEqual(built[3001]["calls"][0]["mode"], "async")
                self.assertEqual(built[3002]["called_by"], [])

    def test_doc_frontmatter_fills_the_rest_and_the_inventory_sheet_is_optional(self):
        entries = self.built()
        self.assertEqual(entries[3001]["doc"], "docs/sales-orders/recipes/3001-new-order.md")
        self.assertEqual(entries[3001]["project"], "Sales Orders")
        self.assertEqual((entries[3001]["severity"], entries[3001]["owner"]), ("high", None))
        self.assertEqual(entries[3002]["findings_count"], 1)
        self.assertIsNone(entries[3009]["doc"])  # in the old index only: kept, without a doc

    def test_the_inventory_sheet_fills_what_a_doc_leaves_empty(self):
        rows = [
            {"recipe_id": 3001, "owner": "Sales team", "severity": "low", "path": "Orders"},
            {"recipe_id": 3002, "owner": "Finance team"},
        ]
        support.write_json(self.inventory / "recipes.json", rows)
        entries = self.built()
        self.assertEqual(
            (entries[3001]["severity"], entries[3001]["owner"], entries[3001]["path"]),
            ("high", "Sales team", "Orders"),  # the doc's severity wins over the sheet
        )
        self.assertEqual(entries[3002]["owner"], "Finance team")

    def test_call_edges_are_folded_into_called_by(self):
        entries = self.built()
        self.assertEqual(entries[3002]["called_by"], [3001])
        self.assertEqual(entries[3001]["called_by"], [3009])  # seen in job history, carried over

    def test_without_a_dev_copy_the_old_record_stays_and_the_run_says_so(self):
        for path in (self.dev / "sales-orders").iterdir():
            path.unlink()
        self.assertEqual(self.built()[3001]["step_count"], 99)
        result = support.run_main(build_index.main)
        self.assertEqual(result.code, 0)
        self.assertIn("note: no Dev copy of sales-orders, common:", result.out)

    def test_only_a_project_without_a_copy_is_named_in_the_note(self):
        result = support.run_main(build_index.main)
        self.assertIn("note: no Dev copy of common: their records are carried over", result.out)
        self.assertNotIn("sales-orders", result.out.split("\n")[0])

    def test_markdown_lists_documented_recipes_by_project_and_verdict(self):
        text = build_index.index_markdown(build_index.build(self.old_index()))
        self.assertIn("## Sales Orders (2)", text)
        rewrite = text.index("LF \\| Create invoice")
        keep = text.index("REC \\| New order")
        self.assertLess(rewrite, keep)  # Rewrite sorts before Keep
        self.assertIn(
            "(sales-orders/recipes/3001-new-order.md) | schedule | 2030-01-31 | Keep |", text
        )
        self.assertNotIn("Old caller", text)

    def test_the_header_links_only_to_the_machine_readable_index(self):
        text = build_index.index_markdown(build_index.build(self.old_index()))
        header = text.split("\n## ", 1)[0]
        self.assertEqual(
            re.findall(r"\]\(([^)]+)\)", header),
            ["../workato/workspaces/acme/inventory/recipes-index.json"],
        )
        target = (self.docs / "../workato/workspaces/acme/inventory/recipes-index.json").resolve()
        self.assertEqual(target, build_index.index_json())

    def test_check_writes_nothing_and_a_second_run_changes_nothing(self):
        before = (self.inventory / "recipes-index.json").read_text(encoding="utf-8")
        result = support.run_main(build_index.main, "--check")
        self.assertEqual(result.code, 1)
        self.assertIn("out of date: docs/recipe-index.md", result.out)
        self.assertEqual((self.inventory / "recipes-index.json").read_text("utf-8"), before)
        self.assertFalse((self.docs / "recipe-index.md").exists())
        written = support.run_main(build_index.main)
        self.assertEqual(written.code, 0)
        self.assertIn("written: workato/workspaces/acme/inventory/recipes-index.json", written.out)
        self.assertIn("3 recipes indexed, 2 with a doc, 1 call edges", written.out)
        self.assertEqual(support.run_main(build_index.main, "--check").code, 0)
        json.loads((self.inventory / "recipes-index.json").read_text(encoding="utf-8"))

    def test_a_first_run_creates_the_folder_of_the_index(self):
        for path in self.inventory.iterdir():
            path.unlink()
        self.inventory.rmdir()
        result = support.run_main(build_index.main)
        self.assertEqual(result.code, 0)
        written = json.loads((self.inventory / "recipes-index.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["recipe_id"] for entry in written], [3001, 3002])
        self.assertIsNone(written[0]["verdict"])  # nothing to carry over on a first run


if __name__ == "__main__":
    unittest.main()

"""scripts/doc_sync.py: the plan around an asset, the stamps, and the audit of the recipe docs."""

import copy
import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import doc_sync
from lib import cli, wkrepo
from tests import support

NOON = datetime(2030, 1, 31, 12, 0, tzinfo=UTC)
EARLY = "2030-01-30T08:00:00.000-06:00"
LATER = "2030-01-31T09:30:00.000-06:00"
SLACK = "[CM] Slack (ops@acme.example)"
LOOKUPS = "workato/workspaces/acme/lookup-tables"


class FakeApi:
    """Stands in for `wkrepo.api("dev")`: answers a recipe read with its `updated_at`."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def get(self, path: str, _params: dict[str, Any] | None = None) -> Any:
        recipe_id = int(path.rsplit("/", 1)[1])
        for item in self.items:
            if item["id"] == recipe_id:
                return {"updated_at": item["updated_at"]}
        raise cli.Error(f"Workato answered HTTP 404 to GET {path}")


def step(provider, name, **step_input):
    return {"provider": provider, "name": name, "input": step_input}


def recipe(recipe_id, name, steps=(), accounts=(), updated=EARLY):
    """One item of `wk recipes list`; the steps sit one block below the trigger, as in Workato."""
    code = {
        "provider": "clock",
        "name": "scheduled_event",
        "block": [{"provider": "workato_variable", "name": "if", "block": list(steps)}],
    }
    return {
        "id": recipe_id,
        "name": name,
        "updated_at": updated,
        "code": json.dumps(code),
        "config": [{"account_id": account, "provider": "x"} for account in (None, *accounts)],
    }


class DocSyncTests(unittest.TestCase):
    def setUp(self):
        registry = copy.deepcopy(support.REGISTRY)
        registry["projects"]["sales-orders"]["tables"] = {"10": "Open orders"}
        self.root = support.fake_workspace(self, registry)
        self.docs = self.root / "docs" / "sales-orders" / "recipes"
        self.docs.mkdir(parents=True)
        self.lookups = self.root / LOOKUPS
        self.lookups.mkdir()
        self.state = self.root / "workato/workspaces/acme/inventory/doc-sync.json"
        self.items = [
            recipe(
                1,
                "Target",
                [
                    step("workato_recipe_function", "call_recipe", flow_id="2"),
                    step("workato_db_table", "get_records", table_id="10"),
                    step("lookup_table", "search_entries", lookup_table_id="20"),
                    step("workato_db_table", "get_records", table_id="#{_dp('pill')}"),
                ],
                accounts=[100],
            ),
            recipe(2, "Callee"),
            recipe(3, "Caller", [step("workato_recipe_function", "call_recipe_async", flow_id=1)]),
            recipe(4, "Sharer", [step("workato_db_table", "add_record", table_id="10")]),
            recipe(5, "Unrelated", [step("workato_db_table", "add_record", table_id="11")]),
        ]
        self.connections = [{"id": 100, "name": SLACK}, {"id": 101, "name": "[SO] ERP"}]
        for recipe_id, name in ((1, "target"), (2, "callee"), (3, "caller"), (4, "sharer")):
            self.write_doc(recipe_id, f"# {name}\n")
        (self.lookups / "20-cache.md").write_text("# cache\n", encoding="utf-8")
        self.clock = self.start(patch.object(doc_sync, "now", return_value=NOON))
        self.start(
            patch.object(doc_sync, "ROOT", self.root),
            patch.object(doc_sync, "DOCS", self.root / "docs"),
            patch.object(wkrepo, "list_recipes", side_effect=lambda _prof: self.items),
            patch.object(wkrepo, "list_connections", side_effect=lambda _prof: self.connections),
            patch.object(wkrepo, "api", side_effect=lambda _env, _prof=None: FakeApi(self.items)),
        )

    def start(self, *patches):
        started = []
        for item in patches:
            started.append(item.start())
            self.addCleanup(item.stop)
        return started[0]

    def write_doc(self, recipe_id, text):
        (self.docs / f"{recipe_id}-doc.md").write_text(text, encoding="utf-8")

    def write_state(self, text):
        """Put a stamps file in place by hand; a new workspace has no inventory folder yet."""
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(text, encoding="utf-8")

    def call(self, *args):
        return support.run_main(doc_sync.main, *args)

    def stamp_all(self):
        every = ["1", "2", "3", "4", "connection:100", "lookup_table:20", "data_table:10"]
        self.assertEqual(self.call("stamp", *every).code, 0)

    def plan_rows(self, target="1", *options):
        result = self.call("plan", target, "--json", *options)
        return result, {row["asset"]: row for row in json.loads(result.out)["assets"]}

    def test_dependencies_are_read_from_nested_steps_and_config(self):
        found = doc_sync.parse_recipe(self.items[0])
        self.assertEqual(found.calls, {2})
        self.assertEqual(found.data_tables, {10})  # a datapill in table_id is no dependency
        self.assertEqual(found.lookup_tables, {20})
        self.assertEqual(found.connections, {100})
        self.assertEqual(doc_sync.parse_recipe(self.items[2]).calls, {1})  # flow_id as a number

    def test_unreadable_code_is_reported_and_skipped(self):
        self.items.append({**recipe(6, "Broken"), "code": "{not json"})
        result = self.call("plan", "1")
        self.assertIn("could not be read", result.err)
        self.assertIn("6", result.err)

    def test_plan_lists_what_the_recipe_uses_and_what_shares_it_and_nothing_else(self):
        result, rows = self.plan_rows()
        self.assertEqual(result.code, 1)  # nothing is stamped yet
        self.assertEqual(
            list(rows),
            [
                "recipe:1",
                "recipe:2",
                "recipe:3",
                "recipe:4",
                "connection:100",
                "lookup_table:20",
                "data_table:10",
            ],
        )
        self.assertEqual(rows["recipe:2"]["relations"], ["called by the target"])
        self.assertEqual(rows["recipe:3"]["relations"], ["calls the target"])
        self.assertEqual(rows["recipe:4"]["relations"], ["also uses data table 10"])
        self.assertEqual(rows["data_table:10"]["name"], "Open orders")
        self.assertEqual(rows["connection:100"]["name"], "[CM] Slack")  # no account, no e-mail
        self.assertEqual(rows["recipe:1"]["doc"], "docs/sales-orders/recipes/1-doc.md")
        self.assertEqual(rows["lookup_table:20"]["doc"], f"{LOOKUPS}/20-cache.md")
        self.assertEqual(rows["lookup_table:20"]["name"], "cache")
        self.assertTrue(all(row["stale"] == "never synced" for row in rows.values()))

    def test_plan_text_names_the_stamp_command_for_what_is_stale(self):
        result = self.call("plan", "1")
        self.assertIn("STALE  recipe 1  Target  (target)", result.out)
        self.assertIn("why: never synced", result.out)
        self.assertIn("doc: docs/sales-orders/recipes/1-doc.md", result.out)
        self.assertIn("7 asset(s), 7 stale.", result.out)
        self.assertIn(
            "scripts/doc_sync.py stamp recipe:1 recipe:2 recipe:3 recipe:4 connection:100 "
            "lookup_table:20 data_table:10",
            result.out,
        )

    def test_fresh_stamps_make_the_plan_pass_until_they_get_old_or_the_asset_changes(self):
        self.stamp_all()
        result, rows = self.plan_rows()
        self.assertEqual(result.code, 0)
        self.assertEqual({row["stale"] for row in rows.values()}, {None})

        self.clock.return_value = NOON + timedelta(hours=25)
        _, rows = self.plan_rows()
        self.assertEqual(rows["recipe:2"]["stale"], "last synced 25 h ago")
        _, rows = self.plan_rows("1", "--max-age-hours", "48")
        self.assertIsNone(rows["recipe:2"]["stale"])
        self.clock.return_value = NOON + timedelta(days=3)
        _, rows = self.plan_rows()
        self.assertEqual(rows["recipe:2"]["stale"], "last synced 3 days ago")

    def test_a_recipe_changed_in_workato_or_a_renamed_connection_is_stale_even_when_fresh(self):
        self.stamp_all()
        self.items[1]["updated_at"] = LATER
        self.connections[0]["name"] = "[CM] Chat (ops@acme.example)"
        result, rows = self.plan_rows()
        self.assertEqual(result.code, 1)
        self.assertEqual(rows["recipe:2"]["stale"], "changed in Workato since the last sync")
        self.assertEqual(
            rows["connection:100"]["stale"], "renamed since the last sync (was [CM] Slack)"
        )
        self.assertIsNone(rows["recipe:3"]["stale"])

    def test_two_spellings_of_one_updated_at_are_not_a_change(self):
        # `wk recipes list` drops the trailing zeros of the fraction that the API keeps.
        self.items[1]["updated_at"] = "2030-01-30T08:00:00.360-06:00"
        self.stamp_all()
        kept = json.loads(self.state.read_text(encoding="utf-8"))["assets"]["recipe:2"]
        self.assertEqual(kept["updated_at"], "2030-01-30T08:00:00.360-06:00")
        for shown in (
            "2030-01-30T08:00:00.36-06:00",
            "2030-01-30T08:00:00.3600-06:00",
            "2030-01-30T14:00:00.36Z",
        ):
            with self.subTest(shown=shown):
                self.items[1]["updated_at"] = shown
                result, rows = self.plan_rows()
                self.assertEqual(result.code, 0)
                self.assertIsNone(rows["recipe:2"]["stale"])
                audit = self.call("status", "sales-orders")
                self.assertEqual(audit.code, 0)
                self.assertIn("0 of 4 recipe doc(s) may be out of date.", audit.out)

    def test_a_different_moment_is_a_change_down_to_the_millisecond(self):
        self.items[1]["updated_at"] = "2030-01-30T08:00:00.360-06:00"
        self.stamp_all()
        for shown in ("2030-01-30T08:00:00.361-06:00", "2030-01-30T08:00:00.36-05:00"):
            with self.subTest(shown=shown):
                self.items[1]["updated_at"] = shown
                _, rows = self.plan_rows()
                self.assertEqual(
                    rows["recipe:2"]["stale"], "changed in Workato since the last sync"
                )
                self.assertIn(
                    "sales-orders  2  2-doc.md  changed in Workato since the last sync",
                    self.call("status", "sales-orders").out,
                )

    def test_a_marker_that_is_not_a_timestamp_is_compared_as_text(self):
        self.items[1]["updated_at"] = "not a time"
        self.stamp_all()
        _, rows = self.plan_rows()
        self.assertIsNone(rows["recipe:2"]["stale"])
        for shown in ("another text", "2030-01-30T08:00:00.360-06:00"):
            with self.subTest(shown=shown):
                self.items[1]["updated_at"] = shown
                _, rows = self.plan_rows()
                self.assertEqual(
                    rows["recipe:2"]["stale"], "changed in Workato since the last sync"
                )

    def test_a_stamp_that_kept_no_updated_at_cannot_vouch_for_a_recipe(self):
        self.write_state('{"assets": {"recipe:2": {"synced_at": "2030-01-31T12:00:00Z"}}}')
        _, rows = self.plan_rows()
        self.assertEqual(rows["recipe:2"]["stale"], "changed in Workato since the last sync")

    def test_only_the_marker_of_a_recipe_is_read_as_a_time(self):
        self.connections[0]["name"] = "2030-01-30"
        self.stamp_all()
        self.connections[0]["name"] = "2030-01-30T00:00:00"
        _, rows = self.plan_rows()
        self.assertEqual(
            rows["connection:100"]["stale"], "renamed since the last sync (was 2030-01-30)"
        )

    def test_a_missing_doc_or_a_deleted_recipe_is_stale(self):
        (self.docs / "4-doc.md").unlink()
        self.items.append(
            recipe(7, "Calls gone", [step("workato_recipe_function", "call_recipe", flow_id="99")])
        )
        _, rows = self.plan_rows("4")
        self.assertEqual(rows["recipe:4"]["stale"], "has no doc")
        _, rows = self.plan_rows("7")
        self.assertEqual(rows["recipe:99"]["stale"], "not in Dev (deleted?)")
        self.assertEqual(rows["recipe:99"]["name"], "(not in Dev)")

    def test_a_connection_name_missing_from_the_doc_of_the_target_is_noted(self):
        _, rows = self.plan_rows()
        self.assertEqual(
            rows["connection:100"]["hint"], "its name is not in the doc of the target"
        )
        self.write_doc(1, "Connections: `[CM] Slack`.\n")
        _, rows = self.plan_rows()
        self.assertIsNone(rows["connection:100"]["hint"])

    def test_plan_of_a_connection_or_a_table_lists_the_recipes_that_use_it(self):
        _, rows = self.plan_rows("connection:100")
        self.assertEqual(list(rows), ["connection:100", "recipe:1"])
        self.assertEqual(rows["recipe:1"]["relations"], ["uses the target"])
        _, rows = self.plan_rows("data_table:10")
        self.assertEqual(list(rows), ["data_table:10", "recipe:1", "recipe:4"])

    def test_more_assets_than_the_limit_is_said_and_json_carries_it(self):
        result = self.call("plan", "1", "--limit", "3")
        self.assertIn("7 assets: over the limit of 3", result.out)
        self.assertTrue(
            json.loads(self.call("plan", "1", "--json", "--limit", "3").out)["over_limit"]
        )
        self.assertFalse(json.loads(self.call("plan", "1", "--json").out)["over_limit"])

    def test_stamp_writes_one_sorted_line_per_asset_and_never_an_email(self):
        self.assertEqual(self.call("stamp", "data_table:10", "2", "connection:100", "1").code, 0)
        text = self.state.read_text(encoding="utf-8")
        self.assertNotIn("@", text)
        data = json.loads(text)
        self.assertEqual(
            data["assets"]["connection:100"],
            {"name": "[CM] Slack", "synced_at": "2030-01-31T12:00:00Z"},
        )
        self.assertEqual(
            data["assets"]["recipe:1"], {"synced_at": "2030-01-31T12:00:00Z", "updated_at": EARLY}
        )
        order = [
            text.index(f'"{key}"')
            for key in ("recipe:1", "recipe:2", "connection:100", "data_table:10")
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(sum(line.startswith('  "') for line in text.splitlines()), 4)
        self.clock.return_value = NOON + timedelta(hours=1)
        self.assertEqual(
            self.call("stamp", "2").code, 0
        )  # earlier stamps are kept, one is renewed
        data = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(data["assets"]), 4)
        self.assertEqual(data["assets"]["recipe:2"]["synced_at"], "2030-01-31T13:00:00Z")
        self.assertEqual(data["assets"]["recipe:1"]["synced_at"], "2030-01-31T12:00:00Z")

    def test_a_failed_stamp_writes_nothing(self):
        result = self.call("stamp", "1", "5", "connection:100")  # recipe 5 has no doc
        self.assertEqual(result.code, 2)
        self.assertIn("recipe 5 has no doc", result.err)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.call("stamp", "1", "connection:999").code, 2)
        self.assertFalse(self.state.exists())

    def test_unknown_assets_and_bad_arguments_are_status_2(self):
        for args in (("plan", "999"), ("plan", "x1"), ("plan", "tables:1"), ("status", "nope")):
            with self.subTest(args=args):
                self.assertEqual(self.call(*args).code, 2)
        self.assertIn("not in Dev", self.call("plan", "999").err)

    def test_a_damaged_state_file_is_an_error_not_an_empty_state(self):
        self.write_state("{")
        result = self.call("plan", "1")
        self.assertEqual(result.code, 2)
        self.assertIn("doc-sync.json is not a valid doc-sync file", result.err)
        self.write_state('{"assets": {"recipe:1": {"synced_at": "yesterday"}}}')
        self.assertEqual(self.call("plan", "1").code, 2)

    def test_status_lists_unstamped_changed_and_orphaned_docs_and_ignores_age(self):
        (self.docs / "9-gone.md").write_text("# gone\n", encoding="utf-8")
        self.assertEqual(self.call("stamp", "1", "2").code, 0)
        self.items[1]["updated_at"] = LATER
        self.clock.return_value = NOON + timedelta(days=30)  # age alone never makes a doc stale
        result = self.call("status")
        self.assertEqual(result.code, 1)
        self.assertNotIn("1-doc.md", result.out)
        self.assertIn(
            "sales-orders  2  2-doc.md  changed in Workato since the last sync", result.out
        )
        self.assertIn("sales-orders  3  3-doc.md  never synced", result.out)
        self.assertIn("sales-orders  9  9-gone.md  the recipe is no longer in Dev", result.out)
        self.assertIn("4 of 5 recipe doc(s) may be out of date.", result.out)
        self.assertIn("4 of 5 recipe doc(s)", self.call("status", "sales-orders").out)

    def test_a_doc_marked_deleted_is_a_record_and_not_reported(self):
        (self.docs / "9-gone.md").write_text("---\ndeleted: true\n---\n# gone\n", encoding="utf-8")
        self.assertEqual(self.call("stamp", "1", "2", "3", "4").code, 0)
        result = self.call("status")
        self.assertEqual(result.code, 0)
        self.assertIn("0 of 5 recipe doc(s)", result.out)

    def test_status_passes_when_every_doc_is_stamped_and_unchanged(self):
        self.assertEqual(self.call("stamp", "1", "2", "3", "4").code, 0)
        result = self.call("status", "sales-orders")
        self.assertEqual(result.code, 0)
        self.assertIn("0 of 4 recipe doc(s) may be out of date.", result.out)


if __name__ == "__main__":
    unittest.main()

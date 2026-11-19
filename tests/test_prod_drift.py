"""scripts/prod_drift.py with an invented workspace in Dev and Prod: no Workato account is read."""

import argparse
import copy
import json
import unittest
from typing import Any
from unittest.mock import patch

import prod_drift as drift
from lib import cli, wkrepo
from tests import support

NEW_ORDER = "[SO] REC | New order"
CREATE_INVOICE = "[SO] LF | Create invoice"
COMMON_INVOICE = "[CM] LF | Create invoice"
FUNCTIONS = "[SO] Functions"
# Values of five digits look like ids to scripts/check_kit_files.py, so they are built here.
LOW, HIGH = int("1" + "0" * 4), int("9" + "0" * 4)
PROFILES = {"acme-dev": "dev", "acme-prod": "prod"}


def listed(recipe_id, name=NEW_ORDER, folders=(), folder_id=2001):
    """Return a recipe as project_recipes() lists it."""
    return {"id": recipe_id, "name": name, "folder_path": list(folders), "folder_id": folder_id}


def nested(provider, step_input, comment="", label=None):
    """Return a recipe with one step under the trigger."""
    step = {"number": 1, "provider": provider, "comment": comment, "input": step_input}
    if label:
        step["dynamicPickListSelection"] = label
    return {"code": {"number": 0, "provider": "clock", "block": [step]}}


def call(flow_id, status="open"):
    """Return a recipe that calls a recipe function."""
    parameters = {"order": "o" * 300, "status": status}
    return nested("workato_recipe_function", {"flow_id": flow_id, "parameters": parameters})


class CompareCodeTests(unittest.TestCase):
    def compare(self, dev_value, prod_value, name="input"):
        def recipe(value):
            return {"code": {"number": 0, "provider": "clock", name: value}}

        return drift.compare_code(recipe(dev_value), recipe(prod_value))

    def test_addresses_in_comment_findings_are_shortened(self):
        def recipe(comment):
            return {"code": {"number": 0, "provider": "clock", "comment": comment}}

        found = drift.compare_code(recipe("ask orders@acme.example first"), recipe("ask nobody"))
        self.assertEqual([finding["kind"] for finding in found], ["COMMENT"])
        self.assertNotIn("orders@acme.example", found[0]["dev"])
        self.assertIn("or…@acme.example", found[0]["dev"])

    def test_business_values_are_never_normalized_as_ids(self):
        pairs = [
            (LOW, HIGH),
            (str(LOW), str(HIGH)),
            (f"amount > {LOW}", f"amount > {HIGH}"),
            (f"url/{LOW}", f"url/{HIGH}"),
            ("x:  a", "x: a"),
            ({"customer_id": LOW}, {"customer_id": HIGH}),
            (
                {"uuid": "-".join("1" * size for size in (8, 4, 4, 4, 12))},
                {"uuid": "-".join("2" * size for size in (8, 4, 4, 4, 12))},
            ),
        ]
        for dev_value, prod_value in pairs:
            with self.subTest(dev=dev_value):
                self.assertTrue(
                    self.compare({"timeout_ms": dev_value}, {"timeout_ms": prod_value})
                )

    def test_provider_identity_preserved_and_only_provider_suffix_ignored(self):
        dev, prod = "erp_connector_12_34", "erp_connector_98_76"
        self.assertEqual(self.compare(dev, prod, "provider"), [])
        self.assertTrue(self.compare(dev, prod.replace("erp", "crm"), "provider"))
        self.assertTrue(self.compare(dev, prod))  # outside `provider` a suffix is a difference

    def test_object_order_and_known_ui_cache_ignored(self):
        self.assertEqual(self.compare({"a": 1, "b": 2}, {"b": 2, "a": 1}), [])
        self.assertEqual(self.compare([1], [2], "extended_input_schema"), [])

    def test_nested_step_comment_and_missing_step_are_reported(self):
        dev, prod = nested("clock", {"x": 1}, "why"), nested("clock", {"x": 2}, "why not")
        self.assertEqual(
            [(f["kind"], f["step"], f["field"]) for f in drift.compare_code(dev, prod)],
            [("COMMENT", 2, "comment"), ("CODE", 2, "input")],
        )
        only_trigger = {"code": {"number": 0, "provider": "clock"}}
        self.assertEqual(
            [(f["step"], f["field"]) for f in drift.compare_code(dev, only_trigger)],
            [(2, "(step)")],
        )

    def test_called_recipe_is_equal_only_when_it_is_the_paired_one(self):
        self.assertEqual(drift.compare_code(call("3001"), call("4001"), {3001: 4001}), [])
        self.assertTrue(drift.compare_code(call("3001"), call("4002"), {3001: 4001}))
        self.assertTrue(drift.compare_code(call("3001"), call("4001")))

    def test_change_behind_a_mapped_id_is_the_finding(self):
        found = drift.compare_code(call("3001", "closed"), call("4001"), {3001: 4001})
        self.assertEqual([(f["step"], f["field"]) for f in found], [(2, "input")])
        self.assertIn("closed", found[0]["dev"])
        self.assertIn("open", found[0]["prod"])

    def test_custom_connector_suffix_inside_a_datapill_is_ignored_but_not_its_name(self):
        pill = '#{_dp(\'{"pill_type":"output","provider":%s"%s","line":"a1"}\')}'
        dev = nested("clock", {"v": pill % ("", "erp_connector_1_2")})

        def prod(value):
            return nested("clock", {"v": value})

        self.assertEqual(drift.compare_code(dev, prod(pill % (" ", "erp_connector_9_8"))), [])
        self.assertTrue(drift.compare_code(dev, prod(pill % ("", "crm_connector_9_8"))))
        changed = (pill % ("", "erp_connector_9_8")) + " + 1"
        self.assertTrue(drift.compare_code(dev, prod(changed)))

    def test_table_ids_map_one_to_one_and_asset_names_must_agree(self):
        def table(table_id, name):
            return nested("workato_db_table", {"table_id": table_id}, label={"table_id": name})

        seen: drift.IdPairs = {}
        self.assertEqual(
            drift.compare_code(table("1", "Orders"), table("9", "Orders"), {}, seen), []
        )
        self.assertEqual(drift.idmap_findings(seen), [])
        self.assertTrue(drift.compare_code(table("1", "Orders"), table("9", "Invoices"), {}, seen))
        self.assertEqual(
            drift.compare_code(table("2", "Orders"), table("9", "Orders"), {}, seen), []
        )
        self.assertEqual(len(drift.idmap_findings(seen)), 2)

    def test_an_id_without_a_stored_name_is_accepted_but_listed(self):
        def template(template_id, name=None):
            label = {"template_id": name} if name else None
            return nested("workato_template", {"template_id": template_id}, label=label)

        seen: drift.IdPairs = {}
        self.assertEqual(drift.compare_code(template("1"), template("9"), {}, seen), [])
        self.assertEqual(drift.unconfirmed(seen), ["template_id: Dev 1 / Prod 9"])
        # Another step that stores the name confirms the same pair: nothing is left to check.
        named = drift.compare_code(
            template("1", "Order confirmation"), template("9", "Order confirmation"), {}, seen
        )
        self.assertEqual(named, [])
        self.assertEqual(drift.unconfirmed(seen), [])
        # A different name is a difference even when the other step stored none.
        self.assertTrue(
            drift.compare_code(
                template("2", "Order confirmation"), template("8", "Invoice reminder"), {}, seen
            )
        )


class PairingTests(unittest.TestCase):
    def test_equal_names_in_different_folders_keep_distinct_counterparts(self):
        dev = [listed(3001, folders=["A"]), listed(3002, folders=["B"])]
        prod = [listed(4002, folders=["B"]), listed(4001, folders=["A"])]
        pairs, extra = drift.pair_recipes(dev, prod)
        self.assertEqual(
            [(d["id"], p and p["id"]) for d, p in pairs], [(3001, 4001), (3002, 4002)]
        )
        self.assertEqual(extra, [])

    def test_exact_names_and_folder_components_are_not_lossily_normalized(self):
        cases = [
            (listed(3001, "A & B"), listed(4001, "A B")),
            (listed(3001, folders=["A/B"]), listed(4001, folders=["A", "B"])),
        ]
        for dev, prod in cases:
            with self.subTest(dev=dev):
                pairs, extra = drift.pair_recipes([dev], [prod])
                self.assertIsNone(pairs[0][1])
                self.assertEqual(extra, [prod])

    def test_rename_or_move_needs_an_explicit_pair(self):
        dev = listed(3001, NEW_ORDER, [FUNCTIONS])
        prod = listed(4001, CREATE_INVOICE)
        pairs, extra = drift.pair_recipes([dev], [prod])
        self.assertIsNone(pairs[0][1])
        self.assertEqual(extra, [prod])
        self.assertEqual(drift.pair_recipes([dev], [prod], [(3001, 4001)]), ([(dev, prod)], []))

    def test_duplicate_paths_and_ids_fail_in_either_environment(self):
        for records in ([listed(3001), listed(3002)], [listed(3001, "A"), listed(3001, "B")]):
            for dev, prod in ((records, []), ([], records)):
                with self.subTest(dev=dev, prod=prod), self.assertRaises(cli.Error):
                    drift.pair_recipes(dev, prod)

    def test_a_recipe_without_a_valid_identity_fails(self):
        for record in (listed(0), listed("3001"), listed(True), listed(3001, "")):
            with self.subTest(record=record), self.assertRaisesRegex(cli.Error, "identity"):
                drift.pair_recipes([record], [])

    def test_explicit_pairs_cannot_be_outside_project_or_many_to_one(self):
        dev = [listed(3001, "A"), listed(3002, "B")]
        prod = [listed(4001, "X"), listed(4002, "Y")]
        for pairs in (
            [(3001, 9999)],
            [(9999, 4001)],
            [(3001, 4001), (3002, 4001)],
            [(3001, 4001), (3001, 4002)],
        ):
            with self.subTest(pairs=pairs), self.assertRaises(cli.Error):
                drift.pair_recipes(dev, prod, pairs)

    def test_explicit_pair_cannot_silently_steal_an_exact_match(self):
        with self.assertRaisesRegex(cli.Error, "explicitly paired elsewhere"):
            drift.pair_recipes(
                [listed(3001, "Renamed"), listed(3002, "A")], [listed(4001, "A")], [(3001, 4001)]
            )

    def test_missing_counterpart_is_not_replaced_by_another_folder(self):
        dev, prod = listed(3001, folders=["A"]), listed(4001, folders=["B"])
        self.assertEqual(drift.pair_recipes([dev], [prod]), ([(dev, None)], [prod]))

    def test_pair_argument_needs_two_positive_ids(self):
        self.assertEqual(drift.parse_pair("3001:4001"), (3001, 4001))
        for value in ("3001", "3001:4001:5001", "a:b", "0:5", "-1:5", ""):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                drift.parse_pair(value)


class ProjectListingTests(unittest.TestCase):
    def test_project_listing_always_filters_each_folder(self):
        location = {"project_id": 1002, "folder_id": 2002}
        folders = [(2002, []), (2102, [FUNCTIONS])]

        def in_folder(_prof, folder):
            return [{"id": folder, "name": NEW_ORDER, "project_id": 1002, "folder_id": folder}]

        with (
            patch.object(wkrepo, "walk_folders", return_value=folders),
            patch.object(wkrepo, "list_recipes", side_effect=in_folder) as fetch,
        ):
            records, folder_ids = drift.project_recipes("acme-prod", location)
        self.assertEqual(
            [found.args for found in fetch.call_args_list],
            [("acme-prod", 2002), ("acme-prod", 2102)],
        )
        self.assertEqual([record["folder_path"] for record in records], [[], [FUNCTIONS]])
        self.assertEqual(folder_ids, {2002, 2102})

    def test_out_of_project_or_out_of_folder_result_is_rejected(self):
        for fields in ({"project_id": 1009}, {"folder_id": 2009}):
            outside = [{"id": 4001, "name": "A", **fields}]
            with (
                self.subTest(fields=fields),
                patch.object(wkrepo, "walk_folders", return_value=[(2002, [])]),
                patch.object(wkrepo, "list_recipes", return_value=outside),
                self.assertRaises(cli.Error),
            ):
                drift.project_recipes("acme-prod", {"project_id": 1002, "folder_id": 2002})

    def test_recipe_moved_or_renamed_between_list_and_get_is_rejected(self):
        for fields in (
            {"name": "Changed"},
            {"folder_id": 2009},
            {"project_id": 1009},
            {"id": 4009},
        ):
            with (
                self.subTest(fields=fields),
                patch.object(drift, "get_recipe", return_value=fields),
                self.assertRaisesRegex(cli.Error, "changed identity"),
            ):
                drift.checked_recipe("acme-prod", listed(4001), 1002)

    def test_code_stored_as_text_is_parsed(self):
        answer = {"id": 3001, "code": json.dumps({"number": 0, "provider": "clock"})}
        with patch.object(wkrepo, "wk_json", return_value=answer) as wk_json:
            self.assertEqual(drift.get_recipe("acme-dev", 3001)["code"]["provider"], "clock")
        wk_json.assert_called_once_with("acme-dev", "recipes", "get", "3001")


class PropertyTests(unittest.TestCase):
    def test_each_state_is_reported_and_no_value_is_returned(self):
        dev = {"a": "1", "b": "1", "c": "1", "same": "x"}
        prod = {"b": "", "c": "2", "d": "1", "same": "x"}
        states = drift.property_states(dev, prod)
        self.assertEqual(
            states,
            [
                ("a", "missing in Prod"),
                ("b", "blank in Prod"),
                ("c", "value differs"),
                ("d", "only in Prod"),
            ],
        )


class ReportTests(unittest.TestCase):
    """main() on the invented workspace `acme`, with wk and the API faked in `wkrepo`.

    Deployed are `sales-orders` (Dev root folder 2001, Prod 2002) and `common` (Dev 2003, Prod
    2004; it holds the shared connections). `sandbox` (Dev 2005) is in Dev only.
    """

    def setUp(self):
        self.root = support.fake_workspace(self)
        self.folders = {2001: [(2101, FUNCTIONS)], 2002: [(2102, FUNCTIONS)]}
        self.recipes: dict[int, dict[str, Any]] = {}
        self.add_recipe(3001, NEW_ORDER, 2001, 1001)
        self.add_recipe(4001, NEW_ORDER, 2002, 1002)
        self.connections: dict[str, list[dict[str, Any]]] = {
            "dev": [
                {"id": 5001, "name": "[CM] Slack", "folder_id": 2003},
                {"id": 5002, "name": "[SO] ERP", "folder_id": 2001},
                {"id": 5003, "name": "[SO] ERP", "folder_id": 2005},
            ],
            "prod": [
                {"id": 6001, "name": "[CM] Slack", "folder_id": 2004},
                {"id": 6002, "name": "[SO] ERP", "folder_id": 2002},
            ],
        }
        self.properties: dict[tuple[str, int], dict[str, str]] = {}
        self.property_reads: list[tuple[str, int]] = []
        self.calls: list[tuple[str, ...]] = []
        self.fetched: list[int] = []
        support.start(
            self,
            patch.object(drift, "ROOT", self.root),
            patch.object(drift, "OUT_DIR", self.root / "tmp" / "wk" / "prod-drift"),
            patch.object(wkrepo, "wk_json", side_effect=self.wk_json),
            patch.object(wkrepo, "property_values", side_effect=self.property_values),
        )

    def add_recipe(self, recipe_id, name, folder_id, project_id, **fields):
        self.recipes[recipe_id] = {
            "id": recipe_id,
            "name": name,
            "folder_id": folder_id,
            "project_id": project_id,
            "code": {"number": 0, "provider": "clock"},
            "config": [],
            **fields,
        }

    def change_registry(self, change):
        path = wkrepo.registry_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        support.write_json(path, data)

    def wk_json(self, profile, *args):
        """Answer the wk calls of the script from the fixtures; refuse every other call."""
        self.calls.append((profile, *args))
        env = PROFILES[profile]
        match args:
            case ("folders", "list", "--parent", parent):
                return [
                    {"id": child, "name": name}
                    for child, name in self.folders.get(int(parent), [])
                ]
            case ("recipes", "list", *options):
                folder = int(options[options.index("--folder") + 1])
                keys = ("id", "name", "folder_id", "project_id")
                items = [
                    {key: recipe[key] for key in keys}
                    for recipe in self.recipes.values()
                    if recipe["folder_id"] == folder
                ]
                return {"items": items, "has_next": False}
            case ("recipes", "get", recipe_id):
                self.fetched.append(int(recipe_id))
                recipe = copy.deepcopy(self.recipes[int(recipe_id)])
                recipe["code"] = json.dumps(recipe["code"])  # Workato sends the code as text
                return recipe
            case ("connections", "list", *_):
                return {"items": self.connections[env], "has_next": False}
        raise AssertionError(f"unexpected wk call: {args}")

    def property_values(self, env, project_id):
        self.property_reads.append((env, project_id))
        return self.properties.get((env, project_id), {})

    def run_report(self, *args):
        result = support.run_main(drift.main, *args)
        files = list(self.root.rglob("drift-*.json"))
        report = json.loads(files[0].read_text(encoding="utf-8")) if files else None
        for path in files:  # every run of a test starts without a report
            path.unlink()
        return result, report

    def add_common_function(self):
        self.add_recipe(3003, COMMON_INVOICE, 2003, 1003)
        self.add_recipe(4003, COMMON_INVOICE, 2004, 1004)

    def bind(self, dev, prod, provider="slack"):
        self.recipes[3001]["config"] = [{"provider": provider, "account_id": dev}]
        self.recipes[4001]["config"] = [{"provider": provider, "account_id": prod}]

    def test_equal_recipes_pass_and_the_report_is_written_in_tmp(self):
        result, report = self.run_report()
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(self.fetched, [3001, 4001])
        self.assertIn("Full result: tmp/wk/prod-drift/drift-", result.out)
        self.assertEqual(report["projects"][0]["recipes"][0]["findings"], [])

    def test_only_reads_are_run(self):
        self.run_report()
        words = {word for call in self.calls for word in call}
        self.assertFalse(words & {"start", "stop", "update", "delete", "push", "pull", "deploy"})
        self.assertEqual({call[0] for call in self.calls}, {"acme-dev", "acme-prod"})

    def test_links_use_the_app_address_of_the_registry(self):
        self.change_registry(lambda data: data.update(app_url="https://app.eu.workato.com"))
        self.recipes[4001].update(description="changed in Prod", running=True)
        result, _ = self.run_report()
        self.assertEqual(result.code, 1)
        self.assertIn(
            f"{NEW_ORDER} (Prod running)\n"
            "  Dev https://app.eu.workato.com/recipes/3001"
            "  Prod https://app.eu.workato.com/recipes/4001\n"
            "  DESCRIPTION: differs",
            result.out,
        )

    def test_full_report_exposes_both_sides_of_unmatched_rename(self):
        self.recipes[3001]["folder_id"] = 2101  # moved into [SO] Functions in Dev only
        result, report = self.run_report()
        self.assertEqual(result.code, 1)
        kinds = [entry["findings"][0]["kind"] for entry in report["projects"][0]["recipes"]]
        self.assertEqual(kinds, ["MISSING", "PROD_ONLY"])
        self.assertEqual(self.fetched, [])
        self.assertNotIn("recipes/None", result.out)

    def test_explicit_pair_reports_rename_and_move(self):
        self.add_recipe(4001, CREATE_INVOICE, 2102, 1002)
        result, report = self.run_report("--pair", "3001:4001")
        entry = report["projects"][0]["recipes"][0]
        self.assertEqual(result.code, 1)
        self.assertEqual({finding["kind"] for finding in entry["findings"]}, {"NAME", "FOLDER"})
        self.assertEqual(entry["pairing"], "explicit")

    def test_a_pair_outside_every_project_stops_the_run(self):
        result, report = self.run_report("--pair", "9999:4001")
        self.assertEqual(result.code, 2)
        self.assertIn("9999", result.err)
        self.assertIsNone(report)

    def test_selected_recipe_report_does_not_label_unselected_prod_as_extra(self):
        self.add_recipe(3002, CREATE_INVOICE, 2101, 1001)
        self.add_recipe(4002, CREATE_INVOICE, 2102, 1002)
        result, report = self.run_report("--recipe", "3001")
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual([section["project"] for section in report["projects"]], ["sales-orders"])
        self.assertEqual(len(report["projects"][0]["recipes"]), 1)
        self.assertEqual(set(self.fetched), {3001, 4001})

    def test_invalid_selected_id_fails_before_recipe_reads_or_report(self):
        result, report = self.run_report("--recipe", "9999")
        self.assertEqual(result.code, 2)
        self.assertEqual(self.fetched, [])
        self.assertIsNone(report)

    def test_an_unknown_project_is_refused(self):
        result, report = self.run_report("no-such-project")
        self.assertEqual(result.code, 2)
        self.assertIn("unknown project 'no-such-project'", result.err)
        self.assertIsNone(report)

    def test_a_project_that_is_only_in_dev_is_refused(self):
        result, report = self.run_report("sandbox")
        self.assertEqual(result.code, 2)
        self.assertIn("sandbox is not synced in both Dev and Prod", result.err)
        self.assertIsNone(report)

    def test_without_a_workspace_the_run_stops_with_the_next_step(self):
        support.fake_repository(self)
        result, _ = self.run_report()
        self.assertEqual(result.code, 2)
        self.assertIn(wkrepo.NO_WORKSPACE, result.err)

    def test_property_values_are_read_per_environment_and_never_printed(self):
        self.properties = {
            ("dev", 1001): {"orders_channel": "dev-value", "protected_accounts": "same"},
            ("prod", 1002): {"orders_channel": "prod-value", "protected_accounts": "same"},
        }
        result, report = self.run_report()
        self.assertEqual(result.code, 1)
        self.assertEqual(report["projects"][0]["recipes"][0]["findings"], [])
        self.assertIn("orders_channel: value differs", result.out)
        self.assertNotIn("protected_accounts", result.out)
        self.assertEqual(
            sorted(self.property_reads),
            [("dev", 1001), ("dev", 1003), ("prod", 1002), ("prod", 1004)],
        )
        everything = result.out + result.err + json.dumps(report)
        for value in ("dev-value", "prod-value", "same"):
            self.assertNotIn(value, everything)

    def test_a_property_missing_in_prod_alone_fails_the_check(self):
        self.properties = {("dev", 1001): {"orders_channel": "do-not-print"}}
        result, report = self.run_report()
        self.assertEqual(result.code, 1)
        self.assertIn("orders_channel: missing in Prod", result.out)
        self.assertNotIn("do-not-print", result.out + json.dumps(report))

    def test_a_property_the_registry_keeps_in_dev_only_is_expected(self):
        self.change_registry(
            lambda data: data["projects"]["sales-orders"].update(
                dev_only_properties=["orders_channel"]
            )
        )
        self.properties = {("dev", 1001): {"orders_channel": "x"}}
        result, report = self.run_report()
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn("orders_channel", result.out)
        self.assertTrue(report["projects"][0]["properties"][0]["expected"])
        # It is expected to be missing, not to differ: once it exists in Prod it is reported.
        self.properties["prod", 1002] = {"orders_channel": "y"}
        result, _ = self.run_report()
        self.assertEqual(result.code, 1)

    def test_a_connection_of_the_project_itself_is_mapped_across_connector_suffixes(self):
        self.recipes[3001]["config"] = [{"provider": "erp_connector_1_2", "account_id": 5002}]
        self.recipes[4001]["config"] = [{"provider": "erp_connector_7_8", "account_id": 6002}]
        result, _ = self.run_report()
        self.assertEqual(result.code, 0, result.out)

    def test_a_connection_of_the_shared_connections_project_is_mapped(self):
        self.bind(5001, 6001)
        result, _ = self.run_report("sales-orders")
        self.assertEqual(result.code, 0, result.out)

    def test_a_connection_of_another_project_is_not_mapped_without_the_registry_flag(self):
        self.change_registry(lambda data: data["projects"]["common"].pop("shared_connections"))
        self.bind(5001, 6001)
        result, _ = self.run_report("sales-orders")
        self.assertEqual(result.code, 1)
        self.assertIn(
            "BINDING slack: Dev binds '[CM] Slack', which is outside this project and the shared "
            "connections: a deployment leaves the Prod slot empty (now '[CM] Slack')",
            result.out,
        )

    def test_a_binding_outside_every_mapped_folder_and_an_empty_prod_slot_are_reported(self):
        self.bind(5003, None, provider="erp_connector_1_2")
        result, report = self.run_report()
        findings = report["projects"][0]["recipes"][0]["findings"]
        notes = [finding["note"] for finding in findings if finding["kind"] == "BINDING"]
        self.assertEqual(result.code, 1)
        self.assertEqual(len(notes), 2)
        self.assertIn("empty in Prod", notes[0])
        self.assertIn("'[SO] ERP'", notes[1])  # the connection of the Dev-only project

    def test_a_call_into_another_project_is_equal_when_it_is_the_paired_recipe(self):
        self.add_common_function()
        self.recipes[3001]["code"] = call("3003")["code"]
        self.recipes[4001]["code"] = call("4003")["code"]
        result, report = self.run_report("sales-orders")
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual([section["project"] for section in report["projects"]], ["sales-orders"])
        self.recipes[4001]["code"] = call("4009")["code"]
        result, _ = self.run_report("sales-orders")
        self.assertEqual(result.code, 1)

    def test_a_problem_in_a_project_that_was_not_asked_for_does_not_stop_the_check(self):
        self.add_common_function()
        self.add_recipe(4004, COMMON_INVOICE, 2004, 1004)  # the same folder and name twice
        result, report = self.run_report("sales-orders")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("warning: common is left out", result.err)
        self.assertEqual([section["project"] for section in report["projects"]], ["sales-orders"])
        # Asked for, the same problem stops the run.
        result, _ = self.run_report("common")
        self.assertEqual(result.code, 2)
        self.assertIn("common: ambiguous recipe path and name", result.err)

    def test_every_deployed_project_gets_its_own_section(self):
        self.add_common_function()
        self.add_recipe(3005, NEW_ORDER, 2005, 1005)  # in the Dev-only project: never compared
        result, report = self.run_report()
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(
            [section["project"] for section in report["projects"]], ["sales-orders", "common"]
        )
        self.assertIn("== sales-orders: 1 recipes checked", result.out)
        self.assertIn("== common: 1 recipes checked", result.out)
        self.assertNotIn(3005, self.fetched)


if __name__ == "__main__":
    unittest.main()

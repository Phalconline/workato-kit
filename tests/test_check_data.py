"""scripts/check_data.py: strict JSON and a registry the other scripts can rely on."""

import copy
import subprocess
import unittest
from unittest.mock import patch

import check_data
from tests import support


class StrictJsonTests(unittest.TestCase):
    def test_rejects_duplicate_json_keys_and_nonstandard_numbers(self):
        path = support.temp_dir(self, "data-") / "fixture.json"
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', "{"):
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_data.read_json(path)

    def test_accepts_plain_json(self):
        path = support.write_json(support.temp_dir(self, "data-") / "fixture.json", {"a": [1, 2]})
        self.assertEqual(check_data.read_json(path), {"a": [1, 2]})


class RegistryTests(unittest.TestCase):
    def changed(self):
        return copy.deepcopy(support.REGISTRY)

    def refused(self, data, text):
        with self.assertRaisesRegex(check_data.RegistryError, text):
            check_data.validate_registry(data)

    def test_the_registry_of_the_tests_is_valid(self):
        check_data.validate_registry(self.changed())

    def test_exactly_dev_and_prod_are_environments(self):
        for spoil in ("test", "prod"):
            data = self.changed()
            if spoil == "test":
                data["environments"]["test"] = data["environments"]["dev"]
            else:
                del data["environments"]["prod"]
            with self.subTest(case=spoil):
                self.refused(data, "exactly dev and prod")
        data = self.changed()
        data["environments"]["dev"]["profile"] = " "
        self.refused(data, "dev: profile")

    def test_ids_are_positive_whole_numbers_and_unique_in_an_environment(self):
        data = self.changed()
        data["projects"]["common"]["dev"]["project_id"] = 1001
        self.refused(data, "common/dev: project_id")
        data = self.changed()
        data["projects"]["common"]["dev"]["folder_id"] = True
        self.refused(data, "common/dev: folder_id")

    def test_a_snapshot_project_needs_prod_ids_and_test_is_not_a_key(self):
        data = self.changed()
        del data["projects"]["common"]["prod"]
        self.refused(data, "common: needs dev ids, and prod ids")
        data = self.changed()
        data["projects"]["common"]["test"] = {"project_id": 9, "folder_id": 9}
        self.refused(data, "common: unknown key test")

    def test_an_unknown_key_is_an_error_at_every_level(self):
        cases = {
            "registry: unknown key company_domain": lambda data: data.update(company_domain=[]),
            "dev: unknown key snapshot_dir": lambda data: data["environments"]["dev"].update(
                snapshot_dir="x"
            ),
            "common: unknown key shared_connection": lambda data: data["projects"][
                "common"
            ].update(shared_connection=True),
            "common/dev: unknown key id": lambda data: data["projects"]["common"]["dev"].update(
                id=1
            ),
        }
        for text, spoil in cases.items():
            data = self.changed()
            spoil(data)
            with self.subTest(case=text):
                self.refused(data, text)

    def test_optional_settings_have_a_fixed_shape(self):
        workspace = {
            "app_url": "http://app.workato.com",
            "company_domains": ["Acme.Example"],
            "lint_literal_patterns": {"order number": ""},
            "maintainer": 7,
        }
        for key, value in workspace.items():
            data = self.changed()
            data[key] = value
            with self.subTest(setting=key):
                self.refused(data, key)
        project = {
            "shared_connections": "yes",
            "dev_only_properties": "orders_channel",
            "lint_checks": ["ACCOUNT_PROPERTY", ""],
            "lint_guard_exempt": [12],
            "lint_guard_property": ["protected_accounts"],
            "tables": {"Orders": "not an id"},
        }
        for key, value in project.items():
            data = self.changed()
            data["projects"]["common"][key] = value
            with self.subTest(setting=key):
                self.refused(data, f"common: {key}")

    def test_what_the_lint_would_refuse_is_refused_here_first(self):
        cases = {
            "lint_checks knows": {"lint_checks": ["NO_SUCH_CHECK"]},
            "NO_GUARD_PROPERTY needs": {"lint_checks": ["NO_GUARD_PROPERTY"]},
            "NO_GUARD_PROPERTY needs lint_guard_property": {
                "lint_checks": ["NO_GUARD_PROPERTY"],
                "lint_guard_parameter": "id$",
            },
            "lint_guard_parameter must be a regular expression": {"lint_guard_parameter": "id("},
        }
        for text, settings in cases.items():
            data = self.changed()
            data["projects"]["common"].update(settings)
            with self.subTest(case=text):
                self.refused(data, f"common: {text}")
        data = self.changed()
        data["lint_literal_patterns"] = {"order number": "SO-("}
        self.refused(data, "lint_literal_patterns")

    def test_addresses_and_names_that_reach_a_command_or_a_harness_are_checked(self):
        for url in (
            "https://tokens.acme.example",
            "https://app.workato.com@tokens.acme.example",
            "https://app.workato.com/x",
        ):
            data = self.changed()
            data["app_url"] = url
            with self.subTest(app_url=url):
                self.refused(data, "app_url must be the https address of a Workato web app")
        data = self.changed()
        data["app_url"] = "https://app.eu.workato.com"
        check_data.validate_registry(data)
        data["environments"]["prod"]["profile"] = "--raw"
        self.refused(data, "prod: profile may hold letters")

    def test_every_optional_setting_is_accepted_in_its_right_shape(self):
        data = self.changed()
        data["lint_literal_patterns"] = {"order number": r"SO-\d{4}"}
        data["notes"] = "free text"
        data["projects"]["sales-orders"].update(
            dev_only_properties=["orders_channel"],
            lint_checks=["ACCOUNT_PROPERTY", "NO_GUARD_PROPERTY"],
            lint_guard_property="protected_accounts",
            lint_guard_parameter=r"(^|_)account_id$",
            lint_guard_exempt=["[SO] LF | Create invoice"],
            tables={"3001": "Orders"},
            confluence_main_page="4001",
            jira="SO",
            notes="free text",
        )
        check_data.validate_registry(data)

    def test_a_slug_is_lower_case_words_and_not_a_docs_folder(self):
        for slug in ("Sales Orders", "sales_orders", "setup", "knowledge", "-orders"):
            data = self.changed()
            data["projects"][slug] = data["projects"].pop("sandbox")
            with self.subTest(slug=slug):
                self.refused(data, "a slug is lower-case words")


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "data-")
        self.files: list[str] = []
        support.start(
            self,
            patch.object(check_data, "ROOT", self.root),
            patch.object(check_data, "tracked_json_files", side_effect=lambda: sorted(self.files)),
        )

    def add(self, relative, data=None, text=None):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            support.write_json(path, data)
        else:
            path.write_text(text, encoding="utf-8")
        self.files.append(relative)

    def test_a_repository_without_a_workspace_passes_and_says_so(self):
        self.add("pyproject.json", {"a": 1})
        result = support.run_main(check_data.main)
        self.assertEqual(result.code, 0)
        self.assertIn("No workspace yet", result.out)

    def test_a_valid_registry_passes(self):
        self.add("workato/workspaces/acme/registry.json", support.REGISTRY)
        result = support.run_main(check_data.main)
        self.assertEqual(result.code, 0, result.err)
        self.assertNotIn("No workspace yet", result.out)

    def test_a_registry_error_names_the_field_and_never_a_value(self):
        data = copy.deepcopy(support.REGISTRY)
        data["environments"]["dev"]["profile"] = ""
        data["maintainer"] = "do-not-print"
        self.add("workato/workspaces/acme/registry.json", data)
        result = support.run_main(check_data.main)
        self.assertEqual(result.code, 1)
        self.assertIn("workato/workspaces/acme/registry.json: dev: profile", result.err)
        self.assertNotIn("do-not-print", result.out + result.err)

    def test_broken_json_is_reported_by_file_name_only(self):
        self.add("broken.json", text='{"token": "do-not-print", "token": "x"}')
        result = support.run_main(check_data.main)
        self.assertEqual(result.code, 1)
        self.assertIn("Invalid JSON: broken.json", result.err)
        self.assertNotIn("do-not-print", result.out + result.err)

    def test_a_snapshot_project_without_a_prod_copy_is_a_note_not_a_failure(self):
        self.add("workato/workspaces/acme/registry.json", support.REGISTRY)
        self.add("workato/workspaces/acme/projects/common/index.json", {"recipes": []})
        result = support.run_main(check_data.main)
        self.assertEqual(result.code, 0, result.err)
        self.assertIn(
            "note: no Prod copy yet of sales-orders: run scripts/sync_recipes.py prod", result.out
        )
        self.assertNotIn("sandbox", result.out)  # a Dev-only project has no Prod copy

    def test_only_a_registry_in_a_workspace_folder_is_checked_as_one(self):
        self.add("tests/fixtures/registry.json", {"not": "a registry"})
        self.add("workato/workspaces/acme/projects/registry.json", {"not": "a registry"})
        self.assertEqual(support.run_main(check_data.main).code, 0)


class RepositoryTests(unittest.TestCase):
    def test_the_files_come_from_git(self):
        listed = subprocess.CompletedProcess([], 0, stdout="a.json\0b.md\0c/d.json\0", stderr="")
        with patch.object(subprocess, "run", return_value=listed):
            self.assertEqual(check_data.tracked_json_files(), ["a.json", "c/d.json"])


if __name__ == "__main__":
    unittest.main()

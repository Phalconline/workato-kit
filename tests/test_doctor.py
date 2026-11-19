"""scripts/doctor.py: every read of the Workato CLI is reported, with the fix when it fails."""

import shutil
import unittest
from typing import Any
from unittest.mock import patch

import doctor
from lib import cli, wkrepo
from tests import support

PROFILES: list[dict[str, Any]] = [
    {
        "name": "acme-dev",
        "base_url": "https://www.workato.com",
        "store_type": "keychain",
        "active": True,
    },
    {"name": "acme-prod", "base_url": "https://www.workato.com", "store_type": "keychain"},
]
WORKSPACES = {"acme-dev": "Acme (Dev)", "acme-prod": "Acme"}


class DoctorTests(unittest.TestCase):
    def setUp(self):
        support.fake_workspace(self)
        self.profiles = [dict(item) for item in PROFILES]
        self.plugins = "recipe-lint 1.2.0\n"
        self.connected = True
        self.workspaces = dict(WORKSPACES)
        self.denied: set[str] = set()
        self.calls: list[tuple[str, ...]] = []
        wkrepo.profiles.cache_clear()
        self.addCleanup(wkrepo.profiles.cache_clear)
        support.start(
            self,
            patch.object(shutil, "which", return_value="/usr/bin/wk"),
            patch.object(wkrepo, "profiles", side_effect=lambda: self.profiles),
            patch.object(wkrepo, "run_wk", side_effect=self.run_wk),
            patch.object(wkrepo, "wk_json", side_effect=self.wk_json),
            patch.object(wkrepo, "property_names", side_effect=self.property_names),
        )

    def run_wk(self, *args):
        self.calls.append(args)
        return self.plugins

    def wk_json(self, profile, *args):
        self.calls.append((profile, *args))
        if args[:2] == ("auth", "status"):
            return {"connected": self.connected, "workspace": self.workspaces[profile]}
        if args[0] in self.denied:
            raise cli.Error(f"wk -p {profile} {args[0]} failed: HTTP 403")
        if args[:3] == ("folders", "list", "--projects"):
            return [{"id": 2001, "name": "Sales Orders", "project_id": 1001}]
        return {"items": []}

    def property_names(self, env, project_id):
        self.calls.append((env, "properties", str(project_id)))
        if "properties" in self.denied:
            raise cli.Error("Workato answered HTTP 403 to GET /properties")
        return ["orders_channel"]

    def run_doctor(self, *, offline=True):
        with patch.object(doctor, "offline_checks", return_value=offline) as checks:
            result = support.run_main(doctor.main)
        checks.assert_called_once()
        return result

    def test_runs_the_offline_checks_then_reports_each_read(self):
        result = self.run_doctor()
        self.assertEqual(result.code, 0, result.out)
        for line in (
            "ok    recipe-lint plugin",
            "ok    dev profile (acme-dev) reaches Workato",
            "ok    dev: reads recipes",
            "ok    dev: reads projects and folders",
            "ok    dev: reads connections",
            "ok    dev: reads project properties",
            "ok    prod profile (acme-prod) reaches Workato",
            "ok    prod: reads project properties",
        ):
            self.assertIn(line, result.out)
        self.assertNotIn("FAIL", result.out)

    def test_only_reads_are_run(self):
        self.run_doctor()
        words = {word for call in self.calls for word in call}
        self.assertFalse(words & {"start", "stop", "update", "delete", "push", "token", "deploy"})

    def test_a_missing_plugin_gets_the_command_that_registers_it(self):
        self.plugins = "another-plugin 1.0\n"
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("FAIL  recipe-lint is not registered", result.out)
        self.assertIn("wk plugins install recipe-lint", result.out)

    def test_a_profile_that_cannot_connect_fails_and_its_reads_are_skipped(self):
        self.connected = False
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("FAIL  dev profile (acme-dev) cannot reach Workato", result.out)
        self.assertNotIn("dev: reads recipes", result.out)

    def test_a_profile_wk_does_not_know_fails_with_its_name(self):
        self.profiles = [self.profiles[0]]
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("no profile 'acme-prod'", result.out)

    def test_a_profile_of_another_workspace_is_caught(self):
        self.workspaces["acme-prod"] = "Another company"
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn(
            "reaches the workspace 'Another company'; the registry says 'Acme'", result.out
        )

    def test_swapped_profiles_are_caught(self):
        self.profiles[0]["environment"] = "prod"
        self.profiles[1]["environment"] = "dev"
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("dev profile (acme-dev) is signed in to prod according to wk", result.out)
        self.assertIn("look swapped", result.out)

    def test_a_missing_read_privilege_is_named(self):
        self.denied = {"properties"}
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn(
            "FAIL  prod: reads project properties: Workato answered HTTP 403", result.out
        )
        self.assertIn("ok    prod: reads recipes", result.out)

    def test_profiles_in_two_data_centers_fail(self):
        self.profiles[1]["base_url"] = "https://app.eu.workato.com"
        result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("different data centers", result.out)

    def test_the_file_store_and_a_prod_default_profile_are_notes_not_failures(self):
        self.profiles[0]["active"] = False
        self.profiles[1].update(active=True, store_type="file")
        result = self.run_doctor()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("note  prod profile (acme-prod) keeps its token as plain text", result.out)
        self.assertIn("note  wk's default profile is the Prod one", result.out)

    def test_missing_cli_is_reported_after_the_offline_checks_ran(self):
        with patch.object(shutil, "which", return_value=None):
            result = self.run_doctor()
        self.assertEqual(result.code, 1)
        self.assertIn("wk is not installed", result.out)
        self.assertEqual(self.calls, [])

    def test_failed_offline_checks_fail_the_run_but_the_reads_are_still_shown(self):
        result = self.run_doctor(offline=False)
        self.assertEqual(result.code, 1)
        self.assertIn("ok    recipe-lint plugin", result.out)
        self.assertIn("offline checks failed", result.out)


class NoWorkspaceTests(unittest.TestCase):
    def test_without_a_workspace_the_tools_are_checked_and_the_next_step_is_named(self):
        support.fake_repository(self)
        with (
            patch.object(doctor, "offline_checks", return_value=True),
            patch.object(shutil, "which", return_value="/usr/bin/wk"),
            patch.object(wkrepo, "run_wk", return_value="recipe-lint 1.2.0\n"),
        ):
            result = support.run_main(doctor.main)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("ok    recipe-lint plugin", result.out)
        self.assertIn("note  no workspace yet: run scripts/init_workspace.py", result.out)


if __name__ == "__main__":
    unittest.main()

"""scripts/init_workspace.py: a workspace folder from two `wk` profiles, with nothing guessed."""

import copy
import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import check_data
import init_workspace
from lib import wkrepo
from tests import support

PROFILES: list[dict[str, Any]] = [
    {
        "name": "acme-dev",
        "base_url": "https://www.workato.com",
        "store_type": "keychain",
        "environment": "dev",
        "workspace": "Acme (Dev)",
        "workspace_id": 3001,
    },
    {
        "name": "acme-prod",
        "base_url": "https://www.workato.com",
        "store_type": "keychain",
        "environment": "prod",
        "workspace": "Acme",
        "workspace_id": 3002,
    },
]
DEV_PROJECTS = [
    {"name": "Sales Orders", "project_id": 1001, "folder_id": 2001},
    {"name": "Common", "project_id": 1003, "folder_id": 2003},
    {"name": "Sandbox", "project_id": 1005, "folder_id": 2005},
]
PROD_PROJECTS = [
    {"name": "Sales Orders", "project_id": 1002, "folder_id": 2002},
    {"name": "Common", "project_id": 1004, "folder_id": 2004},
]
ARGS = ("acme", "--dev-profile", "acme-dev", "--prod-profile", "acme-prod")
TEMPLATE_NOTES = "# Notes of the {workspace} workspace\n"
TEMPLATE_HARNESS = '{"mcp_servers": [], "name": "{workspace}"}\n'
TEMPLATE_IMAGE = b"\x89PNG {workspace} \xff"


class InitWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = support.fake_repository(self)
        self.folder = self.root / "workato" / "workspaces" / "acme"
        template = self.root / "workato" / "workspace-template"
        (template / "notes").mkdir(parents=True)
        (template / "notes" / "README.md").write_text(TEMPLATE_NOTES, encoding="utf-8")
        (template / "harness.json").write_text(TEMPLATE_HARNESS, encoding="utf-8")
        (template / "notes" / "diagram.png").write_bytes(TEMPLATE_IMAGE)
        self.profiles = copy.deepcopy(PROFILES)
        self.projects = {
            "acme-dev": copy.deepcopy(DEV_PROJECTS),
            "acme-prod": copy.deepcopy(PROD_PROJECTS),
        }
        self.reads: list[str] = []
        self.syncs: list[dict[str, Any]] = []
        self.sync_status = 0
        support.start(
            self,
            patch.object(init_workspace, "ROOT", self.root),
            patch.object(init_workspace, "TEMPLATE", template),
            patch.object(wkrepo, "profiles", side_effect=lambda: self.profiles),
            patch.object(wkrepo, "list_projects", side_effect=self.list_projects),
            patch.object(wkrepo, "run_wk", side_effect=AssertionError("wk was run")),
            patch.object(wkrepo, "token", side_effect=AssertionError("a token was read")),
            patch.object(subprocess, "run", side_effect=self.sync_harness),
        )

    def list_projects(self, profile):
        self.reads.append(profile)
        return copy.deepcopy(self.projects[profile])

    def sync_harness(self, command, **options):
        registry = self.folder / "registry.json"
        self.syncs.append(
            {
                "command": command,
                "cwd": options.get("cwd"),
                "registry": json.loads(registry.read_text("utf-8")) if registry.exists() else None,
            }
        )
        return subprocess.CompletedProcess(command, self.sync_status)

    def init(self, *extra):
        return support.run_main(init_workspace.main, *ARGS, *extra)

    def registry(self):
        return json.loads((self.folder / "registry.json").read_text(encoding="utf-8"))

    def assert_refused(self, result, text):
        self.assertEqual(result.code, 2, result.out)
        self.assertIn(text, result.err)
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.syncs, [])


class FirstRunTests(InitWorkspaceTests):
    def test_the_default_project_without_a_folder_is_listed_and_not_registered(self):
        self.projects["acme-dev"].append({"name": "Home", "project_id": 1009, "folder_id": 0})
        self.projects["acme-prod"].append({"name": "Home", "project_id": 1010, "folder_id": 0})
        result = self.init()
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertNotIn("home", self.registry()["projects"])
        self.assertIn("Not registered: Home. Workato lists its default project", result.out)
        self.assertNotIn("Prod only", result.out)
        check_data.validate_registry(self.registry())

    def test_projects_in_both_environments_get_snapshots_and_a_dev_only_one_does_not(self):
        result = self.init()
        self.assertEqual(result.code, 0, result.out + result.err)
        projects = self.registry()["projects"]
        self.assertEqual(
            projects["sales-orders"],
            {
                "name": "Sales Orders",
                "snapshots": True,
                "dev": {"project_id": 1001, "folder_id": 2001},
                "prod": {"project_id": 1002, "folder_id": 2002},
            },
        )
        self.assertTrue(projects["common"]["snapshots"])
        self.assertEqual(projects["common"]["prod"], {"project_id": 1004, "folder_id": 2004})
        self.assertEqual(
            projects["sandbox"],
            {
                "name": "Sandbox",
                "snapshots": False,
                "dev": {"project_id": 1005, "folder_id": 2005},
            },
        )
        self.assertIn("3 projects in the registry, 2 with a Prod copy.", result.out)
        self.assertIn("In Dev only. After the first deployment of one", result.out)
        self.assertIn("\n  Sandbox (Dev project 1005)\n", result.out)
        self.assertNotIn("--pair", result.out)  # nothing in Prod is left to pair it with

    def test_the_environments_come_from_wk_and_the_us_app_host_is_used_for_links(self):
        self.init()
        registry = self.registry()
        self.assertEqual(
            registry["environments"],
            {
                "dev": {"profile": "acme-dev", "workspace": "Acme (Dev)"},
                "prod": {"profile": "acme-prod", "workspace": "Acme"},
            },
        )
        self.assertEqual(registry["app_url"], "https://app.workato.com")

    def test_another_data_center_keeps_its_own_host_for_links(self):
        for profile in self.profiles:
            profile["base_url"] = "https://app.eu.workato.com"
        self.init()
        self.assertEqual(self.registry()["app_url"], "https://app.eu.workato.com")

    def test_the_registry_it_writes_passes_check_data(self):
        result = self.init(
            "--maintainer",
            "the maintainer",
            "--company-domain",
            "Acme.Example",
            "--company-domain",
            "acme.example",
        )
        self.assertEqual(result.code, 0, result.err)
        registry = self.registry()
        check_data.validate_registry(registry)
        self.assertEqual(registry["maintainer"], "the maintainer")
        self.assertEqual(registry["company_domains"], ["acme.example"])

    def test_it_reads_the_project_list_of_both_environments_and_no_token(self):
        self.init()
        self.assertEqual(sorted(self.reads), ["acme-dev", "acme-prod"])

    def test_help_starts_no_work(self):
        result = support.run_main(init_workspace.main, "--help")
        self.assertEqual(result.code, 0)
        self.assertIn("Exit status", result.out)
        self.assertEqual(self.reads, [])
        self.assertFalse(self.folder.exists())


class TemplateTests(InitWorkspaceTests):
    def test_the_template_is_copied_with_the_workspace_name_filled_in(self):
        result = self.init()
        self.assertIn("Workspace folder: workato/workspaces/acme/ (3 file(s) added)", result.out)
        notes = (self.folder / "notes" / "README.md").read_text(encoding="utf-8")
        self.assertEqual(notes, "# Notes of the acme workspace\n")
        harness = json.loads((self.folder / "harness.json").read_text(encoding="utf-8"))
        self.assertEqual(harness["name"], "acme")

    def test_a_file_that_is_neither_markdown_nor_json_is_copied_as_it_is(self):
        self.init()
        self.assertEqual((self.folder / "notes" / "diagram.png").read_bytes(), TEMPLATE_IMAGE)

    def test_an_existing_file_of_the_workspace_folder_is_never_overwritten(self):
        self.folder.mkdir(parents=True)
        (self.folder / "harness.json").write_text('{"mcp_servers": ["atlassian"]}', "utf-8")
        result = self.init()
        self.assertIn("(2 file(s) added)", result.out)
        harness = (self.folder / "harness.json").read_text(encoding="utf-8")
        self.assertEqual(harness, '{"mcp_servers": ["atlassian"]}')


class SyncHarnessTests(InitWorkspaceTests):
    def test_sync_harness_runs_once_after_the_registry_is_written(self):
        result = self.init()
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(len(self.syncs), 1)
        sync = self.syncs[0]
        self.assertEqual(Path(sync["command"][-1]), self.root / "scripts" / "sync_harness.py")
        self.assertEqual(sync["cwd"], self.root)
        self.assertEqual(sync["registry"], self.registry())
        self.assertIn("docs/setup/new-workspace.md", result.out)

    def test_a_failed_sync_harness_is_an_error(self):
        self.sync_status = 1
        result = self.init()
        self.assertEqual(result.code, 2)
        self.assertIn("scripts/sync_harness.py failed", result.err)
        self.assertTrue((self.folder / "registry.json").exists())


class RefusalTests(InitWorkspaceTests):
    def test_an_unknown_profile_is_refused_with_the_sign_in_command(self):
        self.profiles = [self.profiles[0]]
        result = self.init()
        self.assert_refused(
            result, "wk auth login --name acme-prod --environment prod --region <your region>"
        )
        self.assertEqual(self.reads, [])

    def test_profiles_of_two_data_centers_are_refused(self):
        self.profiles[1]["base_url"] = "https://app.eu.workato.com"
        result = self.init()
        self.assert_refused(result, "different data centers")
        self.assertEqual(self.reads, [])

    def test_two_profiles_that_reach_the_same_environment_are_refused(self):
        self.profiles[1]["workspace_id"] = self.profiles[0]["workspace_id"]
        self.assert_refused(self.init(), "reach the same environment")
        result = support.run_main(
            init_workspace.main, "acme", "--dev-profile", "acme-dev", "--prod-profile", "acme-dev"
        )
        self.assert_refused(result, "reach the same environment")
        self.assertEqual(self.reads, [])

    def test_swapped_profiles_are_refused(self):
        result = support.run_main(
            init_workspace.main, "acme", "--dev-profile", "acme-prod", "--prod-profile", "acme-dev"
        )
        self.assert_refused(result, "swap --dev-profile and --prod-profile")
        self.assertIn("'acme-prod' as signed in to prod", result.err)
        self.assertEqual(self.reads, [])

    def test_profiles_that_cannot_be_told_apart_are_refused(self):
        del self.profiles[1]["workspace_id"]
        self.assert_refused(self.init(), "gives no workspace id")

    def test_a_profile_name_that_could_change_a_command_is_refused(self):
        self.profiles[0]["name"] = "acme dev"
        result = support.run_main(
            init_workspace.main, "acme", "--dev-profile", "acme dev", "--prod-profile", "acme-prod"
        )
        self.assert_refused(result, "holds more than letters, digits")

    def test_a_company_domain_that_is_not_a_domain_is_refused(self):
        for value in ("@acme.example", "https://acme.example", "acme"):
            with self.subTest(value=value):
                self.assert_refused(self.init("--company-domain", value), "--company-domain needs")

    def test_another_workspace_in_the_environment_is_refused(self):
        with patch.dict(os.environ, {"WK_WORKSPACE": "other"}):
            self.assert_refused(self.init(), "WK_WORKSPACE names another workspace")

    def test_a_second_workspace_folder_is_refused(self):
        support.write_json(self.root / "workato" / "workspaces" / "other" / "registry.json", {})
        result = self.init()
        self.assert_refused(result, "workato/workspaces/other/ exists")
        self.assertEqual(self.reads, [])

    def test_a_workspace_name_that_is_not_lower_case_words_and_dashes_is_refused(self):
        for name in ("Acme", "acme_corp", "acme corp", "acme-", "acme--corp", "../acme", ""):
            with self.subTest(name=name):
                result = support.run_main(
                    init_workspace.main,
                    name,
                    "--dev-profile",
                    "acme-dev",
                    "--prod-profile",
                    "acme-prod",
                )
                self.assertEqual(result.code, 2)
                self.assertIn("lower-case words joined by dashes", result.err)
                self.assertIn(f"got '{name}'", result.err)
        self.assertEqual(self.reads, [])
        self.assertFalse((self.root / "workato" / "workspaces").exists())
        self.assertEqual(self.syncs, [])

    def test_a_malformed_pair_or_slug_is_refused(self):
        for option, value in (("--pair", "1001"), ("--pair", "x=1002"), ("--slug", "1001=")):
            with self.subTest(value=value):
                result = self.init(option, value)
                self.assert_refused(result, f"{option} needs PROJECT_ID=VALUE")

    def test_a_pair_with_a_prod_id_that_does_not_exist_is_refused(self):
        result = self.init("--pair", "1005=1009")
        self.assert_refused(result, "Prod has no unpaired project with the id 1009")

    def test_another_profile_than_the_registry_names_is_refused(self):
        self.init()
        before = self.registry()
        self.profiles.append(dict(self.profiles[0], name="acme-dev-2", workspace_id=3003))
        result = support.run_main(
            init_workspace.main,
            "acme",
            "--dev-profile",
            "acme-dev-2",
            "--prod-profile",
            "acme-prod",
        )
        self.assertEqual(result.code, 2)
        self.assertIn("the registry names the dev profile 'acme-dev'", result.err)
        self.assertEqual(self.registry(), before)
        self.assertEqual(len(self.syncs), 1)


class PairingTests(InitWorkspaceTests):
    def test_projects_whose_names_differ_are_not_paired_by_a_guess(self):
        self.projects["acme-prod"][0]["name"] = "Sales orders"
        result = self.init()
        self.assertEqual(result.code, 0, result.out)  # nothing to decide for sure: only a hint
        entry = self.registry()["projects"]["sales-orders"]
        self.assertFalse(entry["snapshots"])
        self.assertNotIn("prod", entry)
        self.assertIn("pair them with --pair DEV_ID=PROD_ID", result.out)
        self.assertIn("\n  Sales Orders (Dev project 1001)\n", result.out)
        self.assertIn("\n  Sales orders (Prod project 1002)\n", result.out)

    def test_a_name_used_twice_in_an_environment_is_never_paired_by_name(self):
        self.projects["acme-prod"].append(
            {"name": "Sales Orders", "project_id": 1006, "folder_id": 2006}
        )
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn("prod", self.registry()["projects"]["sales-orders"])
        self.assertIn("Sales Orders (Prod project 1002)", result.out)
        self.assertIn("Sales Orders (Prod project 1006)", result.out)

    def test_a_pair_wins_over_a_project_with_the_same_name(self):
        self.projects["acme-dev"].append(
            {"name": "Common (new)", "project_id": 1007, "folder_id": 2007}
        )
        result = self.init("--pair", "1007=1004")
        self.assertEqual(result.code, 0, result.out)
        projects = self.registry()["projects"]
        self.assertEqual(projects["common-new"]["prod"]["project_id"], 1004)
        self.assertNotIn("prod", projects["common"])

    def test_a_pair_may_be_written_with_a_colon_as_the_drift_script_takes_it(self):
        self.projects["acme-prod"][0]["name"] = "Sales orders"
        self.assertEqual(self.init("--pair", "1001:1002").code, 0)
        self.assertEqual(self.registry()["projects"]["sales-orders"]["prod"]["project_id"], 1002)

    def test_one_prod_project_cannot_be_paired_twice(self):
        self.assert_refused(
            self.init("--pair", "1001=1002", "--pair", "1003=1002"), "for two Dev projects"
        )
        self.assert_refused(self.init("--pair", "1001=common"), "two project ids")

    def test_a_pair_or_slug_that_names_no_project_is_reported(self):
        result = self.init("--pair", "1099=1004", "--slug", "1098=orders")
        self.assertEqual(result.code, 1)
        self.assertIn("--pair 1099=...: no Dev project 1099", result.out)
        self.assertIn("--slug 1098=...: no new Dev project 1098", result.out)
        # The Prod project a --pair names is kept for it, so nothing took it by name.
        self.assertNotIn("prod", self.registry()["projects"]["common"])
        self.assertEqual(self.init().code, 0)
        self.assertTrue(self.registry()["projects"]["common"]["snapshots"])

    def test_pair_joins_two_projects_whose_names_differ(self):
        self.projects["acme-prod"][0]["name"] = "Sales orders"
        result = self.init("--pair", "1001=1002")
        self.assertEqual(result.code, 0, result.out)
        entry = self.registry()["projects"]["sales-orders"]
        self.assertTrue(entry["snapshots"])
        self.assertEqual(entry["prod"], {"project_id": 1002, "folder_id": 2002})

    def test_a_prod_only_project_is_listed_and_not_registered(self):
        self.projects["acme-dev"].pop()
        self.projects["acme-prod"].append(
            {"name": "Sandbox", "project_id": 1006, "folder_id": 2006}
        )
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("In Prod only, not registered:\n  Sandbox (Prod project 1006)", result.out)
        self.assertEqual(sorted(self.registry()["projects"]), ["common", "sales-orders"])


class SlugTests(InitWorkspaceTests):
    def test_a_reserved_or_empty_slug_is_left_out_and_slug_is_asked_for(self):
        for name in ("Setup", "Conventions", "Knowledge", "Kit", "!!!"):
            self.projects["acme-dev"] = [
                *copy.deepcopy(DEV_PROJECTS),
                {"name": name, "project_id": 1007, "folder_id": 2007},
            ]
            with self.subTest(name=name):
                result = self.init()
                self.assertEqual(result.code, 1)
                self.assertIn("name each with --slug PROJECT_ID=SLUG", result.out)
                self.assertIn(f"{name} (Dev project 1007): the slug", result.out)
                self.assertEqual(
                    sorted(self.registry()["projects"]), ["common", "sales-orders", "sandbox"]
                )

    def test_slug_names_a_project_that_was_left_out(self):
        self.projects["acme-dev"].append({"name": "Setup", "project_id": 1007, "folder_id": 2007})
        self.assertEqual(self.init().code, 1)
        result = self.init("--slug", "1007=setup-tools")
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(self.registry()["projects"]["setup-tools"]["name"], "Setup")

    def test_two_projects_with_one_slug_are_both_left_out(self):
        self.projects["acme-dev"].append(
            {"name": "Sales-Orders", "project_id": 1007, "folder_id": 2007}
        )
        result = self.init()
        self.assertEqual(result.code, 1)
        self.assertIn("Sales Orders (Dev project 1001): the slug 'sales-orders'", result.out)
        self.assertIn("Sales-Orders (Dev project 1007): the slug 'sales-orders'", result.out)
        self.assertEqual(sorted(self.registry()["projects"]), ["common", "sandbox"])

    def test_slug_settles_two_projects_with_one_slug(self):
        self.projects["acme-dev"].append(
            {"name": "Sales-Orders", "project_id": 1007, "folder_id": 2007}
        )
        result = self.init("--slug", "1007=sales-orders-copy")
        self.assertEqual(result.code, 0, result.out)
        projects = self.registry()["projects"]
        self.assertEqual(projects["sales-orders"]["dev"]["project_id"], 1001)
        self.assertEqual(projects["sales-orders-copy"]["dev"]["project_id"], 1007)
        check_data.validate_registry(self.registry())

    def test_a_slug_option_that_cannot_name_a_folder_is_refused(self):
        self.assert_refused(self.init("--slug", "1005=Sand_Box"), "'Sand_Box' is not a slug")
        self.assert_refused(self.init("--slug", "1005=setup"), "'setup' is reserved")

    def test_each_left_out_project_says_why(self):
        self.projects["acme-dev"] += [
            {"name": "Setup", "project_id": 1007, "folder_id": 2007},
            {"name": "\u03a9mega", "project_id": 1008, "folder_id": 2008},
        ]
        result = self.init()
        self.assertEqual(result.code, 1)
        self.assertIn("the slug 'setup' is reserved, it is a folder of docs/", result.out)
        self.assertIn("is not lower-case Latin words and digits joined by dashes", result.out)


class SecondRunTests(InitWorkspaceTests):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.init().code, 0)

    def test_a_registered_project_workato_no_longer_lists_is_reported_and_kept(self):
        self.projects["acme-dev"] = [
            project for project in self.projects["acme-dev"] if project["project_id"] != 1005
        ]
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("Workato does not list it for the Dev profile any more", result.out)
        self.assertIn("sandbox (Dev project 1005)", result.out)
        self.assertIn("sandbox", self.registry()["projects"])

    def test_a_slug_for_a_registered_project_is_reported(self):
        result = self.init("--slug", "1001=orders")
        self.assertEqual(result.code, 1)
        self.assertIn("--slug 1001=...: no new Dev project 1001", result.out)
        self.assertIn("sales-orders", self.registry()["projects"])

    def test_a_registry_that_is_not_json_is_named_not_traced(self):
        (self.folder / "registry.json").write_text('{"projects": {,}', encoding="utf-8")
        result = self.init()
        self.assertEqual(result.code, 2)
        self.assertIn("registry.json is not valid JSON", result.err)

    def test_the_summary_comes_before_what_sync_harness_prints(self):
        result = self.init()
        self.assertLess(
            result.out.index("projects in the registry"), result.out.index("Harness files")
        )

    def test_new_projects_are_added_and_the_entries_kept(self):
        self.projects["acme-dev"].append(
            {"name": "Sales Returns", "project_id": 1007, "folder_id": 2007}
        )
        self.projects["acme-prod"].append(
            {"name": "Sales Returns", "project_id": 1008, "folder_id": 2008}
        )
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("registered: sales-returns", result.out)
        projects = self.registry()["projects"]
        self.assertEqual(sorted(projects), ["common", "sales-orders", "sales-returns", "sandbox"])
        self.assertTrue(projects["sales-returns"]["snapshots"])

    def test_the_prod_half_is_added_and_then_snapshots_switched_on(self):
        self.projects["acme-prod"].append(
            {"name": "Sandbox", "project_id": 1006, "folder_id": 2006}
        )
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("now also in Prod (snapshots switched on): sandbox", result.out)
        entry = self.registry()["projects"]["sandbox"]
        self.assertTrue(entry["snapshots"])
        self.assertEqual(entry["prod"], {"project_id": 1006, "folder_id": 2006})

    def test_a_rename_in_workato_is_reported_and_the_slug_kept(self):
        self.projects["acme-dev"][0]["name"] = "Orders"
        self.projects["acme-prod"][0]["name"] = "Orders"
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("renamed in Workato, slug kept: sales-orders: now 'Orders'", result.out)
        projects = self.registry()["projects"]
        self.assertNotIn("orders", projects)
        self.assertEqual(projects["sales-orders"]["dev"]["project_id"], 1001)
        self.assertEqual(projects["sales-orders"]["prod"]["project_id"], 1002)

    def test_projects_are_matched_by_dev_id_not_by_slug(self):
        registry = self.registry()
        registry["projects"]["orders"] = registry["projects"].pop("sales-orders")
        support.write_json(self.folder / "registry.json", registry)
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(sorted(self.registry()["projects"]), ["common", "orders", "sandbox"])

    def test_an_entry_is_never_removed_and_a_hand_edited_field_survives(self):
        registry = self.registry()
        registry["maintainer"] = "the maintainer"
        registry["description"] = "Edited by hand."
        registry["company_domains"] = ["acme.example"]
        registry["projects"]["common"]["shared_connections"] = True
        registry["projects"]["sales-orders"].update(
            snapshots=False, notes="kept", lint_guard_property="protected_accounts"
        )
        support.write_json(self.folder / "registry.json", registry)
        self.projects = {"acme-dev": [], "acme-prod": []}
        result = self.init()
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(self.registry(), registry)
        check_data.validate_registry(self.registry())

    def test_only_missing_template_files_are_copied_again(self):
        (self.folder / "notes" / "README.md").unlink()
        (self.folder / "harness.json").write_text('{"mcp_servers": ["atlassian"]}', "utf-8")
        result = self.init()
        self.assertIn("(1 file(s) added)", result.out)
        self.assertTrue((self.folder / "notes" / "README.md").exists())
        harness = (self.folder / "harness.json").read_text(encoding="utf-8")
        self.assertEqual(harness, '{"mcp_servers": ["atlassian"]}')


if __name__ == "__main__":
    unittest.main()

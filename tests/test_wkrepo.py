"""lib/wkrepo.py: the workspace folder, the registry, `wk` and the API. Nothing reaches Workato."""

import copy
import http.client
import io
import os
import shutil
import subprocess
import unittest
import urllib.error
from unittest.mock import patch

from lib import cli, wkrepo
from tests import support

PROFILES = [
    {"name": "acme-dev", "base_url": "https://www.workato.com", "store_type": "keychain"},
    {"name": "acme-prod", "base_url": "https://app.eu.workato.com", "store_type": "file"},
]


class WorkspaceTests(unittest.TestCase):
    def test_without_a_workspace_every_lookup_says_how_to_create_one(self):
        support.fake_repository(self)
        self.assertEqual(wkrepo.workspaces(), [])
        for lookup in (wkrepo.workspace, wkrepo.registry, wkrepo.inventory, wkrepo.lookup_tables):
            with (
                self.subTest(lookup=lookup.__name__),
                self.assertRaisesRegex(cli.Error, r"scripts/init_workspace\.py"),
            ):
                lookup()

    def test_the_only_workspace_folder_is_the_workspace(self):
        root = support.fake_workspace(self)
        folder = root / "workato" / "workspaces" / "acme"
        self.assertEqual(wkrepo.workspace(), folder)
        self.assertEqual(wkrepo.registry_path(), folder / "registry.json")
        self.assertEqual(wkrepo.inventory(), folder / "inventory")
        self.assertEqual(wkrepo.lookup_tables(), folder / "lookup-tables")

    def test_a_folder_without_a_registry_is_not_a_workspace(self):
        root = support.fake_workspace(self)
        (root / "workato" / "workspaces" / "notes").mkdir()
        (root / "workato" / "workspaces" / "README.md").write_text("x", encoding="utf-8")
        self.assertEqual(wkrepo.workspaces(), ["acme"])

    def test_several_workspaces_need_a_choice(self):
        root = support.fake_workspace(self)
        support.write_json(root / "workato" / "workspaces" / "other" / "registry.json", {})
        with self.assertRaisesRegex(cli.Error, "several workspaces"):
            wkrepo.workspace()
        with patch.dict(os.environ, {"WK_WORKSPACE": "other"}):
            self.assertEqual(wkrepo.workspace().name, "other")
        with (
            patch.dict(os.environ, {"WK_WORKSPACE": "missing"}),
            self.assertRaisesRegex(cli.Error, "missing"),
        ):
            wkrepo.workspace()

    def test_prod_snapshots_are_in_the_workspace_folder_and_dev_in_the_cache(self):
        root = support.fake_workspace(self)
        self.assertEqual(
            wkrepo.snapshot_dir("prod", "sales-orders"),
            root / "workato" / "workspaces" / "acme" / "projects" / "sales-orders",
        )
        self.assertEqual(wkrepo.snapshot_dir("dev"), root / "tmp" / "wk" / "dev")
        with self.assertRaises(cli.Error):
            wkrepo.snapshot_dir("test")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        support.fake_workspace(self)

    def test_profiles_come_from_the_registry_and_the_environment_overrides_them(self):
        self.assertEqual(wkrepo.profile("dev"), "acme-dev")
        with patch.dict(os.environ, {"WK_PROFILE_DEV": "my-own-profile"}):
            self.assertEqual(wkrepo.profile("dev"), "my-own-profile")
            self.assertEqual(wkrepo.profile("prod"), "acme-prod")

    def test_unknown_environment_and_project_are_expected_failures(self):
        with self.assertRaisesRegex(cli.Error, "unknown environment 'test'"):
            wkrepo.profile("test")
        with self.assertRaisesRegex(cli.Error, "unknown project 'no-such-project'"):
            wkrepo.project("no-such-project")

    def test_only_dev_and_prod_are_environments(self):
        self.assertEqual(wkrepo.environments(), ["dev", "prod"])

    def test_snapshot_projects_are_the_managed_ones_of_that_environment(self):
        self.assertEqual(wkrepo.snapshot_projects("dev"), ["sales-orders", "common"])
        self.assertEqual(wkrepo.snapshot_projects("prod"), ["sales-orders", "common"])

    def test_links_use_the_web_app_of_the_workspace(self):
        self.assertEqual(wkrepo.recipe_url(3001), "https://app.workato.com/recipes/3001")
        registry = {**support.REGISTRY, "app_url": "https://app.eu.workato.com/"}
        support.fake_workspace(self, registry)
        self.assertEqual(wkrepo.recipe_url(3001), "https://app.eu.workato.com/recipes/3001")

    def test_company_domains_default_to_none(self):
        self.assertEqual(wkrepo.company_domains(), ["acme.example"])
        registry = {
            key: value for key, value in support.REGISTRY.items() if key != "company_domains"
        }
        support.fake_workspace(self, registry)
        self.assertEqual(wkrepo.company_domains(), [])

    def test_slug_keeps_only_letters_and_digits(self):
        self.assertEqual(wkrepo.slug("[SO] REC | New order"), "so-rec-new-order")
        self.assertEqual(wkrepo.slug("  A & B / C  "), "a-b-c")


class RegistrySafetyTests(unittest.TestCase):
    def write(self, text):
        root = support.fake_workspace(self)
        (root / "workato" / "workspaces" / "acme" / "registry.json").write_text(text, "utf-8")

    def test_a_registry_that_is_not_json_is_an_expected_failure(self):
        self.write('{"projects": {,}')
        with self.assertRaisesRegex(cli.Error, r"registry\.json is not valid JSON"):
            wkrepo.registry()

    def test_a_registry_without_environments_or_projects_is_refused(self):
        for text in ("[]", '{"projects": {}}', '{"environments": {}, "projects": []}'):
            self.write(text)
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(cli.Error, "needs `environments`"),
            ):
                wkrepo.registry()

    def test_a_project_key_that_could_leave_its_folder_is_refused(self):
        for key in ("../../outside", "a/b", "Sales Orders", ".", ""):
            registry = {**support.REGISTRY, "projects": {key: {"name": "X", "snapshots": True}}}
            support.fake_workspace(self, registry)
            with self.subTest(key=key), self.assertRaisesRegex(cli.Error, "is not a slug"):
                wkrepo.snapshot_projects("prod")

    def test_a_profile_name_that_wk_could_read_as_an_option_is_refused(self):
        registry = copy.deepcopy(support.REGISTRY)
        registry["environments"]["dev"]["profile"] = "--raw"
        support.fake_workspace(self, registry)
        with self.assertRaisesRegex(cli.Error, "the registry holds no usable wk profile for dev"):
            wkrepo.profile("dev")
        with (
            patch.dict(os.environ, {"WK_PROFILE_PROD": "-p x"}),
            self.assertRaisesRegex(cli.Error, "WK_PROFILE_PROD holds no usable wk profile"),
        ):
            wkrepo.profile("prod")

    def test_names_in_another_alphabet_stay_apart(self):
        first, second = wkrepo.slug("\u03a9 Orders"), wkrepo.slug("\u0394 Orders")
        self.assertNotEqual(first, second)
        self.assertEqual(wkrepo.slug("Café Orders_2"), "café-orders-2")
        self.assertEqual(wkrepo.slug("!!! ---"), "")


class ProfileTests(unittest.TestCase):
    def setUp(self):
        wkrepo.profiles.cache_clear()
        self.addCleanup(wkrepo.profiles.cache_clear)
        support.start(self, patch.object(wkrepo, "profiles", return_value=PROFILES))

    def test_the_api_root_comes_from_the_profile_of_wk(self):
        self.assertEqual(wkrepo.base_url("acme-dev"), "https://www.workato.com")
        self.assertEqual(wkrepo.api_url("acme-prod"), "https://app.eu.workato.com/api")

    def test_an_unknown_profile_or_one_without_https_is_refused(self):
        with self.assertRaisesRegex(cli.Error, "no profile 'ghost'"):
            wkrepo.base_url("ghost")
        plain = [{"name": "acme-dev", "base_url": "http://www.workato.com"}]
        with (
            patch.object(wkrepo, "profiles", return_value=plain),
            self.assertRaisesRegex(cli.Error, "https"),
        ):
            wkrepo.base_url("acme-dev")

    def test_a_base_url_that_is_not_a_plain_workato_address_is_refused(self):
        for url in (
            "https://tokens.acme.example",
            "https://app.workato.com@tokens.acme.example",
            "https://www.workato.com.acme.example",
            "https://www.workato.com/api/../x?y=1",
            "https://www.workato.com:8443",
            "http://www.workato.com",
            "",
        ):
            entry = {"name": "acme-dev", "base_url": url}
            with (
                self.subTest(url=url),
                patch.object(wkrepo, "profiles", return_value=[entry]),
                self.assertRaisesRegex(cli.Error, "no https base URL on a Workato host"),
            ):
                wkrepo.base_url("acme-dev")

    def test_every_data_center_of_workato_is_accepted(self):
        for url in (
            "https://www.workato.com",
            "https://app.eu.workato.com/",
            "https://app.workatoapp.cn",
            "https://app.preview.workato.com",
        ):
            entry = {"name": "acme-dev", "base_url": url}
            with self.subTest(url=url), patch.object(wkrepo, "profiles", return_value=[entry]):
                self.assertEqual(wkrepo.base_url("acme-dev"), url.rstrip("/"))

    def test_only_the_us_data_center_has_a_separate_app_host(self):
        self.assertEqual(wkrepo.app_host("https://www.workato.com"), "https://app.workato.com")
        self.assertEqual(
            wkrepo.app_host("https://app.eu.workato.com/"), "https://app.eu.workato.com"
        )

    def test_a_profile_of_the_file_store_gets_the_store_flag(self):
        self.assertEqual(wkrepo.store_flags("acme-dev"), [])
        self.assertEqual(wkrepo.store_flags("acme-prod"), ["--store-type", "file"])
        with patch.object(wkrepo, "run_wk", return_value="{}") as run:
            wkrepo.wk_json("acme-prod", "recipes", "get", "3001")
        self.assertEqual(
            run.call_args.args,
            ("-p", "acme-prod", "--store-type", "file", "recipes", "get", "3001", "-j"),
        )


class WkTests(unittest.TestCase):
    def setUp(self):
        wkrepo.profiles.cache_clear()
        self.addCleanup(wkrepo.profiles.cache_clear)
        support.start(
            self,
            patch.object(shutil, "which", return_value="/usr/bin/wk"),
            patch.object(wkrepo, "store_flags", return_value=[]),
        )

    def answer(self, returncode=0, stdout="", stderr=""):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
        return patch.object(subprocess, "run", return_value=done)

    def test_failed_credential_lookup_never_echoes_what_wk_printed(self):
        with (
            self.answer(1, "sensitive-output", "sensitive-error"),
            self.assertRaises(cli.Error) as raised,
        ):
            wkrepo.token("acme-dev")
        self.assertIn("output withheld", str(raised.exception))
        self.assertNotIn("sensitive", str(raised.exception))

    def test_an_answer_that_is_not_a_token_alone_is_refused_without_being_shown(self):
        # Used as a header, such an answer fails inside the HTTP library with a message quoting it.
        for stdout in ("A new version is available\nreal-token-value\n", "two words\n", "\n", ""):
            with (
                self.subTest(stdout=stdout),
                self.answer(0, stdout),
                self.assertRaises(cli.Error) as raised,
            ):
                wkrepo.token("acme-dev")
            self.assertIn("output withheld", str(raised.exception))
            self.assertNotIn("real-token-value", str(raised.exception))

    def test_the_token_is_returned_without_the_trailing_newline(self):
        with self.answer(0, "token-value\n"):
            self.assertEqual(wkrepo.token("acme-dev"), "token-value")

    def test_the_token_never_shows_in_the_repr_of_the_api(self):
        api = wkrepo.Api("https://www.workato.com/api", "token-value")
        self.assertNotIn("token-value", repr(api))
        self.assertNotIn("token-value", str(api))

    def test_another_failed_command_reports_what_wk_said(self):
        with (
            self.answer(1, "", "recipe not found"),
            self.assertRaisesRegex(cli.Error, "not found"),
        ):
            wkrepo.wk("acme-dev", "recipes", "get", "3001")

    def test_an_html_error_page_is_named_not_printed(self):
        page = "Error: 502\n<!DOCTYPE html>\n<html><body>" + "x" * 5000 + "</body></html>"
        with self.answer(1, "", page), self.assertRaises(cli.Error) as raised:
            wkrepo.wk("acme-dev", "recipes", "list")
        message = str(raised.exception)
        self.assertIn("Error: 502 (Workato answered with an HTML error page)", message)
        self.assertNotIn("<html>", message)
        with self.answer(1, "", "y" * 5000), self.assertRaises(cli.Error) as raised:
            wkrepo.wk("acme-dev", "recipes", "list")
        self.assertLess(len(str(raised.exception)), 500)

    def test_missing_cli_is_an_expected_failure_that_names_the_setup_doc(self):
        with (
            patch.object(shutil, "which", return_value=None),
            patch.object(subprocess, "run") as run,
            self.assertRaisesRegex(cli.Error, r"wk is not installed.*docs/setup/workato\.md"),
        ):
            wkrepo.wk("acme-dev", "recipes", "list")
        run.assert_not_called()

    def test_wk_runs_from_the_repository_root_with_the_profile(self):
        with self.answer(0, "{}") as run:
            wkrepo.wk_json("acme-dev", "recipes", "get", "3001")
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/wk", "-p", "acme-dev", "recipes", "get", "3001", "-j"],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], wkrepo.ROOT)

    def test_an_answer_of_wk_that_is_not_json_is_an_expected_failure(self):
        with (
            self.answer(0, "Update available\n"),
            self.assertRaisesRegex(cli.Error, "did not answer with JSON"),
        ):
            wkrepo.wk_json("acme-dev", "recipes", "list")

    def test_the_profile_listing_is_read_once_and_holds_no_token(self):
        listing = '[{"name": "acme-dev", "base_url": "https://www.workato.com"}]'
        with self.answer(0, listing) as run:
            self.assertEqual(wkrepo.profiles()[0]["name"], "acme-dev")
            wkrepo.profiles()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wk", "auth", "list", "-j"])


class ApiTests(unittest.TestCase):
    """Api.get() with a fake opener: a failed read is an expected failure, never a traceback."""

    def setUp(self):
        self.api = wkrepo.Api("https://www.workato.com/api", "token-value")

    def failing(self, error):
        return patch.object(wkrepo.OPENER, "open", side_effect=error)

    def test_the_request_goes_to_the_api_root_with_the_token_in_the_header_only(self):
        sent = []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

        def open_(request, timeout=None):
            sent.append(request)
            return Answer(b'{"items": []}')

        with patch.object(wkrepo.OPENER, "open", open_):
            self.assertEqual(self.api.get("/recipes", {"page": 2}), {"items": []})
        self.assertEqual(sent[0].full_url, "https://www.workato.com/api/recipes?page=2")
        self.assertEqual(sent[0].get_header("Authorization"), "Bearer token-value")

    def test_an_http_error_names_the_status_and_the_path(self):
        error = urllib.error.HTTPError(
            "https://www.workato.com/api/recipes",
            401,
            "Unauthorized",
            {},  # type: ignore[arg-type]
            io.BytesIO(b"body"),
        )
        with self.failing(error), self.assertRaisesRegex(cli.Error, "HTTP 401 to GET /recipes"):
            self.api.get("/recipes")

    def test_an_unreachable_api_and_a_broken_answer_are_expected_failures(self):
        errors = (
            urllib.error.URLError("no route"),
            TimeoutError("timed out"),
            http.client.IncompleteRead(b""),
        )
        for error in errors:
            with self.subTest(error=error), self.failing(error), self.assertRaises(cli.Error):
                self.api.get("/recipes")

    def test_an_error_that_quotes_the_header_never_reaches_the_message(self):
        error = ValueError("Invalid header value b'Bearer token-value'")
        with self.failing(error), self.assertRaises(cli.Error) as raised:
            self.api.get("/recipes")
        self.assertNotIn("token-value", str(raised.exception))

    def test_the_api_of_an_environment_uses_its_profile(self):
        support.fake_workspace(self)
        with (
            patch.object(wkrepo, "api_url", return_value="https://app.eu.workato.com/api") as url,
            patch.object(wkrepo, "token", return_value="token-value") as token,
        ):
            api = wkrepo.api("prod")
            other = wkrepo.api("prod", "another-profile")
        self.assertEqual(api.url, "https://app.eu.workato.com/api")
        self.assertEqual(
            [call.args[0] for call in url.call_args_list], ["acme-prod", "another-profile"]
        )
        self.assertEqual(token.call_args_list[0].args, ("acme-prod",))
        self.assertEqual(other.token, "token-value")


class ListingTests(unittest.TestCase):
    def setUp(self):
        support.start(self, patch.object(wkrepo, "store_flags", return_value=[]))

    def test_connections_include_later_pages(self):
        pages = [
            {"items": [{"id": 1}], "has_next": True},
            {"items": [{"id": 2}], "has_next": False},
        ]
        with patch.object(wkrepo, "wk_json", side_effect=pages) as fetch:
            self.assertEqual([item["id"] for item in wkrepo.list_connections("acme-dev")], [1, 2])
        self.assertEqual(fetch.call_count, 2)

    def test_recipes_include_later_pages_and_stay_in_the_folder(self):
        pages = [
            {"items": [{"id": 1}], "has_next": True},
            {"items": [{"id": 2}], "has_next": False},
        ]
        with patch.object(wkrepo, "wk_json", side_effect=pages) as fetch:
            self.assertEqual([item["id"] for item in wkrepo.list_recipes("acme-dev", 77)], [1, 2])
        for call in fetch.call_args_list:
            self.assertEqual(call.args[-2:], ("--folder", "77"))
        self.assertEqual([call.args[6] for call in fetch.call_args_list], ["1", "2"])

    def test_projects_are_listed_with_their_root_folder(self):
        listed = [{"id": 2001, "is_project": True, "name": "Sales Orders", "project_id": 1001}]
        with patch.object(wkrepo, "wk_json", return_value=listed) as fetch:
            projects = wkrepo.list_projects("acme-dev")
        self.assertEqual(
            projects, [{"name": "Sales Orders", "project_id": 1001, "folder_id": 2001}]
        )
        self.assertEqual(fetch.call_args.args, ("acme-dev", "folders", "list", "--projects"))

    def test_a_project_listing_of_another_shape_is_an_expected_failure(self):
        with (
            patch.object(wkrepo, "wk_json", return_value=[{"id": 2001, "name": "Sales Orders"}]),
            self.assertRaisesRegex(cli.Error, "did not answer with name, project_id and id"),
        ):
            wkrepo.list_projects("acme-dev")

    def test_folders_are_walked_root_first_with_their_names(self):
        children = {"10": [{"id": 12, "name": "B"}, {"id": 11, "name": "A"}], "11": [], "12": []}

        def listed(_prof, *args):
            return children[args[-1]]

        with patch.object(wkrepo, "wk_json", side_effect=listed):
            self.assertEqual(
                wkrepo.walk_folders("acme-dev", 10), [(10, []), (11, ["A"]), (12, ["B"])]
            )

    def test_property_names_never_carry_the_values(self):
        with patch.object(wkrepo, "property_values", return_value={"b": "secret", "a": "x"}):
            self.assertEqual(wkrepo.property_names("dev", 1001), ["a", "b"])


if __name__ == "__main__":
    unittest.main()

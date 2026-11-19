"""scripts/check_kit_files.py: nothing of a workspace in a file the kit owns.

Every token this check reports is built at run time below, so this file passes the check itself.
"""

import subprocess
import unittest
from unittest.mock import patch

import check_kit_files
from lib import wkrepo
from tests import support

LONG_NUMBER = "1" * 5
FOREIGN_CODE = "[" + "XY" + "]"
PRIVATE_HOST = "intranet." + "corp.invalid"
PRIVATE_ADDRESS = "ops" + "@" + "corp.invalid"
FOREIGN_LETTER = chr(0x03A9)  # a Greek capital letter
FOREIGN_TICKET = "XY" + "-" + "12"
EARLY_DATE = str(2030 - 1) + "-12-31"  # the year before the one the examples use
WEBHOOK = "https:" + "//webhooks" + ".workato.com/webhooks/rest/abc"
ENDPOINT = "https:" + "//apim" + ".workato.com/acme/orders"
HOME_PATHS = ("/" + "Users/someone/kit", "/" + "home/someone/kit", "C:" + "\\" + "Users\\x")


def findings(line):
    return list(check_kit_files.line_findings(line))


class KitOwnedTests(unittest.TestCase):
    def assert_owned(self, paths, owned):
        for path in paths:
            with self.subTest(path=path):
                self.assertIs(check_kit_files.kit_owned(path), owned)

    def test_files_of_the_kit_are_owned(self):
        self.assert_owned(
            (
                "README.md",
                "AGENTS.md",
                "Makefile",
                ".github/workflows/check.yml",
                ".codex/hooks.json",
                ".agents/agents.json",
                ".agents/mcp.json",
                ".agents/roles/architect.md",
                ".agents/skills/workato-recipe-edit/SKILL.md",
                "scripts/sync_recipes.py",
                "scripts/lib/wkrepo.py",
                "tests/test_wkrepo.py",
            ),
            owned=True,
        )

    def test_the_kit_docs_are_owned_and_project_docs_are_not(self):
        self.assert_owned(
            (
                "docs/README.md",
                "docs/setup/new-workspace.md",
                "docs/conventions/python.md",
                "docs/knowledge/README.md",
                "docs/knowledge/workato/platform-notes-tags.md",
            ),
            owned=True,
        )
        self.assert_owned(
            (
                "docs/sales-orders/README.md",
                "docs/sales-orders/recipes/1001-so-rec-new-order.md",
                "docs/common/runbooks/rotate-a-connection.md",
            ),
            owned=False,
        )

    def test_the_workspace_files_among_the_docs_are_not_owned(self):
        self.assert_owned(
            (
                "docs/recipe-index.md",
                "docs/conventions/decisions.md",
                "docs/knowledge/workspace/notes.md",
            ),
            owned=False,
        )

    def test_a_workspace_folder_is_not_owned_but_its_readme_and_the_template_are(self):
        self.assert_owned(
            (
                "workato/workspaces/acme/registry.json",
                "workato/workspaces/acme/harness.json",
                "workato/workspaces/acme/projects/sales-orders/index.json",
            ),
            owned=False,
        )
        self.assert_owned(
            (
                "workato/workspaces/README.md",
                "workato/workspace-template/README.md",
                "workato/workspace-template/harness.json",
                "workato/workspace-template/notes/README.md",
            ),
            owned=True,
        )

    def test_the_scripts_and_tests_of_a_workspace_are_not_owned(self):
        self.assert_owned(("scripts/ws_orders_report.py", "tests/test_ws_orders_report.py"), False)
        self.assert_owned(
            (
                "scripts/lib/ws_checks.py",
                ".agents/skills/ws-returns/SKILL.md",
                ".github/workflows/ws-nightly.yml",
            ),
            owned=False,
        )
        self.assert_owned((".agents/skills/workato-assets/SKILL.md", "scripts/lib/cli.py"), True)

    def test_only_the_readme_of_tmp_is_owned(self):
        self.assert_owned(("tmp/README.md",), owned=True)
        self.assert_owned(("tmp/wk/dev/sales-orders/1001.json", "tmp/analysis/notes.md"), False)

    def test_generated_harness_files_are_not_owned(self):
        self.assert_owned(
            (
                ".claude/settings.json",
                ".claude/skills/recipe-docs/SKILL.md",
                ".claude/agents/architect.md",
                ".codex/agents/architect.toml",
                ".codex/config.toml",
                ".cursor/mcp.json",
                ".gemini/settings.json",
                ".mcp.json",
                ".agents/mcp_config.json",
            ),
            owned=False,
        )

    def test_the_vendor_skills_and_licenses_are_left_to_their_publisher(self):
        self.assert_owned(
            (
                ".agents/skills/search-company-knowledge/SKILL.md",
                ".agents/skills/triage-issue/SKILL.md",
                ".agents/licenses/atlassian.txt",
            ),
            owned=False,
        )


class LineFindingTests(unittest.TestCase):
    def test_a_number_of_five_or_more_digits_is_reported(self):
        for line in (
            f"project {LONG_NUMBER}",
            f"see the recipe {LONG_NUMBER}.",
            f"(id {LONG_NUMBER}, folder 2001)",
            f"docs/sales-orders/recipes/{LONG_NUMBER}.md",
            f"docs/sales-orders/recipes/{LONG_NUMBER}-so-rec-new-order.md",
            f"the recipe #{LONG_NUMBER}",
            f"job-{LONG_NUMBER}",
        ):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [("NUMBER", LONG_NUMBER)])

    def test_short_ids_versions_and_hashes_are_not_numbers(self):
        for line in (
            "project 1001, folder 2001, table 3001",
            "ruff==0.17.5 and mypy 2.4.1",
            f"version 1.2.{LONG_NUMBER}",
            f"a decimal {LONG_NUMBER}.5",
            f"commit 9f{LONG_NUMBER}ab and {LONG_NUMBER}cafe",
            "2030-01-31T09:00:00Z",
        ):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [])

    def test_an_address_outside_the_example_domains_is_reported(self):
        self.assertEqual(findings(f"write to {PRIVATE_ADDRESS}"), [("ADDRESS", PRIVATE_ADDRESS)])

    def test_example_and_public_addresses_are_accepted(self):
        for line in (
            "orders@acme.example",
            "orders@sales.example.com",
            "bot@users.noreply.github.com",
            "brew install python@3.14",
            "uses: actions/checkout@v7",
        ):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [])

    def test_a_host_that_is_not_public_is_reported(self):
        line = "see https://" + PRIVATE_HOST + "/wiki/page"
        self.assertEqual(findings(line), [("HOST", PRIVATE_HOST)])

    def test_public_vendor_and_example_hosts_are_accepted(self):
        for line in (
            "https://docs.python.org/3/library/unittest.html",
            "https://workato.com and https://www.workato.com",
            "https://app.eu.workato.com/recipes/1001",
            "https://docs.workato.com/en/features/environments.html",
            "https://acme.example/orders",
            "https://github.com/example/kit",
            "http://localhost:8080",
        ):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [])

    def test_an_address_that_reaches_one_workspace_at_workato_is_reported(self):
        for line, host in ((WEBHOOK, "webhooks.workato.com"), (ENDPOINT, "apim.workato.com")):
            with self.subTest(host=host):
                self.assertEqual(findings(line), [("HOST", host)])

    def test_a_ticket_key_other_than_the_examples_is_reported(self):
        self.assertEqual(findings(f"see {FOREIGN_TICKET} for it"), [("TICKET", FOREIGN_TICKET)])
        for line in ("SO-1001 and CM-2", "UTF-8, ISO-8601 and SHA-256", "Apache-2.0", "x-12"):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [])

    def test_a_date_before_the_example_year_is_reported_except_in_the_changelog(self):
        self.assertEqual(findings(f"released {EARLY_DATE}"), [("DATE", EARLY_DATE)])
        self.assertEqual(findings("2030-01-31T09:00:00Z and 2031-12-01"), [])
        self.assertEqual(
            list(check_kit_files.line_findings(f"released {EARLY_DATE}", dated=True)), []
        )

    def test_a_bracket_code_other_than_the_examples_is_reported(self):
        line = FOREIGN_CODE + " REC | New order"
        self.assertEqual(findings(line), [("CODE", FOREIGN_CODE)])

    def test_the_example_codes_and_regular_expressions_are_accepted(self):
        for line in (
            "[SO] REC | New order",
            "[CM] Slack",
            "[DEPARTMENT_CODE] [PROJECT_CODE] Name",
            "[A-Z]{2,6} and [a-z0-9-]+",
        ):
            with self.subTest(line=line):
                self.assertEqual(findings(line), [])

    def test_text_in_a_non_latin_script_is_reported(self):
        line = "a note: " + FOREIGN_LETTER
        self.assertEqual(findings(line), [("SCRIPT", "greek capital letter omega")])

    def test_accented_latin_letters_and_symbols_are_accepted(self):
        self.assertEqual(findings("café, Zürich, naïve → done — ok"), [])

    def test_a_home_directory_is_reported(self):
        for path in HOME_PATHS:
            with self.subTest(path=path):
                self.assertEqual(findings(f"cd {path}"), [("PATH", "a home directory")])

    def test_paths_that_belong_to_nobody_are_accepted(self):
        self.assertEqual(findings("~/projects/kit, $HOME/.config and /usr/local/bin/wk"), [])


class FileFindingTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "kit-")
        support.start(self, patch.object(check_kit_files, "ROOT", self.root))

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def findings(self, relative):
        return list(check_kit_files.file_findings(relative))

    def test_each_finding_names_the_file_and_the_line(self):
        self.write("docs/setup/README.md", f"# Setup\n\nproject {LONG_NUMBER}\n")
        self.assertEqual(
            self.findings("docs/setup/README.md"),
            [f"docs/setup/README.md:3: NUMBER {LONG_NUMBER}"],
        )

    def test_agents_md_is_checked_only_above_its_last_section(self):
        text = (
            f"# Rules\n\nSee {FOREIGN_CODE}.\n\n## Rules of this workspace\n\n"
            f"Project {LONG_NUMBER} stays stopped.\n"
        )
        self.write("AGENTS.md", text)
        self.write("CLAUDE.md", text)
        self.assertEqual(self.findings("AGENTS.md"), [f"AGENTS.md:3: CODE {FOREIGN_CODE}"])
        self.assertEqual(
            self.findings("CLAUDE.md"),
            [f"CLAUDE.md:3: CODE {FOREIGN_CODE}", f"CLAUDE.md:7: NUMBER {LONG_NUMBER}"],
        )

    def test_a_finding_in_a_file_name_is_reported(self):
        relative = f"docs/setup/{FOREIGN_CODE} notes.md"
        self.write(relative, "nothing here\n")
        self.assertEqual(
            self.findings(relative), [f"{relative}: CODE in the file name: {FOREIGN_CODE}"]
        )

    def test_a_binary_file_is_skipped(self):
        self.write("workato/workspace-template/diagram.png", b"\x89PNG\xff" + LONG_NUMBER.encode())
        self.assertEqual(self.findings("workato/workspace-template/diagram.png"), [])

    def test_a_file_that_is_gone_is_skipped(self):
        self.assertEqual(self.findings("docs/setup/removed.md"), [])


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.root = support.fake_repository(self)
        self.files: list[str] = []
        support.start(
            self,
            patch.object(check_kit_files, "ROOT", self.root),
            patch.object(check_kit_files, "candidate_files", side_effect=lambda: self.files),
        )

    def add(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.files.append(relative)

    def test_clean_kit_files_pass(self):
        self.add("README.md", "# Kit\n\nProject 1001 in [SO] Functions, orders@acme.example.\n")
        self.add("workato/workspaces/acme/registry.json", f'{{"id": {LONG_NUMBER}}}\n')
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("checked 1 kit-owned files, 0 finding(s)", result.out)
        self.assertNotIn("Move workspace data", result.out)

    def test_a_finding_fails_and_workspace_files_are_not_checked(self):
        self.add("README.md", "# Kit\n")
        self.add("docs/setup/README.md", f"Ask {PRIVATE_ADDRESS}.\n")
        self.add("docs/sales-orders/README.md", f"Project {LONG_NUMBER}\n")
        self.add("tmp/notes.md", f"Project {LONG_NUMBER}\n")
        self.add(".claude/settings.json", f'{{"id": {LONG_NUMBER}}}\n')
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        self.assertIn(f"docs/setup/README.md:1: ADDRESS {PRIVATE_ADDRESS}", result.out)
        self.assertIn("checked 2 kit-owned files, 1 finding(s)", result.out)
        self.assertIn("Move workspace data to workato/workspaces/<workspace>/", result.out)
        self.assertNotIn(LONG_NUMBER, result.out)

    def test_the_names_of_the_repositorys_own_workspace_are_findings_in_kit_files(self):
        registry = {
            "maintainer": "Zeta Lead",
            "company_domains": ["zeta.example"],
            "environments": {
                "dev": {"profile": "zeta-dev", "workspace": "Zeta Trading (Dev)"},
                "prod": {"profile": "zeta-prod", "workspace": "Zeta Trading"},
            },
            "projects": {
                "returns-desk": {"name": "Zeta Returns Desk"},
                "returns": {"name": "Returns"},
            },
        }
        support.write_json(self.root / "workato/workspaces/zeta/registry.json", registry)
        self.add("README.md", "# Kit\n\nReturns are handled by Common.\n")  # one plain word
        self.add("docs/setup/README.md", "Sign in as zeta-prod.\n")
        self.add("docs/setup/tools.md", "Ask the zeta lead of ZETA TRADING.\n")
        self.add(".agents/skills/x/SKILL.md", "The project Zeta Returns Desk, at zeta.example.\n")
        self.add("docs/returns-desk/README.md", "Zeta Returns Desk belongs here.\n")
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        for line in (
            "docs/setup/README.md:1: NAME zeta-prod",
            "docs/setup/tools.md:1: NAME zeta lead",
            "docs/setup/tools.md:1: NAME ZETA TRADING",
            ".agents/skills/x/SKILL.md:1: NAME Zeta Returns Desk",
            ".agents/skills/x/SKILL.md:1: NAME zeta.example",
        ):
            with self.subTest(line=line):
                self.assertIn(line, result.out)
        self.assertIn("checked 4 kit-owned files, 5 finding(s)", result.out)

    def test_the_names_of_the_examples_are_never_findings(self):
        support.write_json(self.root / "workato/workspaces/acme/registry.json", support.REGISTRY)
        registry = {**support.REGISTRY, "maintainer": "Integration lead"}
        support.write_json(self.root / "workato/workspaces/acme/registry.json", registry)
        self.add(
            "README.md", "acme-dev, Acme (Dev), acme.example, Sales Orders, Integration lead\n"
        )
        self.assertEqual(support.run_main(check_kit_files.main).code, 0)

    def test_a_symbolic_link_is_a_finding(self):
        self.add("README.md", "# Kit\n")
        (self.root / "docs").mkdir()
        (self.root / "docs/notes.md").symlink_to(self.root / "README.md")
        self.files.append("docs/notes.md")
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        self.assertIn("docs/notes.md: LINK a symbolic link", result.out)

    def test_only_the_copyright_line_of_the_license_is_not_checked(self):
        notice = f"Copyright (c) 2030 A Person (https://{PRIVATE_HOST}/in/a-person/)\n"
        self.add("LICENSE", "MIT License\n\n" + notice + "\nPermission is hereby granted.\n")
        self.add("README.md", "# Kit\n")
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("checked 2 kit-owned files, 0 finding(s)", result.out)
        for relative in ("docs/setup/README.md", "docs/setup/LICENSE", "LICENSE.md"):
            self.add(relative, notice)
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        for relative in ("docs/setup/README.md", "docs/setup/LICENSE", "LICENSE.md"):
            with self.subTest(relative=relative):
                self.assertIn(f"{relative}:1: HOST {PRIVATE_HOST}", result.out)
        self.assertNotIn("LICENSE:3", result.out)

    def test_any_other_line_of_the_license_is_checked(self):
        self.add("LICENSE", f"MIT License\n\nAsk {PRIVATE_ADDRESS} for a copy.\n")
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        self.assertIn(f"LICENSE:3: ADDRESS {PRIVATE_ADDRESS}", result.out)

    def test_a_license_that_is_a_symbolic_link_is_a_finding(self):
        self.add("README.md", "# Kit\n")
        (self.root / "LICENSE").symlink_to(self.root / "README.md")
        self.files.append("LICENSE")
        result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 1)
        self.assertIn("LICENSE: LINK a symbolic link", result.out)

    def test_the_check_skips_its_own_source(self):
        self.add("scripts/check_kit_files.py", f"CODES = {{'{FOREIGN_CODE}'}}\n")
        own = str(self.root / "scripts" / "check_kit_files.py")
        with patch.object(check_kit_files, "__file__", own):
            result = support.run_main(check_kit_files.main)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("checked 0 kit-owned files, 0 finding(s)", result.out)


class CandidateFileTests(unittest.TestCase):
    def test_the_candidates_are_the_files_git_tracks_or_would_track(self):
        listed = subprocess.CompletedProcess([], 0, stdout="b.md\0a.md\0c/d.py\0", stderr="")
        with (
            patch.object(wkrepo, "executable", return_value="/usr/bin/git"),
            patch.object(subprocess, "run", return_value=listed) as run,
        ):
            self.assertEqual(check_kit_files.candidate_files(), ["a.md", "b.md", "c/d.py"])
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ["ls-files", "-co", "--exclude-standard", "-z"])


if __name__ == "__main__":
    unittest.main()

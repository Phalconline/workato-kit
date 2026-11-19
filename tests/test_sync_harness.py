"""scripts/sync_harness.py: the generated harness files follow their sources and the workspace."""

import copy
import json
import os
import tomllib
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import sync_harness as harness
from lib import cli
from tests import support

ROOT = support.ROOT
CACHE_FILES = (
    "__pycache__/orphan.pyc",
    "example/__pycache__/render.pyc",
    "example/old.pyo",
    "example/.DS_Store",
)
# The kit's Claude settings, cut down to what the tests need.
CLAUDE_SETTINGS: dict[str, Any] = {
    "wk_read_commands": ["recipes get", "folders list"],
    "settings": {
        "permissions": {
            "allow": ["Bash(wk version *)", "Bash(scripts/check.py *)"],
            "deny": ["Bash(wk pull *)", "Bash(wk push *)"],
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "python3.14 scripts/guard_wk.py"}],
                }
            ]
        },
    },
}
# The kit's MCP servers: the Workato one in every repository, the wiki one only when switched on.
MCP_SERVERS: dict[str, Any] = {
    "servers": {
        "workato": {"url": "{app_url}/airo_mcp", "unavailable_at": ["https://app.workatoapp.cn"]},
        "wiki": {"url": "https://wiki.acme.example/mcp", "optional": True, "skills": ["pages"]},
    }
}
MANIFEST = ".agents/generated-files.json"
MCP_FILES = {
    ".mcp.json",
    ".cursor/mcp.json",
    ".agents/mcp_config.json",
    ".gemini/settings.json",
    ".codex/config.toml",
}
WS_RULE = "Bash(scripts/ws_orders.py *)"


def make_repo(
    test: unittest.TestCase,
    registry: dict[str, Any] | None = None,
    harness_json: dict[str, Any] | None = None,
) -> Path:
    """Return a temporary repository with one role and no skills.

    Without a registry it has no workspace; with one it has the workspace `acme`, and its
    harness.json when one is given.
    """
    if registry is None:
        repo = support.fake_repository(test)
    else:
        repo = support.fake_workspace(test, registry)
    (repo / ".agents/skills").mkdir(parents=True)
    (repo / ".agents/roles").mkdir()
    (repo / ".agents/roles/keeper.md").write_text("You keep things.\n", encoding="utf-8")
    role = {
        "description": "Keeps things",
        "instructions_file": ".agents/roles/keeper.md",
        "color": "blue",
    }
    support.write_json(repo / ".agents/mcp.json", MCP_SERVERS)
    support.write_json(repo / ".agents/claude-settings.json", CLAUDE_SETTINGS)
    support.write_json(repo / ".agents/agents.json", {"roles": {"keeper": role}})
    support.write_json(
        repo / ".agents/models.json",
        {"claude": {"keeper": {"model": "sonnet", "effort": "medium"}}},
    )
    if harness_json is not None:
        support.write_json(workspace_folder(repo) / "harness.json", harness_json)
    return repo


def workspace_folder(repo: Path, name: str = support.WORKSPACE) -> Path:
    """Return the folder of a workspace of a temporary repository."""
    return repo / "workato" / "workspaces" / name


def registry(**changes: Any) -> dict[str, Any]:
    """Return a copy of the registry of the tests with some top-level keys changed."""
    return {**copy.deepcopy(support.REGISTRY), **changes}


def add_skill(repo, name="example", frontmatter="name: example\ndescription: Example procedure"):
    """Add a skill with a helper file to the sources of a temporary repository."""
    skill = repo / ".agents/skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n", encoding="utf-8")
    (skill / "render.py").write_text("print('example')\n", encoding="utf-8")


def read_json(repo: Path, relative: str) -> Any:
    """Read a generated JSON file of a temporary repository."""
    return json.loads((repo / relative).read_text(encoding="utf-8"))


def server_urls(repo: Path) -> dict[str, str]:
    """Return the MCP servers Claude Code gets, with their URLs."""
    servers = read_json(repo, ".mcp.json")["mcpServers"]
    return {name: spec["url"] for name, spec in servers.items()}


@unittest.skipUnless(
    (ROOT / ".agents/agents.json").is_file(), "the kit's roles are not in .agents/ yet"
)
class RepositorySourcesTests(unittest.TestCase):
    def test_both_harnesses_share_the_role_and_provider_choices(self):
        rendered = harness.agent_files(ROOT)
        roles = json.loads((ROOT / ".agents/agents.json").read_text(encoding="utf-8"))["roles"]
        models = json.loads((ROOT / ".agents/models.json").read_text(encoding="utf-8"))
        for name, role in roles.items():
            instructions = (ROOT / role["instructions_file"]).read_text(encoding="utf-8").strip()
            claude = rendered[f".claude/agents/{name}.md"]
            codex = rendered[f".codex/agents/{name}.toml"]
            self.assertTrue(claude.endswith(instructions + "\n"))
            config = tomllib.loads(codex)
            self.assertTrue(config["developer_instructions"].endswith(instructions))
            codex_choice = models.get("codex", {}).get(name, {})
            claude_choice = models.get("claude", {}).get(name, {})
            self.assertEqual(config.get("model_reasoning_effort"), codex_choice.get("effort"))
            if claude_choice.get("effort"):
                self.assertIn("effort: " + claude_choice["effort"], claude)
            if not codex_choice.get("model"):
                self.assertNotIn("model", config)
            for skill in role.get("skills", []):
                self.assertIn(skill, config["developer_instructions"])


class SyncTests(unittest.TestCase):
    def test_skill_generation_ignores_local_caches_on_both_sides(self):
        repo = make_repo(self)
        add_skill(repo)
        for folder in (repo / ".agents/skills", repo / ".claude/skills"):
            for relative in CACHE_FILES:
                (folder / relative).parent.mkdir(parents=True, exist_ok=True)
                (folder / relative).write_bytes(b"local-only artifact")
        written = harness.sync(repo)
        self.assertEqual(
            {path for path in written if path.startswith(".claude/skills/")},
            {".claude/skills/example/SKILL.md", ".claude/skills/example/render.py"},
        )
        self.assertEqual(harness.sync(repo, check=True), [])
        for relative in CACHE_FILES:  # a cache in the copy is neither written nor removed
            self.assertTrue((repo / ".claude/skills" / relative).is_file())

    def test_copy_of_a_removed_skill_is_reported_and_deleted(self):
        repo = make_repo(self)
        add_skill(repo)
        harness.sync(repo)
        for path in (repo / ".agents/skills/example").iterdir():
            path.unlink()
        (repo / ".agents/skills/example").rmdir()
        self.assertEqual(
            harness.sync(repo, check=True),
            [
                MANIFEST,
                ".claude/skills/example/SKILL.md (removed)",
                ".claude/skills/example/render.py (removed)",
            ],
        )
        self.assertTrue((repo / ".claude/skills/example/SKILL.md").exists())  # --check kept it
        harness.sync(repo)
        self.assertFalse((repo / ".claude/skills/example").exists())
        self.assertEqual(harness.sync(repo, check=True), [])

    def test_a_file_a_person_put_into_a_generated_folder_is_never_deleted(self):
        repo = make_repo(self)
        harness.sync(repo)
        own = [repo / ".claude/agents/mine.md", repo / ".claude/skills/mine/SKILL.md"]
        for path in own:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("written by a person\n", encoding="utf-8")
        self.assertEqual(harness.sync(repo, check=True), [])
        self.assertEqual(harness.sync(repo), [])
        self.assertTrue(all(path.is_file() for path in own))
        self.assertEqual(
            harness.extra_files(repo, harness.generated(repo)),
            [".claude/agents/mine.md", ".claude/skills/mine/SKILL.md"],
        )

    def test_without_a_record_of_generated_files_nothing_is_deleted(self):
        repo = make_repo(self)
        stray = repo / ".claude/agents/gone.md"
        stray.parent.mkdir(parents=True)
        stray.write_text("left behind\n", encoding="utf-8")
        harness.sync(repo)
        self.assertTrue(stray.is_file())

    def test_the_record_names_every_generated_file_and_itself(self):
        repo = make_repo(self)
        add_skill(repo)
        harness.sync(repo)
        files = read_json(repo, MANIFEST)["files"]
        self.assertEqual(files, sorted(files))
        self.assertIn(MANIFEST, files)
        self.assertIn(".claude/skills/example/SKILL.md", files)
        self.assertEqual(set(files), set(harness.generated(repo)))

    def test_a_record_cannot_make_the_script_delete_another_file(self):
        repo = make_repo(self)
        harness.sync(repo)
        victim = repo / "AGENTS.md"
        victim.write_text("rules\n", encoding="utf-8")
        record = read_json(repo, MANIFEST)
        record["files"] += ["AGENTS.md", "../outside.md", ".agents/roles/keeper.md"]
        support.write_json(repo / MANIFEST, record)
        harness.sync(repo)
        self.assertTrue(victim.is_file())
        self.assertTrue((repo / ".agents/roles/keeper.md").is_file())

    def test_a_symbolic_link_among_the_sources_is_refused(self):
        repo = make_repo(self)
        add_skill(repo)
        secret = repo / "profiles.env"
        secret.write_text("TOKEN=x\n", encoding="utf-8")
        (repo / ".agents/skills/example/ref.md").symlink_to(secret)
        with self.assertRaisesRegex(cli.Error, "ref.md is a symbolic link"):
            harness.sync(repo)
        self.assertFalse((repo / ".claude").exists())

    def test_a_skill_of_an_optional_server_is_copied_only_while_it_is_on(self):
        repo = make_repo(self, registry(), {"mcp_servers": ["wiki"]})
        add_skill(repo, "pages", "name: pages\ndescription: Wiki pages")
        add_skill(repo)
        harness.sync(repo)
        self.assertTrue((repo / ".claude/skills/pages/SKILL.md").is_file())
        support.write_json(workspace_folder(repo) / "harness.json", {"mcp_servers": []})
        stale = harness.sync(repo)
        self.assertIn(".claude/skills/pages/SKILL.md (removed)", stale)
        self.assertFalse((repo / ".claude/skills/pages").exists())
        self.assertTrue((repo / ".claude/skills/example/SKILL.md").is_file())

    def test_agent_file_of_a_removed_role_is_reported_and_deleted(self):
        repo = make_repo(self)
        support.write_json(
            repo / ".agents/models.json", {"claude": {"keeper": {"model": "sonnet"}}}
        )
        gone = {"description": "Gone", "instructions_file": ".agents/roles/keeper.md"}
        roles = read_json(repo, ".agents/agents.json")["roles"]
        support.write_json(
            repo / ".agents/agents.json", {"roles": {**roles, "gone": {**gone, "color": "red"}}}
        )
        harness.sync(repo)
        support.write_json(repo / ".agents/agents.json", {"roles": roles})
        orphans = [repo / ".claude/agents/gone.md", repo / ".codex/agents/gone.toml"]
        self.assertTrue(all(orphan.is_file() for orphan in orphans))

        stale = harness.sync(repo, check=True)
        self.assertIn(".claude/agents/gone.md (removed)", stale)
        self.assertIn(".codex/agents/gone.toml (removed)", stale)
        self.assertTrue(all(orphan.exists() for orphan in orphans))  # --check deletes nothing
        harness.sync(repo)
        self.assertFalse(any(orphan.exists() for orphan in orphans))
        keeper = (repo / ".claude/agents/keeper.md").read_text(encoding="utf-8")
        self.assertIn('model: "sonnet"', keeper)
        self.assertNotIn("effort", keeper)  # not set: the session's effort is inherited
        self.assertEqual(harness.sync(repo, check=True), [])

    def test_an_invalid_source_stops_the_run_before_the_first_write(self):
        cases = {
            "skill without a description": lambda repo: add_skill(
                repo, frontmatter="name: example"
            ),
            "skill named unlike its folder": lambda repo: add_skill(
                repo, frontmatter="name: other\ndescription: x"
            ),
            "role with an unknown skill": lambda repo: support.write_json(
                repo / ".agents/agents.json",
                {
                    "roles": {
                        "keeper": {
                            "description": "Keeps things",
                            "instructions_file": ".agents/roles/keeper.md",
                            "color": "blue",
                            "skills": ["no-such-skill"],
                        }
                    }
                },
            ),
            "effort the provider does not have": lambda repo: support.write_json(
                repo / ".agents/models.json", {"codex": {"keeper": {"effort": "max"}}}
            ),
            "settings source that is not JSON": lambda repo: (
                repo / ".agents/claude-settings.json"
            ).write_text("{", encoding="utf-8"),
        }
        for name, spoil in cases.items():
            repo = make_repo(self)
            spoil(repo)
            with self.subTest(case=name), self.assertRaises(cli.Error):
                harness.sync(repo)
            self.assertFalse((repo / ".mcp.json").exists())
            self.assertFalse((repo / ".claude").exists())


class NoWorkspaceTests(unittest.TestCase):
    def test_a_repository_without_a_workspace_still_gets_every_file(self):
        repo = make_repo(self)
        written = harness.sync(repo)
        self.assertTrue(MCP_FILES | {".claude/settings.json"} <= set(written))
        self.assertEqual(harness.sync(repo, check=True), [])

    def test_without_a_workspace_the_us_app_address_is_used_and_optional_servers_are_off(self):
        repo = make_repo(self)
        harness.sync(repo)
        self.assertEqual(server_urls(repo), {"workato": "https://app.workato.com/airo_mcp"})

    def test_without_a_workspace_wk_reads_are_allowed_only_without_a_profile(self):
        repo = make_repo(self)
        harness.sync(repo)
        allow = read_json(repo, ".claude/settings.json")["permissions"]["allow"]
        self.assertEqual(
            allow,
            [
                "Bash(wk version *)",
                "Bash(scripts/check.py *)",
                "Bash(wk recipes get *)",
                "Bash(wk folders list *)",
            ],
        )
        self.assertFalse(any(" -p " in rule for rule in allow))


class WorkspaceTests(unittest.TestCase):
    def test_the_app_address_of_the_registry_fills_every_mcp_config(self):
        repo = make_repo(self, registry(app_url="https://app.eu.workato.com/"))
        files = harness.mcp_files(repo, harness.workspace(repo))
        self.assertEqual(set(files), MCP_FILES)
        for path, text in files.items():
            with self.subTest(file=path):
                self.assertIn("https://app.eu.workato.com/airo_mcp", text)
                self.assertNotIn("{app_url}", text)
                self.assertNotRegex(text.lower(), r"token|secret|password|authorization")
        codex = tomllib.loads(files[".codex/config.toml"])
        self.assertEqual(
            codex["mcp_servers"]["workato"]["url"], "https://app.eu.workato.com/airo_mcp"
        )

    def test_a_quote_in_a_server_address_cannot_break_the_codex_config(self):
        url = 'https://wiki.acme.example/mcp"\n[injected]\nurl = "x'
        repo = make_repo(self, registry(), {"mcp_servers": ["wiki"]})
        servers = copy.deepcopy(MCP_SERVERS)
        servers["servers"]["wiki"]["url"] = url
        support.write_json(repo / ".agents/mcp.json", servers)
        codex = tomllib.loads(
            harness.mcp_files(repo, harness.workspace(repo))[".codex/config.toml"]
        )
        self.assertEqual(sorted(codex["mcp_servers"]), ["wiki", "workato"])
        self.assertEqual(codex["mcp_servers"]["wiki"]["url"], url)

    def test_an_app_address_that_is_not_workatos_own_is_refused(self):
        for url in (
            "https://tokens.acme.example",
            "https://app.workato.com@tokens.acme.example",
            'https://app.workato.com"\n[injected]',
            "https://app.workato.com/elsewhere",
        ):
            repo = make_repo(self, registry(app_url=url))
            with self.subTest(url=url), self.assertRaisesRegex(cli.Error, "app_url must be"):
                harness.sync(repo)
            self.assertFalse((repo / ".mcp.json").exists())

    def test_names_that_become_file_names_or_table_headers_are_checked(self):
        repo = make_repo(self)
        servers = copy.deepcopy(MCP_SERVERS)
        servers["servers"]["x]\nevil = 1\n[y"] = {"url": "https://wiki.acme.example/mcp"}
        support.write_json(repo / ".agents/mcp.json", servers)
        with self.assertRaisesRegex(cli.Error, "server name"):
            harness.sync(repo)
        support.write_json(repo / ".agents/mcp.json", MCP_SERVERS)
        role = read_json(repo, ".agents/agents.json")["roles"]["keeper"]
        spoiled: dict[str, dict[str, Any]] = {
            "../../escaped": role,
            "keeper": {**role, "color": "blue\npermissionMode: bypassPermissions"},
            "other": {**role, "instructions_file": "../outside.md"},
            "third": {**role, "instructions_file": "AGENTS.md"},
            "fourth": {**role, "skills": ["../x"]},
        }
        for name, changed in spoiled.items():
            support.write_json(repo / ".agents/agents.json", {"roles": {name: changed}})
            with self.subTest(role=name), self.assertRaisesRegex(cli.Error, "^role "):
                harness.sync(repo)
        self.assertFalse((repo / ".claude").exists())

    def test_an_optional_server_is_written_only_when_harness_json_switches_it_on(self):
        repo = make_repo(self, registry(), {"mcp_servers": ["wiki"]})
        harness.sync(repo)
        self.assertEqual(
            server_urls(repo),
            {
                "workato": "https://app.workato.com/airo_mcp",
                "wiki": "https://wiki.acme.example/mcp",
            },
        )
        (workspace_folder(repo) / "harness.json").unlink()
        harness.sync(repo)
        self.assertEqual(list(server_urls(repo)), ["workato"])

    def test_a_server_is_left_out_where_its_vendor_does_not_offer_it(self):
        repo = make_repo(
            self, registry(app_url="https://app.workatoapp.cn"), {"mcp_servers": ["wiki"]}
        )
        harness.sync(repo)
        self.assertEqual(server_urls(repo), {"wiki": "https://wiki.acme.example/mcp"})

    def test_switching_on_a_server_that_is_not_optional_is_an_error(self):
        for name in ("workato", "no-such-server"):
            repo = make_repo(self, registry(), {"mcp_servers": [name]})
            with self.subTest(server=name), self.assertRaisesRegex(cli.Error, "not optional"):
                harness.sync(repo)
            self.assertFalse((repo / ".mcp.json").exists())

    def test_settings_allow_the_base_list_then_wk_reads_per_profile_then_the_workspace_rules(self):
        extra = [WS_RULE, "mcp__wiki__search", WS_RULE]  # duplicates are dropped
        repo = make_repo(self, registry(), {"claude_allow": extra, "mcp_servers": ["wiki"]})
        harness.sync(repo)
        settings = read_json(repo, ".claude/settings.json")
        # The workspace's rules stand first: a kit update then changes lines it never touched.
        self.assertEqual(
            settings["permissions"]["allow"],
            [
                "Bash(wk -p acme-dev recipes get *)",
                "Bash(wk -p acme-dev folders list *)",
                "Bash(wk -p acme-prod recipes get *)",
                "Bash(wk -p acme-prod folders list *)",
                WS_RULE,
                "mcp__wiki__search",
                "Bash(wk version *)",
                "Bash(scripts/check.py *)",
                "Bash(wk recipes get *)",
                "Bash(wk folders list *)",
            ],
        )
        source = CLAUDE_SETTINGS["settings"]
        self.assertEqual(settings["permissions"]["deny"], source["permissions"]["deny"])
        self.assertEqual(settings["hooks"], source["hooks"])

    def test_harness_json_cannot_widen_the_shared_permissions_beyond_its_own_scripts(self):
        refused = (
            "Bash(*)",
            "Bash(wk recipes start *)",
            "Bash(wk -p acme-prod recipes stop *)",
            "Bash(scripts/sync_harness.py *)",
            "Bash(scripts/ws_orders.py *) ; Bash(*)",
            "Bash(scripts/ws_../guard_wk.py *)",
            "mcp__workato",
            "mcp__workato__recipe_builder_push",
            "mcp__wiki__search",  # the wiki server is not switched on in this repository
            "Read(./profiles.env)",
        )
        for rule in refused:
            repo = make_repo(self, registry(), {"claude_allow": [rule]})
            with (
                self.subTest(rule=rule),
                self.assertRaisesRegex(cli.Error, "claude_allow accepts"),
            ):
                harness.sync(repo)
            self.assertFalse((repo / ".claude").exists())

    def test_a_profile_name_that_could_change_a_rule_is_refused(self):
        for name in ("acme dev", "acme-dev *) Bash(wk push", "-p", "", "acme/dev", 7):
            data = registry()
            data["environments"]["prod"]["profile"] = name
            repo = make_repo(self, data)
            with self.subTest(profile=name), self.assertRaisesRegex(cli.Error, "profile name"):
                harness.sync(repo)
            self.assertFalse((repo / ".claude").exists())
        data = registry()
        del data["environments"]["prod"]["profile"]
        with self.assertRaisesRegex(cli.Error, "profile name"):  # an error, not a crash
            harness.sync(make_repo(self, data))
        data = registry()
        data["environments"]["dev"]["profile"] = "acme_dev.2030"
        harness.sync(make_repo(self, data))  # letters, digits, dot, underscore, hyphen pass

    def test_an_app_address_that_is_not_https_is_refused(self):
        for url in ("http://app.workato.com", "app.workato.com", 7):
            repo = make_repo(self, registry(app_url=url))
            with self.subTest(url=url), self.assertRaisesRegex(cli.Error, "https"):
                harness.sync(repo)
            self.assertFalse((repo / ".mcp.json").exists())

    def test_harness_json_of_the_wrong_shape_is_refused(self):
        wrong: list[dict[str, Any]] = [
            {"claude_allow": WS_RULE},
            {"mcp_servers": [7]},
            {"models": []},
            {"models": {"claude": "sonnet"}},
            {"models": {"claude": {"keeper": "sonnet"}}},
            {"mcp_server": ["wiki"]},  # a misspelled key
        ]
        for content in wrong:
            repo = make_repo(self, registry(), content)
            with self.subTest(content=content), self.assertRaisesRegex(cli.Error, "harness.json"):
                harness.sync(repo)

    def test_the_workspace_overrides_the_kit_model_choices_one_field_at_a_time(self):
        models = {"claude": {"keeper": {"effort": "high"}}, "codex": {"keeper": {"model": "x1"}}}
        repo = make_repo(self, registry(), {"models": models})
        harness.sync(repo)
        claude = (repo / ".claude/agents/keeper.md").read_text(encoding="utf-8")
        self.assertIn('model: "sonnet"', claude)  # the kit's default stays
        self.assertIn("effort: high", claude)  # the workspace's choice wins
        codex = tomllib.loads((repo / ".codex/agents/keeper.toml").read_text(encoding="utf-8"))
        self.assertEqual(codex["model"], "x1")
        self.assertNotIn("model_reasoning_effort", codex)

    def test_a_workspace_effort_the_provider_does_not_have_is_refused(self):
        models = {"codex": {"keeper": {"effort": "max"}}}
        repo = make_repo(self, registry(), {"models": models})
        with self.assertRaisesRegex(cli.Error, "codex/keeper: effort"):
            harness.sync(repo)


class SeveralWorkspacesTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo(self, registry())
        other = registry()
        other["environments"]["dev"]["profile"] = "other-dev"
        support.write_json(workspace_folder(self.repo, "other") / "registry.json", other)

    def allow(self) -> list[str]:
        return read_json(self.repo, ".claude/settings.json")["permissions"]["allow"]

    def test_several_workspaces_need_wk_workspace(self):
        with self.assertRaisesRegex(cli.Error, "set WK_WORKSPACE"):
            harness.sync(self.repo)
        self.assertFalse((self.repo / ".claude").exists())

    def test_wk_workspace_picks_the_workspace(self):
        with patch.dict(os.environ, {"WK_WORKSPACE": "other"}):
            harness.sync(self.repo)
        self.assertIn("Bash(wk -p other-dev recipes get *)", self.allow())
        self.assertNotIn("Bash(wk -p acme-dev recipes get *)", self.allow())

    def test_a_wk_workspace_that_names_no_workspace_is_an_error(self):
        with (
            patch.dict(os.environ, {"WK_WORKSPACE": "acme-typo"}),
            self.assertRaisesRegex(cli.Error, "WK_WORKSPACE is 'acme-typo'"),
        ):
            harness.sync(self.repo)


class PermissionChangeTests(unittest.TestCase):
    def settings(self, allow=(), deny=()) -> bytes:
        return json.dumps({"permissions": {"allow": list(allow), "deny": list(deny)}}).encode()

    def test_added_and_removed_rules_are_listed_for_both_lists(self):
        before = self.settings(["Bash(wk version *)", "Bash(old *)"], ["Bash(wk push *)"])
        after = self.settings(["Bash(wk version *)", WS_RULE], ["Bash(wk pull *)"])
        self.assertEqual(
            harness.permission_changes(before, after),
            [
                f"  allow + {WS_RULE}",
                "  allow - Bash(old *)",
                "  deny + Bash(wk pull *)",
                "  deny - Bash(wk push *)",
            ],
        )

    def test_a_new_file_gets_the_number_of_rules(self):
        after = self.settings(["a", "b", "c"], ["d"])
        self.assertEqual(
            harness.permission_changes(None, after), ["  allow: 3 rule(s)", "  deny: 1 rule(s)"]
        )

    def test_a_rewrite_that_keeps_every_rule_says_so(self):
        same = self.settings(["a"], ["b"])
        self.assertEqual(harness.permission_changes(same, same), ["  no permission rule changed"])

    def test_a_file_on_disk_that_is_not_settings_counts_as_one_without_rules(self):
        after = self.settings(["a"], ["b"])
        for before in (b"{", b"[]", b'{"permissions": []}'):
            with self.subTest(before=before):
                self.assertEqual(
                    harness.permission_changes(before, after), ["  allow + a", "  deny + b"]
                )


class CommandLineTests(unittest.TestCase):
    def run_in(self, repo: Path, *argv: str) -> support.Result:
        with patch.object(harness, "ROOT", repo):
            return support.run_main(harness.main, *argv)

    def test_check_exits_1_when_a_file_is_out_of_date_and_writes_nothing(self):
        repo = make_repo(self)
        stale = self.run_in(repo, "--check")
        self.assertEqual(stale.code, 1)
        self.assertIn("out of date: .mcp.json", stale.out)
        self.assertFalse((repo / ".mcp.json").exists())
        self.assertEqual(self.run_in(repo).code, 0)
        current = self.run_in(repo, "--check")
        self.assertEqual(current.code, 0)
        self.assertIn("Harness files are up to date.", current.out)
        self.assertNotIn("Permission rules", current.out)

    def test_a_new_settings_file_reports_how_many_rules_it_has(self):
        repo = make_repo(self, registry())
        result = self.run_in(repo)
        self.assertEqual(result.code, 0)
        self.assertIn("Permission rules of .claude/settings.json:", result.out)
        self.assertIn("  allow: 8 rule(s)\n  deny: 2 rule(s)\n", result.out)
        self.assertNotIn("allow +", result.out)

    def test_a_rewrite_lists_each_rule_added_and_removed(self):
        repo = make_repo(self, registry())
        self.run_in(repo)
        support.write_json(workspace_folder(repo) / "harness.json", {"claude_allow": [WS_RULE]})
        source = copy.deepcopy(CLAUDE_SETTINGS)
        source["settings"]["permissions"]["deny"].remove("Bash(wk push *)")
        support.write_json(repo / ".agents/claude-settings.json", source)

        result = self.run_in(repo)
        self.assertEqual(result.code, 0)
        self.assertIn(
            "Permission rules of .claude/settings.json:\n"
            f"  allow + {WS_RULE}\n"
            "  deny - Bash(wk push *)\n",
            result.out,
        )
        self.assertNotIn("recipes get", result.out)  # a rule that stays is not listed
        self.assertEqual(self.run_in(repo).out, "Nothing to change.\n")

    def test_check_lists_the_rule_changes_and_writes_nothing(self):
        repo = make_repo(self, registry())
        self.run_in(repo)
        before = (repo / ".claude/settings.json").read_bytes()
        support.write_json(workspace_folder(repo) / "harness.json", {"claude_allow": [WS_RULE]})

        result = self.run_in(repo, "--check")
        self.assertEqual(result.code, 1)
        self.assertEqual(
            result.out,
            "out of date: .claude/settings.json\n"
            "Permission rules of .claude/settings.json:\n"
            f"  allow + {WS_RULE}\n"
            "Run scripts/sync_harness.py.\n",
        )
        self.assertEqual((repo / ".claude/settings.json").read_bytes(), before)

    def test_files_other_than_the_settings_print_no_permission_lines(self):
        repo = make_repo(self)
        self.run_in(repo)
        add_skill(repo)
        result = self.run_in(repo)
        self.assertEqual(result.code, 0)
        self.assertNotIn("Permission rules", result.out)

    def test_an_invalid_workspace_is_exit_2_and_writes_nothing(self):
        repo = make_repo(self, registry(app_url="http://app.workato.com"))
        result = self.run_in(repo)
        self.assertEqual(result.code, 2)
        self.assertIn("app_url must be the https address of a Workato web app", result.err)
        self.assertFalse((repo / ".claude").exists())

    def test_unknown_argument_writes_nothing(self):
        with patch.object(harness, "sync") as sync:
            self.assertEqual(support.run_main(harness.main, "--chek").code, 2)
        sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()

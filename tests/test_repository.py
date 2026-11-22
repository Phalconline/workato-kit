"""The hand-written configuration of the repository agrees with the scripts and the rules."""

import json
import re
import subprocess
import unittest

import check_kit_files
from lib import wkrepo
from tests import support

ROOT = support.ROOT
INSTRUCTION_FILE_NAMES = {"claude.md", "agents.md", "gemini.md"}
WORKATO_MCP = "mcp__workato-airo-mcp-server__"
WORKATO_MCP_READS = {
    "docs_get",
    "recipe_get",
    "recipe_list",
    "folder_list",
    "project_list",
    "job_list",
    "job_get",
    "recipe_builder_list_connections",
    "project_privilege_get",
}
FORBIDDEN_WK = {
    "wk pull",
    "wk diff",
    "wk clone",
    "wk push",
    "wk auth token",
    "wk mcp auth-header",
}
# Anchored at the repository root (a leading slash), so they hold wherever the session stands.
# A Read rule also stops an edit of the file and the file commands the harness recognizes.
SECRET_FILES = {
    "Read(/profiles.env)",
    "Read(/.env)",
    "Read(/.env.*)",
    "Read(/.wk/**)",
    "Read(/workato/workspaces/**/master.key)",
    "Read(/workato/workspaces/**/settings.yaml)",
}
IGNORED_BY_OTHER_HARNESSES = {
    "profiles.env",
    ".wk/",
    ".env",
    ".env.*",
    "master.key",
    "settings.yaml",
}
SCRIPT_PATH = re.compile(r"scripts/[A-Za-z0-9_./-]+\.(?:py|sh|js)\b")
# A workspace's own scripts: the docs name invented ones as examples.
WORKSPACE_SCRIPTS = "scripts/ws_"
# Records of what was done at the time: they may name a script that was renamed or removed since.
HISTORICAL = ("docs/conventions/decisions.md", "changelog", "/design/")
SKILLS = ROOT / ".agents" / "skills"
SKILL_TABLE_HEADING = "## Which skill to load"
# A workspace names the skills of its own in the last section of the rules, which it owns: a
# line in the kit's table would conflict with the next update of the kit.
WORKSPACE_RULES_HEADING = check_kit_files.WORKSPACE_SECTION
WORKSPACE_SKILL = "ws-"
BACKTICKED = re.compile(r"`([a-z][a-z0-9-]+)`")


def tracked_files():
    """Return every file git tracks or would track, relative to the repository root."""
    listed = subprocess.run(
        [wkrepo.executable("git"), "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in listed.stdout.split("\0") if path]


def skill_names():
    """Return the name of every skill of the repository."""
    return sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))


def kit_skills(names):
    """Return the skills of the kit among the names: all but the workspace's own."""
    return [name for name in names if not name.startswith(WORKSPACE_SKILL)]


def section(rules, heading):
    """Return one section of the rules, from its heading to the next one; empty without it."""
    found = re.search(rf"^{re.escape(heading)}[ \t]*$", rules, re.MULTILINE)
    return rules[found.end() :].split("\n## ", 1)[0] if found else ""


def table_skills(rules):
    """Return the skills that the rows of the table "Which skill to load" name."""
    table = section(rules, SKILL_TABLE_HEADING)
    rows = [line for line in table.split("\n") if line.startswith("| ") and "`" in line]
    return {name for row in rows for name in BACKTICKED.findall(row.rsplit("|", 2)[-2])}


def workspace_skills(rules):
    """Return the skills of the workspace's own that the last section of the rules names."""
    names = BACKTICKED.findall(section(rules, WORKSPACE_RULES_HEADING))
    return {name for name in names if name.startswith(WORKSPACE_SKILL)}


def unlisted_skills(rules, names):
    """Return the skills that the rules do not name in the section where they belong.

    A skill of the kit belongs in the section "Which skill to load". A skill of the workspace's
    own belongs in the last section, "Rules of this workspace".
    """
    kit = set(BACKTICKED.findall(section(rules, SKILL_TABLE_HEADING)))
    workspace = workspace_skills(rules)
    return {
        name
        for name in names
        if name not in (workspace if name.startswith(WORKSPACE_SKILL) else kit)
    }


def invented_rules(table_skill, workspace_skill):
    """Return rules whose table names one skill and whose last section names another."""
    return (
        f"# Rules\n\n{SKILL_TABLE_HEADING}\n\n| Task | Skill |\n|---|---|\n"
        f"| Do the task | `{table_skill}` |\n\n{WORKSPACE_RULES_HEADING}\n\n"
        f"- **Order recipes.** Load `{workspace_skill}` before you change an order recipe.\n"
    )


class ClaudeSettingsTests(unittest.TestCase):
    def setUp(self):
        settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        self.allow = settings["permissions"]["allow"]
        self.deny = settings["permissions"]["deny"]

    def test_workato_mcp_allowlist_is_explicitly_read_only(self):
        tools = [
            rule.removeprefix(WORKATO_MCP) for rule in self.allow if rule.startswith(WORKATO_MCP)
        ]
        self.assertTrue(tools)
        self.assertEqual(set(tools) - WORKATO_MCP_READS, set())

    def test_script_permissions_name_scripts_that_exist(self):
        rules = [rule for rule in self.allow if rule.startswith("Bash(scripts/")]
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                script = rule.removeprefix("Bash(").rstrip(")").split()[0]
                self.assertTrue((ROOT / script).is_file(), script)

    def test_the_api_helper_is_allowed_for_reads_only(self):
        rules = [rule for rule in self.allow if "scripts/wk_api.py" in rule]
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertRegex(rule, r"^Bash\(scripts/wk_api\.py (dev|prod) GET /[a-z_]+\*\)$")
                self.assertNotIn("properties", rule)

    def test_only_the_reading_commands_of_doc_sync_run_without_asking(self):
        # `stamp` records that a doc was compared with Workato: a claim a person should see.
        rules = sorted(rule for rule in self.allow if "scripts/doc_sync.py" in rule)
        self.assertEqual(
            rules, ["Bash(scripts/doc_sync.py plan *)", "Bash(scripts/doc_sync.py status *)"]
        )

    def test_no_wk_write_is_allowed_without_asking(self):
        writes = {
            "start", "stop", "update", "update-connection", "create", "delete", "deploy", "push",
            "retry", "tags", "copy", "move", "import", "restore", "install", "disconnect", "login",
            "logout", "token", "auth-header",
        }  # fmt: skip
        for rule in self.allow:
            if rule.startswith("Bash(wk "):
                with self.subTest(rule=rule):
                    self.assertEqual(set(rule.removeprefix("Bash(").split()) & writes, set())

    def test_the_forbidden_wk_commands_are_denied(self):
        denied = {rule.removeprefix("Bash(").removesuffix(" *)") for rule in self.deny}
        self.assertEqual(FORBIDDEN_WK - denied, set())

    def test_the_files_that_hold_secrets_may_not_be_read_or_edited(self):
        self.assertEqual(SECRET_FILES - set(self.deny), set())
        for rule in self.deny:
            if rule.startswith(("Read(", "Edit(")):
                with self.subTest(rule=rule):  # `./x` would follow the current directory
                    self.assertRegex(rule, r"^(Read|Edit)\(/[^/]")
        for name in (".cursorignore", ".geminiignore"):
            with self.subTest(file=name):
                lines = set((ROOT / name).read_text(encoding="utf-8").split())
                self.assertEqual(IGNORED_BY_OTHER_HARNESSES - lines, set())

    def test_no_rule_lets_arguments_reach_a_shell(self):
        # make expands a variable given on the command line into its recipe, unquoted:
        # `make test TESTS="x'; any command; '"` would run any command under a `make test *` rule.
        for rule in self.allow:
            if rule.startswith("Bash(make"):
                with self.subTest(rule=rule):
                    self.assertNotIn("*", rule)

    def test_the_scripts_that_widen_permissions_always_ask(self):
        # sync_harness.py writes this very file and init_workspace.py runs it: allowing either
        # without asking would let an agent grant itself permissions through harness.json.
        harness = [rule for rule in self.allow if "sync_harness.py" in rule]
        self.assertEqual(harness, ["Bash(scripts/sync_harness.py --check)"])
        self.assertEqual([rule for rule in self.allow if "init_workspace.py" in rule], [])


class NamingTests(unittest.TestCase):
    def test_no_file_below_the_root_is_named_like_harness_instructions(self):
        # Some file systems ignore case: a harness would load such a file as instructions.
        nested = [
            path
            for path in tracked_files()
            if "/" in path and path.rsplit("/", 1)[-1].lower() in INSTRUCTION_FILE_NAMES
        ]
        self.assertEqual(nested, [])

    def test_the_template_of_a_workspace_is_complete(self):
        template = ROOT / "workato" / "workspace-template"
        harness = json.loads((template / "harness.json").read_text(encoding="utf-8"))
        self.assertEqual(set(harness), {"mcp_servers", "claude_allow", "models"})
        for name in ("README.md", "notes/README.md"):
            with self.subTest(file=name):
                self.assertTrue((template / name).is_file())
        self.assertFalse(
            (template / wkrepo.REGISTRY_NAME).exists(), "the template is no workspace"
        )


class SkillTests(unittest.TestCase):
    def test_the_rules_list_exactly_the_skills_that_exist(self):
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        names = set(skill_names())
        self.assertEqual(
            unlisted_skills(rules, names),
            set(),
            f"skills the rules do not name. One of the kit is named in the table under "
            f"'{SKILL_TABLE_HEADING}'. One of the workspace's own is named as `ws-<name>`, in "
            f"backticks, under '{WORKSPACE_RULES_HEADING}'",
        )
        self.assertEqual(table_skills(rules) - names, set(), "the table lists a missing skill")
        self.assertEqual(
            workspace_skills(rules) - names,
            set(),
            f"'{WORKSPACE_RULES_HEADING}' names a skill that has no folder in .agents/skills/",
        )

    def test_the_table_of_the_kit_names_no_skill_of_the_workspace(self):
        # The kit owns the table: a line of the workspace there conflicts with the next update.
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(
            {name for name in table_skills(rules) if name.startswith(WORKSPACE_SKILL)},
            set(),
            f"a skill of the workspace's own is named under '{WORKSPACE_RULES_HEADING}', not in "
            "the table of the kit",
        )

    def test_the_rules_keep_the_section_of_the_workspace(self):
        # Without its heading, no skill of the workspace's own can be listed.
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(
            WORKSPACE_RULES_HEADING in [line.rstrip() for line in rules.splitlines()],
            f"AGENTS.md has no line '{WORKSPACE_RULES_HEADING}': its last section is gone",
        )

    def test_a_skill_of_the_workspace_named_in_the_last_section_passes(self):
        rules = invented_rules("recipe-docs", "ws-orders")
        self.assertEqual(unlisted_skills(rules, ["recipe-docs", "ws-orders"]), set())
        self.assertEqual(table_skills(rules), {"recipe-docs"})
        self.assertEqual(workspace_skills(rules), {"ws-orders"})

    def test_a_skill_of_the_workspace_missing_from_the_last_section_is_reported(self):
        rules = invented_rules("recipe-docs", "ws-orders")
        names = ["recipe-docs", "ws-orders", "ws-returns"]
        self.assertEqual(unlisted_skills(rules, names), {"ws-returns"})

    def test_a_skill_named_only_in_the_other_section_is_reported(self):
        rules = invented_rules("ws-orders", "recipe-docs")
        names = ["recipe-docs", "ws-orders"]
        self.assertEqual(unlisted_skills(rules, names), {"recipe-docs", "ws-orders"})
        self.assertEqual(table_skills(rules), {"ws-orders"})
        self.assertEqual(workspace_skills(rules), set())

    def test_without_the_last_section_every_skill_of_the_workspace_is_reported(self):
        rules = invented_rules("recipe-docs", "ws-orders").split(WORKSPACE_RULES_HEADING)[0]
        self.assertEqual(unlisted_skills(rules, ["recipe-docs", "ws-orders"]), {"ws-orders"})

    def test_a_heading_with_a_space_after_it_still_starts_its_section(self):
        heading = WORKSPACE_RULES_HEADING
        rules = invented_rules("recipe-docs", "ws-orders").replace(heading, f"{heading} ")
        self.assertEqual(workspace_skills(rules), {"ws-orders"})

    def test_a_skill_of_the_workspace_is_not_a_skill_of_the_kit(self):
        self.assertEqual(kit_skills(["recipe-docs", "ws-orders"]), ["recipe-docs"])

    def test_every_skill_of_the_kit_points_at_the_notes_of_the_workspace(self):
        # A skill of the workspace's own is the workspace's text already: it has no notes file.
        for name in kit_skills(skill_names()):
            with self.subTest(skill=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(f"workato/workspaces/<workspace>/notes/{name}.md", text)

    def test_every_role_has_its_prompt_and_every_prompt_its_role(self):
        roles = json.loads((ROOT / ".agents/agents.json").read_text(encoding="utf-8"))["roles"]
        used = {role["instructions_file"] for role in roles.values()}
        prompts = {
            path.relative_to(ROOT).as_posix() for path in (ROOT / ".agents/roles").glob("*")
        }
        self.assertEqual(used, prompts)
        models = json.loads((ROOT / ".agents/models.json").read_text(encoding="utf-8"))
        for provider, choices in models.items():
            with self.subTest(provider=provider):
                self.assertEqual(set(choices) - set(roles), set(), "a model for a missing role")


class ReferenceTests(unittest.TestCase):
    def test_make_and_ci_run_scripts_that_exist(self):
        for name in ("Makefile", ".github/workflows/check.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for script in SCRIPT_PATH.findall(text):
                with self.subTest(file=name, script=script):
                    self.assertTrue((ROOT / script).is_file())
        workflow = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
        self.assertIn("make dev check", workflow)

    def test_no_current_document_names_a_script_that_does_not_exist(self):
        stale = []
        for path in tracked_files():
            current = path.endswith((".md", ".json", ".toml")) and not any(
                mark in path.lower() for mark in HISTORICAL
            )
            if not current or path.startswith(("workato/workspaces/", "tmp/")):
                continue
            text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
            stale += [
                f"{path}: {script}"
                for script in sorted(set(SCRIPT_PATH.findall(text)))
                if not script.startswith(WORKSPACE_SCRIPTS) and not (ROOT / script).is_file()
            ]
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()

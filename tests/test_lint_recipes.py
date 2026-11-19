"""scripts/lint_recipes.py: the triage of `wk lint` and the house checks, on invented recipes."""

import copy
import json
import subprocess
import sys
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import lint_recipes as lint
from lib import cli, wkrepo
from tests import support

FUNCTION_NAME = "[SO] LF | Create invoice"
GUARD = "protected_accounts"
GUARD_PARAMETER = r"(^|_)account_id$"
GUARDED = lint.Settings(
    checks=frozenset({"NO_GUARD_PROPERTY"}), guard_property=GUARD, guard_parameter=GUARD_PARAMETER
)
# A Slack channel id has the shape C or G plus eight to eleven capitals and digits.
CHANNEL = "C0ABC12DEF"
ACTING = {"provider": "erp", "name": "create_invoice", "input": {"id": "x"}}


def pill(kind, name):
    """Return a property datapill as the builder stores it in a step input."""
    return "#{_dp('" + json.dumps({"pill_type": kind, "property_name": name}) + "')}"


def recipe(*steps, trigger=None, name="[SO] REC | New order"):
    """Return a recipe whose trigger holds the given steps, numbered from 1."""
    block = [{"number": number, **step} for number, step in enumerate(steps, 1)]
    code = {"number": 0, "keyword": "trigger", "provider": "clock", **(trigger or {})}
    return {"name": name, "code": {**code, "block": block}}


def function(*steps, parameters=("account_id",), name=FUNCTION_NAME):
    """Return a recipe function that takes the given parameters."""
    schema = json.dumps([{"name": parameter} for parameter in parameters])
    trigger = {
        "provider": "workato_recipe_function",
        "name": "execute",
        "input": {"parameters_schema_json": schema},
    }
    return recipe(*steps, trigger=trigger, name=name)


def rules(findings):
    return [(finding.level, finding.rule, finding.step) for finding in findings]


def labels(findings):
    """Return the literal labels of MAGIC_LITERAL messages such as `URL 'x' in input 'y'`."""
    return sorted(finding.message.split(" '")[0] for finding in findings)


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.recipe = recipe(
            {"keyword": "foreach", "as": "loop1", "provider": None},
            {"keyword": "action", "as": "call1", "provider": "x", "name": "call_recipe_async"},
        )

    def diagnostic(self, rule, message, pointer="/code/block/1/input/message"):
        source = {"json_pointer": pointer}
        return {"rule_id": rule, "message": message, "level": "warn", "source": source}

    def test_known_false_positives_are_dropped(self):
        dropped = [
            self.diagnostic(
                "DP_LINE_RESOLVES", 'Datapill references step "loop1" which is unknown'
            ),
            self.diagnostic(
                "DP_PATH_RESOLVES", 'field "job_url" is not declared in step "call1" output'
            ),
            self.diagnostic("FORMULA_METHOD_INVALID", 'Unknown formula method "hours"'),
        ]
        self.assertEqual(lint.triage(self.recipe, dropped), [])

    def test_everything_else_is_kept_with_its_ui_step_number(self):
        kept = [
            self.diagnostic(
                "DP_LINE_RESOLVES", 'Datapill references step "ghost" which is unknown'
            ),
            self.diagnostic("DP_PATH_RESOLVES", 'field "other" is not declared in step "call1"'),
            self.diagnostic("DP_PATH_RESOLVES", 'field "job_url" is not declared in step "nope"'),
            self.diagnostic("FORMULA_METHOD_INVALID", 'Unknown formula method "utc"'),
            self.diagnostic("SOME_OTHER_RULE", "anything", pointer="/code"),
        ]
        found = lint.triage(self.recipe, kept)
        self.assertEqual([finding.rule for finding in found], [item["rule_id"] for item in kept])
        self.assertEqual([finding.step for finding in found], [3, 3, 3, 3, 1])

    def test_a_pointer_outside_any_step_gives_no_step_number(self):
        found = lint.triage(self.recipe, [self.diagnostic("X", "y", pointer="/name")])
        self.assertIsNone(found[0].step)


class HouseCheckTests(unittest.TestCase):
    def test_a_pill_on_a_missing_project_property_is_an_error(self):
        step = {"provider": "slack", "input": {"channel": pill("project_property", "old_name")}}
        self.assertEqual(
            rules(lint.house_checks(recipe(step), {"orders_channel"})),
            [("error", "PROPERTY_MISSING", None)],
        )
        self.assertEqual(lint.house_checks(recipe(step), {"old_name"}), [])
        self.assertEqual(lint.house_checks(recipe(step), None), [])  # no names: check skipped

    def test_account_property_is_reported_only_where_the_project_asks_for_it(self):
        step = {"provider": "slack", "input": {"channel": pill("account_property", "channel")}}
        self.assertEqual(lint.house_checks(recipe(step), set()), [])
        settings = lint.Settings(checks=frozenset({"ACCOUNT_PROPERTY"}))
        found = lint.house_checks(recipe(step), set(), settings)
        self.assertEqual(rules(found), [("warn", "ACCOUNT_PROPERTY", None)])

    def test_slack_channel_ids_and_urls_are_magic_literals_everywhere(self):
        step_input = {
            "channel": CHANNEL,
            "url": "https://erp.acme.example/api",
            "text": "see https://erp.acme.example/api again",
            "to": "orders@acme.example",
        }
        found = lint.house_checks(recipe({"provider": "slack", "input": step_input}), set())
        self.assertEqual({finding.rule for finding in found}, {"MAGIC_LITERAL"})
        self.assertEqual({finding.step for finding in found}, {2})
        # The same URL twice is one finding; without company domains an address is no finding.
        self.assertEqual(labels(found), ["Slack channel id", "URL"])

    def test_an_address_of_a_company_domain_is_a_magic_literal(self):
        settings = lint.Settings(company_domains=("acme.example",))
        step_input = {"to": "Orders@ACME.example", "cc": "someone@other.example"}
        found = lint.house_checks(
            recipe({"provider": "erp", "input": step_input}), set(), settings
        )
        self.assertEqual(labels(found), ["company e-mail"])
        self.assertIn("Orders@ACME.example", found[0].message)

    def test_the_registry_patterns_add_their_own_literals(self):
        settings = lint.Settings(extra_literals=(("order number", r"\bSO-\d{4}\b"),))
        step = {"provider": "erp", "input": {"order": "SO-1001", "note": "SO-1001" + "1"}}
        found = lint.house_checks(recipe(step), set(), settings)
        self.assertEqual(rules(found), [("warn", "MAGIC_LITERAL", 2)])
        self.assertEqual(found[0].message, "order number 'SO-1001' in input 'order'")

    def test_literal_patterns_are_the_built_in_ones_plus_the_workspace_ones(self):
        built_in = [label for label, _ in lint.literal_patterns(lint.Settings())]
        self.assertEqual(built_in, ["Slack channel id", "URL"])
        settings = lint.Settings(
            company_domains=("acme.example",), extra_literals=(("order number", "SO-"),)
        )
        found = [label for label, _ in lint.literal_patterns(settings)]
        self.assertEqual(found, ["Slack channel id", "URL", "company e-mail", "order number"])

    def test_a_pattern_that_is_not_a_regular_expression_stops_the_run(self):
        settings = lint.Settings(extra_literals=(("broken", "SO-("),))
        with self.assertRaisesRegex(cli.Error, "lint_literal_patterns.*'broken'"):
            lint.literal_patterns(settings)

    def test_the_slack_pattern_needs_a_digit_and_a_whole_word(self):
        pattern = dict(lint.literal_patterns(lint.Settings()))["Slack channel id"]
        for text in (CHANNEL, f"post to {CHANNEL}.", "G1234ABCD"):
            with self.subTest(text=text):
                self.assertTrue(pattern.search(text))
        for text in ("CUSTOMERS", f"x{CHANNEL}", f"{CHANNEL}_old", "C12"):
            with self.subTest(text=text):
                self.assertFalse(pattern.search(text))

    def test_literals_are_allowed_in_variables_config_steps_and_id_fields(self):
        literal = {"channel": CHANNEL}
        allowed = [
            {"provider": "workato_variable", "input": literal},
            {"provider": "workato_custom_code", "input": {"name": "Config", **literal}},
            {"provider": "workato_custom_code", "input": {"name": "Order settings", **literal}},
            {"provider": "workato_recipe_function", "input": {"flow_id": CHANNEL}},
            {
                "provider": "slack",
                "input": {"channel": pill("project_property", "orders_channel")},
            },
            {"provider": "slack", "input": {"text": "plain words without ids"}},
        ]
        for step in allowed:
            with self.subTest(step=step):
                self.assertEqual(lint.house_checks(recipe(step), {"orders_channel"}), [])

    def test_unfinished_and_skipped_steps_are_reported(self):
        found = lint.house_checks(
            recipe({"provider": "slack", "unfinished": True}, {"provider": "slack", "skip": True}),
            set(),
        )
        self.assertEqual(
            rules(found), [("error", "UNFINISHED_STEP", 2), ("warn", "SKIPPED_STEP", 3)]
        )

    def test_a_function_that_takes_a_guarded_parameter_must_read_the_guard_property(self):
        unguarded = function(ACTING)
        self.assertEqual(lint.house_checks(unguarded, set()), [])  # the check is per project
        found = lint.house_checks(unguarded, set(), GUARDED)
        self.assertEqual(rules(found), [("warn", "NO_GUARD_PROPERTY", None)])
        self.assertEqual(found[0].message, f"takes 'account_id' but never reads {GUARD}")
        for parameter in ("customer_account_id", "account_id"):
            with self.subTest(parameter=parameter):
                taking = function(ACTING, parameters=("order_id", parameter))
                self.assertTrue(lint.house_checks(taking, set(), GUARDED))

    def test_the_guard_is_not_asked_of_recipes_that_do_not_need_it(self):
        guard = {"provider": "erp", "input": {"x": pill("project_property", GUARD)}}
        exempt_name = "[SO] LF | Guarded by its caller"
        settings = lint.Settings(
            checks=GUARDED.checks,
            guard_property=GUARD,
            guard_parameter=GUARD_PARAMETER,
            guard_exempt=frozenset({exempt_name}),
        )
        not_needed = {
            "reads the property": function(ACTING, guard),
            "takes no guarded parameter": function(ACTING, parameters=("order_id",)),
            "the name only holds the word": function(ACTING, parameters=("account_ids_sent",)),
            "only logs and returns": function({"provider": "logger", "input": {"message": "x"}}),
            "guarded by its only caller": function(ACTING, name=exempt_name),
            "not a recipe function": recipe(ACTING),
        }
        for case, checked in not_needed.items():
            with self.subTest(case=case):
                self.assertEqual(lint.house_checks(checked, {GUARD}, settings), [])
        unlisted = function(ACTING, name=exempt_name)
        self.assertTrue(lint.house_checks(unlisted, set(), GUARDED))  # not in the registry

    def test_a_function_with_an_unreadable_parameter_schema_takes_nothing(self):
        broken = function(ACTING)
        broken["code"]["input"]["parameters_schema_json"] = "not json"
        self.assertEqual(lint.house_checks(broken, set(), GUARDED), [])


class RegistryTests(unittest.TestCase):
    """What the registry of the workspace switches on, on an invented workspace."""

    def setUp(self):
        self.root = support.fake_workspace(self)

    def change(self, edit: Callable[[dict[str, Any]], Any]) -> None:
        data = copy.deepcopy(support.REGISTRY)
        edit(data)
        support.write_json(wkrepo.registry_path(), data)

    def test_a_project_without_lint_keys_gets_the_built_in_checks_and_company_domains(self):
        settings = lint.project_settings("sales-orders")
        self.assertEqual(settings, lint.Settings(company_domains=("acme.example",)))

    def test_the_registry_switches_checks_on_per_project(self):
        def edit(data):
            data["lint_literal_patterns"] = {"order number": r"SO-\d{4}"}
            data["projects"]["sales-orders"].update(
                lint_checks=["ACCOUNT_PROPERTY", "NO_GUARD_PROPERTY"],
                lint_guard_property=GUARD,
                lint_guard_parameter=GUARD_PARAMETER,
                lint_guard_exempt=[FUNCTION_NAME],
            )

        self.change(edit)
        settings = lint.project_settings("sales-orders")
        self.assertEqual(settings.checks, frozenset({"ACCOUNT_PROPERTY", "NO_GUARD_PROPERTY"}))
        self.assertEqual(settings.guard_property, GUARD)
        self.assertEqual(settings.guard_parameter, GUARD_PARAMETER)
        self.assertEqual(settings.guard_exempt, frozenset({FUNCTION_NAME}))
        self.assertEqual(settings.extra_literals, (("order number", r"SO-\d{4}"),))
        self.assertEqual(lint.project_settings("common").checks, frozenset())

    def test_the_guard_check_without_its_property_or_parameter_is_refused(self):
        options: tuple[dict[str, str], ...] = (
            {},
            {"lint_guard_property": GUARD},
            {"lint_guard_parameter": "id$"},
        )
        for given in options:

            def edit(data: dict[str, Any], given: dict[str, str] = given) -> None:
                data["projects"]["sales-orders"].update(lint_checks=["NO_GUARD_PROPERTY"], **given)

            self.change(edit)
            with (
                self.subTest(given=given),
                self.assertRaisesRegex(cli.Error, "sales-orders: .*needs lint_guard_property"),
            ):
                lint.project_settings("sales-orders")
        self.change(
            lambda data: data["projects"]["sales-orders"].update(lint_guard_parameter="id(")
        )
        with self.assertRaisesRegex(cli.Error, "lint_guard_parameter is not a regular expression"):
            lint.project_settings("sales-orders")

    def test_an_unknown_check_name_is_refused(self):
        self.change(lambda data: data["projects"]["common"].update(lint_checks=["NO_SUCH_CHECK"]))
        with self.assertRaisesRegex(cli.Error, "common: unknown lint_checks.*NO_SUCH_CHECK"):
            lint.project_settings("common")

    def test_without_company_domains_no_address_is_reported(self):
        self.change(lambda data: data.pop("company_domains"))
        settings = lint.project_settings("sales-orders")
        self.assertEqual(settings.company_domains, ())
        step = {"provider": "erp", "input": {"to": "orders@acme.example"}}
        self.assertEqual(lint.house_checks(recipe(step), set(), settings), [])

    def test_the_kit_lint_configuration_is_used_unless_the_workspace_has_its_own(self):
        self.assertEqual(lint.lint_config(), lint.CONFIG)
        own = support.write_json(wkrepo.workspace() / "wklintrc.json", {"rules": {}})
        self.assertEqual(lint.lint_config(), own)

    def test_the_lint_configuration_of_the_kit_exists(self):
        config = json.loads(lint.CONFIG.read_text(encoding="utf-8"))
        self.assertIn("rules", config)


class DevCopyTests(unittest.TestCase):
    """The functions that read the Dev copy, on an invented workspace with two projects."""

    def setUp(self):
        self.root = support.fake_workspace(self)
        self.cache = wkrepo.DEV_CACHE
        support.start(self, patch.object(lint, "LINT_OUTPUT", self.root / "tmp" / "lint.json"))
        self.add("sales-orders", 3001, recipe({"provider": "slack", "input": {"text": "plain"}}))
        self.add(
            "common", 3002, recipe({"provider": "slack", "unfinished": True}, name="[CM] Two")
        )

    def change(self, edit: Callable[[dict[str, Any]], Any]) -> None:
        data = json.loads(wkrepo.registry_path().read_text(encoding="utf-8"))
        edit(data)
        support.write_json(wkrepo.registry_path(), data)

    def add(self, slug, recipe_id, document, properties=()):
        file = f"{recipe_id}-recipe.recipe.json"
        support.write_json(self.cache / slug / file, document)
        index_path = self.cache / slug / "index.json"
        index: dict[str, list[Any]] = {"recipes": [], "properties": list(properties)}
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        index["recipes"].append({"id": recipe_id, "file": file})
        support.write_json(index_path, index)

    def run_lint(self, *args, diagnostics=None):
        with (
            patch.object(lint, "run_lint", return_value=diagnostics or {}) as linted,
            patch.object(lint, "pull") as pull,
        ):
            result = support.run_main(lint.main, *args)
        return result, linted, pull

    def test_every_project_with_a_prod_copy_is_checked_and_an_error_fails_the_run(self):
        result, linted, pull = self.run_lint()
        self.assertEqual(result.code, 1)
        pull.assert_called_once_with(["sales-orders", "common"], set())
        self.assertEqual(len(linted.call_args.args[0]), 2)
        self.assertIn("== sales-orders: 1 recipes, 0 errors, 0 warnings", result.out)
        self.assertIn("== common: 1 recipes, 1 errors, 0 warnings", result.out)
        self.assertIn("[CM] Two  https://app.workato.com/recipes/3002", result.out)
        self.assertIn("UNFINISHED_STEP", result.out)
        self.assertIn("2 recipes checked: 1 errors.", result.out)
        self.assertNotIn("== sandbox", result.out)  # a Dev-only project has no Prod copy

    def test_warnings_alone_do_not_fail_the_run(self):
        warning = {"rule_id": "SOME_RULE", "message": "m", "level": "warn", "source": {}}
        result, _, _ = self.run_lint("sales-orders", diagnostics={3001: [warning]})
        self.assertEqual(result.code, 0)
        self.assertIn("== sales-orders: 1 recipes, 0 errors, 1 warnings", result.out)
        self.assertIn("WARN  SOME_RULE recipe", result.out)
        self.assertNotIn("== common", result.out)

    def test_no_pull_reads_the_copy_that_is_there(self):
        result, _, pull = self.run_lint("sales-orders", "--no-pull")
        self.assertEqual(result.code, 0)
        pull.assert_not_called()

    def test_a_recipe_id_selects_its_project_before_anything_is_pulled(self):
        result, linted, pull = self.run_lint("--recipe", "3002")
        self.assertEqual(result.code, 1)
        pull.assert_called_once_with(["common"], {3002})
        self.assertEqual(
            [path.name for path in linted.call_args.args[0]], ["3002-recipe.recipe.json"]
        )
        self.assertNotIn("== sales-orders", result.out)

    def test_an_id_no_local_copy_knows_is_looked_for_in_every_project(self):
        both = ["sales-orders", "common"]
        self.assertEqual(lint.narrowed(both, {3002, 3999}), both)
        self.assertEqual(lint.narrowed(both, set()), both)
        self.assertEqual(lint.narrowed(both, {3001}), ["sales-orders"])

    def test_a_recipe_missing_from_the_copy_stops_the_run(self):
        result, linted, _ = self.run_lint("--recipe", "3999", "--no-pull")
        self.assertEqual(result.code, 2)
        self.assertIn("3999", result.err)
        linted.assert_not_called()

    def test_a_project_without_a_copy_stops_a_whole_project_run(self):
        result, linted, _ = self.run_lint("sandbox", "--no-pull")
        self.assertEqual(result.code, 2)
        self.assertIn("no Dev copy of sandbox", result.err)
        linted.assert_not_called()

    def test_an_unknown_project_stops_the_run_before_anything_is_pulled(self):
        result, _, pull = self.run_lint("no-such-project")
        self.assertEqual(result.code, 2)
        self.assertIn("unknown project 'no-such-project'", result.err)
        pull.assert_not_called()

    def test_an_unknown_check_or_a_guard_check_without_its_property_stops_the_run(self):
        self.change(lambda data: data["projects"]["sales-orders"].update(lint_checks=["NOPE"]))
        result, _, _ = self.run_lint("sales-orders", "--no-pull")
        self.assertEqual(result.code, 2)
        self.assertIn("NOPE", result.err)
        self.change(
            lambda data: data["projects"]["sales-orders"].update(lint_checks=["NO_GUARD_PROPERTY"])
        )
        result, _, _ = self.run_lint("sales-orders", "--no-pull")
        self.assertEqual(result.code, 2)
        self.assertIn("needs lint_guard_property", result.err)

    def test_the_checks_of_the_registry_apply_to_their_project_only(self):
        self.add("sales-orders", 3003, function(ACTING, name="[SO] LF | One"))
        self.add("common", 3004, function(ACTING, name="[CM] LF | Two"))
        self.change(
            lambda data: data["projects"]["sales-orders"].update(
                lint_checks=["NO_GUARD_PROPERTY"],
                lint_guard_property=GUARD,
                lint_guard_parameter=GUARD_PARAMETER,
            )
        )
        result, _, _ = self.run_lint("--no-pull")
        self.assertIn("[SO] LF | One  https://app.workato.com/recipes/3003", result.out)
        self.assertIn(f"never reads {GUARD}", result.out)
        self.assertNotIn("[CM] LF | Two", result.out)
        self.change(
            lambda data: data["projects"]["sales-orders"].update(
                lint_guard_exempt=["[SO] LF | One"]
            )
        )
        result, _, _ = self.run_lint("--no-pull")
        self.assertNotIn("[SO] LF | One", result.out)

    def test_company_domains_and_patterns_of_the_registry_reach_every_project(self):
        step = {"provider": "erp", "input": {"to": "orders@acme.example", "order": "SO-1001"}}
        self.add("common", 3005, recipe(step, name="[CM] Addresses"))
        self.change(lambda data: data.update(lint_literal_patterns={"order number": r"SO-\d+"}))
        result, _, _ = self.run_lint("common", "--no-pull")
        self.assertIn("company e-mail 'orders@acme.example'", result.out)
        self.assertIn("order number 'SO-1001'", result.out)
        self.change(lambda data: data.update(lint_literal_patterns={"broken": "SO-("}))
        result, _, _ = self.run_lint("common", "--no-pull")
        self.assertEqual(result.code, 2)
        self.assertIn("'broken' is not a regular expression", result.err)

    def test_property_pills_are_checked_against_the_names_in_the_index(self):
        step = {"provider": "slack", "input": {"channel": pill("project_property", "old_name")}}
        self.add("sales-orders", 3006, recipe(step, name="[SO] Renamed"))
        result, _, _ = self.run_lint("sales-orders", "--no-pull")
        self.assertEqual(result.code, 1)
        self.assertIn('project property "old_name" does not exist', result.out)
        self.assertNotIn("Property check SKIPPED", result.out)

    def test_an_index_without_property_names_skips_the_property_check_and_says_so(self):
        index_path = self.cache / "sales-orders" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        del index["properties"]
        support.write_json(index_path, index)
        result, _, _ = self.run_lint("sales-orders", "--no-pull")
        self.assertEqual(result.code, 0)
        self.assertIn("Property check SKIPPED for sales-orders", result.out)


class PullTests(unittest.TestCase):
    def pull(self, returncode, slugs, only):
        done: subprocess.CompletedProcess[str] = subprocess.CompletedProcess([], returncode)
        with patch.object(subprocess, "run", return_value=done) as run:
            lint.pull(slugs, only)
        return run.call_args.args[0]

    def test_the_dev_copy_is_refreshed_with_sync_recipes(self):
        command = self.pull(0, ["sales-orders"], {3002, 3001})
        self.assertEqual(command[:3], [sys.executable, "-I", "-B"])
        self.assertTrue(command[3].endswith("scripts/sync_recipes.py"))
        self.assertEqual(command[4:], ["dev", "sales-orders", "--recipe", "3001", "3002"])
        self.assertEqual(self.pull(0, ["common"], set())[4:], ["dev", "common"])

    def test_a_failed_refresh_stops_the_run(self):
        with self.assertRaisesRegex(cli.Error, "Dev copy could not be refreshed"):
            self.pull(2, ["sales-orders"], set())


class RunLintTests(unittest.TestCase):
    def setUp(self):
        self.root = support.fake_workspace(self)
        self.out = self.root / "tmp" / "wk" / "lint.json"
        support.start(
            self,
            patch.object(lint, "LINT_OUTPUT", self.out),
            patch.object(wkrepo, "executable", return_value="/usr/bin/wk"),
        )

    def lint(self, stdout, returncode=1):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="plugin error")
        with patch.object(subprocess, "run", return_value=done) as run:
            return lint.run_lint([self.out.parent / "3001-a.recipe.json"]), run

    def test_diagnostics_are_keyed_by_recipe_id_and_the_raw_output_is_kept(self):
        files = [{"file": "/x/3001-a.recipe.json", "diagnostics": [{"rule_id": "R"}]}]
        found, run = self.lint(json.dumps({"files": files}))
        self.assertEqual(found, {3001: [{"rule_id": "R"}]})
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8")), {"files": files})
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["/usr/bin/wk", "lint"])
        self.assertEqual(command[-3:-1], ["--json", "--config-path"])
        self.assertEqual(command[-1], str(lint.CONFIG))

    def test_the_workspace_lint_configuration_is_passed_when_it_exists(self):
        own = support.write_json(wkrepo.workspace() / "wklintrc.json", {"rules": {}})
        _, run = self.lint(json.dumps({"files": []}))
        self.assertEqual(run.call_args.args[0][-1], str(own))

    def test_an_answer_that_is_not_the_lint_result_stops_the_run(self):
        for stdout in ("", "Error: unknown command lint", "[]"):
            with self.subTest(stdout=stdout), self.assertRaisesRegex(cli.Error, "wk lint"):
                self.lint(stdout)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()

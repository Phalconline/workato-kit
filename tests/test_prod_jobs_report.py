"""scripts/prod_jobs_report.py with a fake API: the report is redacted before it is written."""

import json
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import prod_jobs_report as report
from lib import cli, wkrepo
from tests import support

SINCE = datetime(2030, 1, 5, 17, tzinfo=UTC)
UNTIL = datetime(2030, 1, 6, 17, tzinfo=UTC)


def job(job_id, started_at, status="succeeded", **extra):
    return {"id": job_id, "started_at": started_at, "status": status, **extra}


class FakeApi:
    """Stands in for wkrepo.Api: answers each GET from a list or from a function."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, Any]] = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if callable(self.answers):
            return self.answers(path, params)
        return self.answers.pop(0)


class TimeTests(unittest.TestCase):
    def test_iso_times_are_read_as_utc(self):
        for text in (
            "2030-01-05T17:00:00Z",
            "2030-01-05T18:00:00+01:00",
            "2030-01-05 17:00:00 UTC",
        ):
            with self.subTest(text=text):
                self.assertEqual(report.parse_time(text), SINCE)

    def test_another_format_is_an_expected_failure(self):
        with self.assertRaisesRegex(cli.Error, "ISO 8601"):
            report.parse_time("yesterday")


class RedactionTests(unittest.TestCase):
    def test_addresses_are_replaced_at_every_depth(self):
        value = {
            "title": "Order of jo@acme.example",
            "lines": [{"error": "no order for sam@acme.example"}, 5, None],
        }
        self.assertEqual(
            report.redact(value),
            {"title": "Order of <user>", "lines": [{"error": "no order for <user>"}, 5, None]},
        )


class JobsTests(unittest.TestCase):
    def test_only_jobs_inside_the_window_are_kept_and_reading_stops_at_its_start(self):
        first = [job("d", "2030-01-07T00:00:00Z"), job("c", "2030-01-06T10:00:00Z")]
        second = [job("b", "2030-01-05T18:00:00Z"), job("a", "2030-01-04T00:00:00Z")]
        never = [job("never", "2030-01-01T00:00:00Z")]
        api = FakeApi([{"items": first}, {"items": second}, {"items": never}])
        found = report.jobs_in_window(api, 7, SINCE, UNTIL)  # type: ignore[arg-type]
        self.assertEqual([item["id"] for item in found], ["c", "b"])
        self.assertEqual(
            api.calls,
            [("/recipes/7/jobs", None), ("/recipes/7/jobs", {"offset_job_id": "c"})],
        )

    def test_an_empty_page_ends_the_listing(self):
        api = FakeApi([{"items": [job("b", "2030-01-06T00:00:00Z")]}, {"items": []}])
        self.assertEqual(len(report.jobs_in_window(api, 7, SINCE, UNTIL)), 1)  # type: ignore[arg-type]
        self.assertEqual(len(api.calls), 2)

    def test_a_page_that_repeats_its_last_job_ends_the_listing(self):
        page = {"items": [job("b", "2030-01-06T00:00:00Z")]}
        api = FakeApi([page, page, page])
        report.jobs_in_window(api, 7, SINCE, UNTIL)  # type: ignore[arg-type]
        self.assertEqual(len(api.calls), 2)

    def test_failing_steps_carry_the_ui_step_number(self):
        detail = {
            "lines": [
                {"recipe_line_number": 0, "adapter_name": "clock"},
                {"recipe_line_number": 4, "adapter_name": "erp", "error": "not found"},
            ]
        }
        lines = report.failing_lines(FakeApi([detail]), 7, "j1")  # type: ignore[arg-type]
        self.assertEqual([(line["ui_step"], line["adapter"]) for line in lines], [(5, "erp")])


class ReportTests(unittest.TestCase):
    def setUp(self):
        root = support.fake_workspace(self)
        self.out = root / "tmp" / "evidence" / "report.json"
        support.start(self, patch.object(report, "ROOT", root))
        self.answers: dict[str, Any] = {
            "/recipes/7/jobs": {
                "items": [
                    job("j2", "2030-01-06T10:00:00Z", "failed", title="Order of jo@acme.example"),
                    job("j1", "2030-01-05T18:00:00Z"),
                ]
            },
            "/recipes/7/jobs/j2": {
                "lines": [{"recipe_line_number": 1, "error": "jo@acme.example"}]
            },
            "/activity_logs": {
                "data": [
                    {"event_type": "recipe_stopped", "resource": {"id": 7}, "timestamp": "t"},
                    {"event_type": "user_login", "timestamp": "t"},
                ]
            },
        }
        self.api = FakeApi(self.answer)
        recipes = [{"id": 7, "name": "Recipe", "running": True}]
        support.start(
            self,
            patch.object(wkrepo, "api", return_value=self.api),
            patch.object(wkrepo, "list_recipes", return_value=recipes),
        )

    def answer(self, path, params):
        answer = self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        if path == "/recipes/7/jobs" and params:  # the page after the last job
            return {"items": []}
        return answer

    def run_report(self, *extra):
        result = support.run_main(
            report.main,
            "--since",
            "2030-01-05T17:00:00Z",
            "--until",
            "2030-01-06T17:00:00Z",
            "--out",
            str(self.out),
            *extra,
        )
        return result, json.loads(self.out.read_text(encoding="utf-8"))

    def test_jobs_failing_steps_and_audit_events_are_collected_and_redacted(self):
        result, written = self.run_report()
        self.assertEqual(result.code, 0)
        self.assertIn("1 recipes, 2 jobs, 1 failed, 1 audit events, 0 read errors", result.out)
        recipe = written["recipes"][0]
        self.assertEqual(recipe["counts"], {"failed": 1, "succeeded": 1, "total": 2})
        self.assertEqual(recipe["jobs"][0]["title"], "Order of <user>")
        self.assertEqual(recipe["jobs"][0]["failing_lines"][0]["ui_step"], 2)
        self.assertEqual(recipe["jobs"][0]["url"], "https://app.workato.com/recipes/7/job/j2")
        self.assertEqual([event["event"] for event in written["audit"]], ["recipe_stopped"])
        self.assertNotIn("acme.example", self.out.read_text(encoding="utf-8"))

    def test_the_prod_profile_of_the_registry_is_used_unless_another_is_named(self):
        with patch.object(wkrepo, "api", return_value=self.api) as api:
            self.run_report()
            self.run_report("--profile", "acme-prod-readonly")
        self.assertEqual(
            [call.args for call in api.call_args_list],
            [("prod", "acme-prod"), ("prod", "acme-prod-readonly")],
        )

    def test_a_recipe_that_cannot_be_read_is_listed_and_the_run_goes_on(self):
        self.answers["/recipes/7/jobs"] = OSError("connection reset")
        result, written = self.run_report()
        self.assertEqual(result.code, 0)
        self.assertEqual(written["recipes"][0]["counts"], {"total": 0})
        self.assertEqual(written["errors"][0]["stage"], "jobs")
        self.assertEqual(len(written["audit"]), 1)

    def test_a_job_with_an_unreadable_time_is_listed_and_the_run_goes_on(self):
        self.answers["/recipes/7/jobs"] = {"items": [job("j9", "not a time")]}
        result, written = self.run_report()
        self.assertEqual(result.code, 0)
        self.assertEqual(written["errors"][0]["stage"], "jobs")
        self.assertEqual(len(written["audit"]), 1)

    def test_an_api_failure_on_one_recipe_is_listed_and_the_run_goes_on(self):
        self.answers["/recipes/7/jobs"] = cli.Error(
            "Workato answered HTTP 500 to GET /recipes/7/jobs"
        )
        result, written = self.run_report()
        self.assertEqual(result.code, 0)
        self.assertIn("HTTP 500", written["errors"][0]["error"])

    def test_the_report_is_written_under_tmp_only(self):
        outside = support.temp_dir(self, "outside-") / "report.json"
        for target in (
            outside,
            self.out.parents[2] / "AGENTS.md",
            self.out.parent / ".." / ".." / "x",
        ):
            result = support.run_main(report.main, "--out", str(target))
            with self.subTest(target=target):
                self.assertEqual(result.code, 2)
                self.assertIn("--out must be a file under tmp/", result.err)
                self.assertFalse(target.exists())
        self.assertEqual(self.api.calls, [])  # refused before anything is read

    def test_a_time_that_is_not_iso_stops_the_run(self):
        result = support.run_main(report.main, "--since", "last week")
        self.assertEqual(result.code, 2)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()

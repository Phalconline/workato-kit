"""scripts/check.py: one failed check does not hide the ones after it."""

import subprocess
import sys
import unittest
from unittest.mock import patch

import check
from tests import support


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "check-")
        self.tools = self.root / ".venv" / "bin"
        self.tools.mkdir(parents=True)
        for tool in ("ruff", "mypy"):
            (self.tools / tool).touch()
        self.calls = []
        support.start(
            self,
            patch.object(check, "ROOT", self.root),
            patch.object(check, "TOOLS", self.tools),
            patch.object(check, "not_ignored", return_value=[]),
            patch.object(subprocess, "run", side_effect=self.run_command),
        )

    def run_command(self, command, **_options):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 1 if command == ["failing-check"] else 0)

    def test_failure_is_reported_and_remaining_checks_still_run(self):
        steps = [("failure", ["failing-check"]), ("later", ["later-check"])]
        with patch.object(check, "steps", return_value=steps):
            result = support.run_main(check.main)
        self.assertEqual(result.code, 1)
        self.assertEqual(self.calls, [["failing-check"], ["later-check"]])
        self.assertIn("FAILED: failure", result.err)

    def test_all_passing_is_status_0(self):
        with patch.object(check, "steps", return_value=[("fine", ["fine-check"])]):
            result = support.run_main(check.main)
        self.assertEqual(result.code, 0)
        self.assertIn("All offline checks passed", result.out)

    def test_a_path_git_does_not_ignore_fails_the_check(self):
        with (
            patch.object(check, "steps", return_value=[]),
            patch.object(check, "not_ignored", return_value=["profiles.env"]),
        ):
            result = support.run_main(check.main)
        self.assertEqual(result.code, 1)
        self.assertIn("Ignore rule: profiles.env", result.err)

    def test_missing_development_tools_stop_the_run_with_the_fix(self):
        (self.tools / "mypy").unlink()
        result = support.run_main(check.main)
        self.assertEqual(result.code, 2)
        self.assertIn("make dev", result.err)
        self.assertEqual(self.calls, [])

    def test_python_series_is_required_and_any_patch_is_accepted(self):
        with patch.object(check, "steps", return_value=[]):
            for version in ((3, 9, 6), (3, 13, 9), (3, 15, 0)):
                with self.subTest(version=version), patch.object(sys, "version_info", version):
                    result = support.run_main(check.main)
                    self.assertEqual(result.code, 2)
                    self.assertIn("Python 3.14", result.err)
            for version in ((3, 14, 0), (3, 14, 10), (3, 14, 11)):
                with self.subTest(version=version), patch.object(sys, "version_info", version):
                    self.assertEqual(support.run_main(check.main).code, 0)

    def test_the_series_agrees_with_the_version_file_and_the_tool_configuration(self):
        series = ".".join(str(part) for part in check.PYTHON_SERIES)
        version_file = (support.ROOT / ".python-version").read_text(encoding="utf-8").strip()
        self.assertEqual(version_file, series)  # no patch number: any 3.14 release serves
        pyproject = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'target-version = "py{series.replace(".", "")}"', pyproject)
        self.assertIn(f'python_version = "{series}"', pyproject)

    def test_every_step_names_a_tool_of_the_venv_or_a_script_that_exists(self):
        for label, command in check.steps("python"):
            with self.subTest(step=label):
                scripts = [part for part in command if part.startswith("scripts/")]
                for script in scripts:
                    self.assertTrue((support.ROOT / script).is_file(), script)
                self.assertTrue(command[0] == "python" or command[0].startswith(str(self.tools)))

    def test_the_credential_files_and_caches_must_be_ignored(self):
        for path in ("profiles.env", "master.key", ".env", "tmp/example", ".venv/bin/python"):
            self.assertIn(path, check.MUST_BE_IGNORED)


if __name__ == "__main__":
    unittest.main()

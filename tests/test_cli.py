"""lib/cli.py: the exit codes and the one-line error every script shares."""

import contextlib
import io
import unittest

from lib import cli
from tests import support


class InvokeTests(unittest.TestCase):
    def test_the_status_of_main_is_returned(self):
        def findings(_argv):
            return cli.EXIT_FINDINGS

        self.assertEqual(cli.invoke(findings), cli.EXIT_FINDINGS)
        self.assertEqual(cli.invoke(findings, ["--option"]), cli.EXIT_FINDINGS)

    def test_an_expected_failure_is_one_line_and_status_2(self):
        def main(_argv):
            raise cli.Error("the registry is missing")

        result = support.run_main(main)
        self.assertEqual(result.code, cli.EXIT_ERROR)
        self.assertEqual(result.err, "error: the registry is missing\n")
        self.assertNotIn("Traceback", result.err)

    def test_a_bug_is_not_swallowed(self):
        def main(_argv):
            raise KeyError("bug")

        with self.assertRaises(KeyError):
            support.run_main(main)

    def test_a_crash_shows_its_traceback_and_does_not_exit_like_a_finding(self):
        def main(_argv):
            raise KeyError("bug")

        with (
            contextlib.redirect_stderr(io.StringIO()) as shown,
            self.assertRaises(SystemExit) as stop,
        ):
            cli.run(main)
        self.assertEqual(stop.exception.code, cli.EXIT_ERROR)
        self.assertIn("KeyError: 'bug'", shown.getvalue())

    def test_run_exits_with_the_status_of_main(self):
        def findings(_argv):
            return cli.EXIT_FINDINGS

        with self.assertRaises(SystemExit) as stop:
            cli.run(findings)
        self.assertEqual(stop.exception.code, cli.EXIT_FINDINGS)

    def test_help_is_the_module_docstring(self):
        def main(argv):
            cli.parser("Explain the script.\n\n    scripts/example.py").parse_args(argv)
            return cli.EXIT_OK

        result = support.run_main(main, "--help")
        self.assertEqual(result.code, 0)
        self.assertIn("Explain the script.\n\n    scripts/example.py", result.out)

    def test_a_flag_cannot_be_abbreviated(self):
        def main(argv):
            parser = cli.parser("doc")
            parser.add_argument("--write", action="store_true")
            return cli.EXIT_FINDINGS if parser.parse_args(argv).write else cli.EXIT_OK

        self.assertEqual(support.run_main(main, "--write").code, cli.EXIT_FINDINGS)
        self.assertEqual(support.run_main(main, "--w").code, cli.EXIT_ERROR)

    def test_an_unknown_argument_is_status_2(self):
        def main(argv):
            cli.parser("doc").parse_args(argv)
            return cli.EXIT_OK

        self.assertEqual(support.run_main(main, "--no-such-option").code, cli.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()

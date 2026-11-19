"""Every script in scripts/ follows the conventions of docs/conventions/python.md."""

import ast
import importlib
import inspect
import os
import re
import subprocess
import sys
import unittest

from tests import support

SCRIPTS = sorted(support.SCRIPTS.glob("*.py"))
LIBRARY = sorted(
    path for path in (support.SCRIPTS / "lib").glob("*.py") if path.stem != "__init__"
)
SHEBANG = "#!/usr/bin/env python3.14\n"
# Test modules that belong to no single script: the conventions and the repository's config.
SHARED_TEST_MODULES = {"test_scripts", "test_repository"}


def imported_modules(source):
    """Return the top-level name of every module a source file imports."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


class ConventionTests(unittest.TestCase):
    def test_all_scripts_are_python_in_one_flat_folder(self):
        self.assertGreater(len(SCRIPTS), 15)
        others = [
            path.relative_to(support.ROOT).as_posix()
            for path in support.SCRIPTS.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".py"
            and path.name not in {"README.md", "wklintrc.json"}
        ]
        self.assertEqual(others, [])
        folders = [path.name for path in support.SCRIPTS.iterdir() if path.is_dir()]
        self.assertEqual([name for name in folders if name != "__pycache__"], ["lib"])

    def test_names_are_snake_case(self):
        for path in [*SCRIPTS, *LIBRARY]:
            with self.subTest(file=path.name):
                self.assertRegex(path.name, r"^[a-z][a-z0-9_]*\.py$")

    def test_every_script_is_executable_and_starts_with_the_shebang(self):
        for path in SCRIPTS:
            with self.subTest(script=path.name):
                self.assertTrue(os.access(path, os.X_OK), "not executable")
                self.assertTrue(path.read_text(encoding="utf-8").startswith(SHEBANG))
        for path in LIBRARY:
            with self.subTest(module=path.name):
                self.assertFalse(os.access(path, os.X_OK), "a library module is not a command")

    def test_every_script_documents_its_usage_and_exit_status(self):
        for path in SCRIPTS:
            with self.subTest(script=path.name):
                doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
                self.assertIn(f"scripts/{path.name}", doc)
                self.assertIn("Exit status:", doc)

    def test_main_takes_argv_and_returns_the_exit_status(self):
        for path in SCRIPTS:
            with self.subTest(script=path.name):
                main = importlib.import_module(path.stem).main
                parameters = inspect.signature(main).parameters
                self.assertEqual(list(parameters), ["argv"])
                self.assertIsNone(parameters["argv"].default)
                self.assertIs(inspect.signature(main).return_annotation, int)

    def test_only_the_standard_library_and_lib_are_imported(self):
        allowed = set(sys.stdlib_module_names) | {"lib"}
        for path in [*SCRIPTS, *LIBRARY]:
            with self.subTest(file=path.name):
                extra = imported_modules(path.read_text(encoding="utf-8")) - allowed
                self.assertEqual(extra, set(), "a script may not import a package or a script")

    def test_every_script_and_library_module_has_its_own_test_module(self):
        tested = {path.stem for path in (support.ROOT / "tests").glob("test_*.py")}
        expected = {f"test_{path.stem}" for path in [*SCRIPTS, *LIBRARY]}
        self.assertEqual(expected - tested, set(), "missing test modules")
        # A workspace may test its own data or rules without a script of that name.
        own = {name for name in tested if name.startswith("test_ws_")}
        self.assertEqual(
            tested - expected - SHARED_TEST_MODULES - own, set(), "tests of no script"
        )

    def test_test_modules_never_import_one_another(self):
        for path in sorted((support.ROOT / "tests").glob("test_*.py")):
            with self.subTest(module=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIsNone(
                    re.search(r"^\s*(from|import) tests\.test_", source, re.MULTILINE)
                )
                self.assertIsNone(re.search(r"^\s*from tests import test_", source, re.MULTILINE))


class CommandLineTests(unittest.TestCase):
    """Each script is started in an empty folder with an empty PATH.

    A script that went on past its arguments could not reach git, wk or a network tool, and
    would leave a file behind.
    """

    def run_each(self, *args):
        empty = support.temp_dir(self, "empty-")
        for path in SCRIPTS:
            done = subprocess.run(
                [sys.executable, "-I", "-B", str(path), *args],
                cwd=empty,
                env={"PATH": str(empty)},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            yield path.name, done
        self.assertEqual(list(empty.iterdir()), [])

    def test_every_script_answers_help_without_running(self):
        for name, done in self.run_each("--help"):
            with self.subTest(script=name):
                self.assertEqual(done.returncode, 0, done.stderr[-300:])
                self.assertIn(f"scripts/{name}", done.stdout)
                self.assertIn("Exit status:", done.stdout)

    def test_an_unknown_option_is_status_2_and_nothing_runs(self):
        for name, done in self.run_each("--no-such-option"):
            with self.subTest(script=name):
                self.assertEqual(done.returncode, 2, done.stderr[-300:])
                self.assertEqual(done.stdout, "")
                self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()

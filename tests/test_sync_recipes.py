"""scripts/sync_recipes.py: a sync writes a project only after every read succeeded."""

import contextlib
import copy
import io
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_recipes as sync
from lib import cli, wkrepo
from tests import support


def listed(recipe_id, name):
    """Return a recipe as remote_state() lists it."""
    return {
        "id": recipe_id,
        "name": name,
        "folder": "(project root)",
        "file": f"{recipe_id}-{name}.recipe.json",
        "match_key": name,
        "running": False,
    }


def document(version):
    """Return the bytes of a pulled recipe."""
    return json.dumps({"code": {"number": 0}, "version": version}).encode()


class SyncProjectTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "sync-")
        self.base = self.root / "projects" / "example"
        self.folders = [{"id": 1, "name": "(project root)", "path": "."}]
        self.recipes = [listed(1, "one"), listed(2, "two")]
        self.data = {recipe["id"]: document(1) for recipe in self.recipes}
        entry = {"name": "Example", "prod": {"project_id": 1, "folder_id": 1}}
        support.start(
            self,
            patch.object(sync, "ROOT", self.root),
            patch.object(wkrepo, "project", return_value=entry),
            patch.object(wkrepo, "profile", return_value="test"),
            patch.object(wkrepo, "snapshot_dir", return_value=self.base),
            patch.object(sync, "remote_state", side_effect=self.remote_state),
            patch.object(sync, "pull", side_effect=lambda _prof, rid, _scratch: self.data[rid]),
            patch.object(wkrepo, "list_connections", return_value=[]),
            patch.object(wkrepo, "property_names", return_value=["example_property"]),
        )
        self.sync()

    def remote_state(self, *_args):
        return copy.deepcopy(self.folders), copy.deepcopy(self.recipes)

    def sync(self, only=(), *, check=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return sync.sync_project("prod", "example", set(only), check)

    def tree(self):
        files = (path for path in self.base.rglob("*") if path.is_file())
        return {path.relative_to(self.base).as_posix(): path.read_bytes() for path in files}

    def index(self):
        return json.loads((self.base / "index.json").read_text(encoding="utf-8"))

    def test_partial_keeps_unselected_files_and_metadata_after_remote_move(self):
        before = self.tree()
        old_index = self.index()
        self.recipes[1] = {**listed(2, "moved"), "running": True}
        self.data[1] = document(2)
        self.sync([1])
        self.assertEqual(self.tree()["2-two.recipe.json"], before["2-two.recipe.json"])
        self.assertFalse((self.base / "2-moved.recipe.json").exists())
        self.assertEqual(self.index()["recipes"][1], old_index["recipes"][1])
        self.assertEqual(self.index()["recipes"][0]["version"], 2)

    def test_partial_does_not_remove_remote_deleted_unselected_recipe(self):
        before = self.tree()
        self.recipes = self.recipes[:1]
        self.assertEqual(self.sync([1]), 0)
        self.assertEqual(self.tree(), before)

    def test_partial_selected_rename_removes_only_selected_old_path(self):
        self.recipes[0] = listed(1, "renamed")
        self.sync([1])
        self.assertTrue((self.base / "1-renamed.recipe.json").exists())
        self.assertFalse((self.base / "1-one.recipe.json").exists())
        self.assertTrue((self.base / "2-two.recipe.json").exists())

    def test_partial_refreshes_project_metadata_but_not_other_recipes(self):
        old_entry = self.index()["recipes"][1]
        self.recipes[1]["running"] = True
        with patch.object(wkrepo, "property_names", return_value=["renamed_property"]):
            self.sync([1])
        self.assertEqual(self.index()["properties"], ["renamed_property"])
        self.assertEqual(self.index()["recipes"][1], old_entry)

    def test_partial_without_a_local_copy_pulls_the_whole_project(self):
        shutil.rmtree(self.base)
        self.sync([1])
        self.assertEqual(
            sorted(self.tree()), ["1-one.recipe.json", "2-two.recipe.json", "index.json"]
        )

    def test_failed_second_pull_leaves_all_files_unchanged(self):
        before = self.tree()
        failing = [document(9), cli.Error("wk recipes pull failed")]
        with patch.object(sync, "pull", side_effect=failing), self.assertRaises(cli.Error):
            self.sync()
        self.assertEqual(self.tree(), before)

    def test_metadata_failure_leaves_all_files_unchanged(self):
        before = self.tree()
        self.data[1] = document(2)
        failure = cli.Error("properties could not be read")
        with (
            patch.object(wkrepo, "property_names", side_effect=failure),
            self.assertRaises(cli.Error),
        ):
            self.sync()
        self.assertEqual(self.tree(), before)

    def test_invalid_pull_leaves_all_files_unchanged(self):
        before = self.tree()
        for invalid in (b"not json", b"[]", b'{"error":"denied"}'):
            self.data[2] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(cli.Error):
                self.sync()
            self.assertEqual(self.tree(), before)

    def test_missing_id_fails_without_mutation(self):
        before = self.tree()
        with self.assertRaisesRegex(cli.Error, "999"):
            self.sync([999])
        self.assertEqual(self.tree(), before)

    def test_check_uses_fetched_version_and_never_rewrites_snapshot(self):
        before = self.tree()
        self.data[1] = document(2)
        # A changed recipe and a changed index, although the local recipe is still at version 1.
        self.assertEqual(self.sync(check=True), 2)
        self.assertEqual(self.tree(), before)

    def test_full_sync_removes_deleted_recipe_then_is_idempotent(self):
        self.recipes = self.recipes[:1]
        self.sync()
        self.assertFalse((self.base / "2-two.recipe.json").exists())
        self.assertEqual(len(self.index()["recipes"]), 1)
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.sync(check=True), 0)

    def test_interrupted_write_is_completed_by_running_again(self):
        self.data[1] = self.data[2] = document(2)
        write = Path.write_bytes
        calls = []

        def fail_second(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            return write(path, data)

        with patch.object(Path, "write_bytes", fail_second), self.assertRaises(OSError):
            self.sync()
        self.assertTrue(self.sync(check=True))
        self.sync()
        self.assertEqual(self.sync(check=True), 0)
        self.assertEqual({recipe["version"] for recipe in self.index()["recipes"]}, {2})

    def test_a_duplicate_folder_and_name_is_a_warning(self):
        index = {"recipes": [listed(1, "same"), listed(2, "same")], "connections": []}
        self.assertIn("cannot be paired", sync.warnings("prod", index)[0])


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.folders = [{"id": 1, "name": "(project root)", "path": "."}]
        entry = {"name": "Example", "prod": {"project_id": 1, "folder_id": 1}}
        support.start(
            self,
            patch.object(wkrepo, "project", return_value=entry),
            patch.object(wkrepo, "profile", return_value="test"),
        )

    def test_missing_ids_are_rejected_before_the_first_project_write(self):
        state = (self.folders, [listed(1, "one"), listed(2, "two")])
        with (
            patch.object(sync, "remote_state", return_value=state),
            patch.object(sync, "sync_project") as write,
        ):
            result = support.run_main(sync.main, "prod", "example", "--recipe", "1", "999")
        self.assertEqual(result.code, 2)
        self.assertIn("999", result.err)
        write.assert_not_called()

    def test_ids_are_routed_only_to_their_project(self):
        states = [(self.folders, [listed(1, "one")]), (self.folders, [listed(2, "two")])]
        with (
            patch.object(sync, "remote_state", side_effect=states),
            patch.object(sync, "sync_project", return_value=0) as write,
        ):
            result = support.run_main(sync.main, "prod", "first", "second", "--recipe", "1", "2")
        self.assertEqual(result.code, 0)
        self.assertEqual(
            [call.args[1:3] for call in write.call_args_list], [("first", {1}), ("second", {2})]
        )

    def test_check_exits_1_when_the_copy_is_stale(self):
        state = (self.folders, [listed(1, "one")])
        for differences, expected in ((0, 0), (3, 1)):
            with (
                self.subTest(differences=differences),
                patch.object(sync, "remote_state", return_value=state),
                patch.object(sync, "sync_project", return_value=differences),
            ):
                result = support.run_main(sync.main, "prod", "example", "--check")
                self.assertEqual(result.code, expected)

    def test_a_project_without_ids_in_that_environment_is_skipped_aloud(self):
        with (
            patch.object(wkrepo, "project", return_value={"name": "Sandbox", "dev": {}}),
            patch.object(sync, "sync_project") as write,
        ):
            result = support.run_main(sync.main, "prod", "sandbox")
        self.assertEqual(result.code, 0)
        self.assertIn("prod sandbox: the registry has no prod ids for this project", result.out)
        write.assert_not_called()

    def test_no_managed_project_is_said_aloud(self):
        with (
            patch.object(wkrepo, "snapshot_projects", return_value=[]),
            patch.object(sync, "sync_project") as write,
        ):
            result = support.run_main(sync.main, "prod")
        self.assertEqual(result.code, 0)
        self.assertIn("No managed project has prod ids in the registry", result.out)
        write.assert_not_called()

    def test_an_unknown_environment_is_a_bad_argument(self):
        with patch.object(sync, "sync_project") as write:
            self.assertEqual(support.run_main(sync.main, "test").code, 2)
        write.assert_not_called()


class RemoteStateTests(unittest.TestCase):
    def test_dev_and_prod_copies_get_the_same_match_key_and_a_folder_path(self):
        def state(root, ids):
            folders = [(root, []), (root + 1, ["[SO] Functions"])]

            def in_folder(_prof, folder):
                return [{"id": ids[folder], "name": "[SO] LF | Same name", "running": True}]

            with (
                patch.object(wkrepo, "walk_folders", return_value=folders),
                patch.object(wkrepo, "list_recipes", side_effect=in_folder),
            ):
                return sync.remote_state("profile", {"folder_id": root})[1]

        dev, prod = state(10, {10: 1, 11: 2}), state(20, {20: 101, 21: 102})
        keys = ["so-lf-same-name", "so-functions/so-lf-same-name"]
        self.assertEqual([recipe["match_key"] for recipe in dev], keys)
        self.assertEqual([recipe["match_key"] for recipe in prod], keys)
        self.assertEqual(prod[1]["file"], "so-functions/102-so-lf-same-name.recipe.json")

    def test_names_without_latin_letters_never_give_an_empty_or_absolute_path(self):
        archive, order = "\u0391\u03c1\u03c7", "\u03a0\u03b1\u03c1"  # two Greek words
        folders = [(10, []), (11, [archive]), (12, [archive, "!!!"]), (13, ["***"])]

        def in_folder(_prof, folder):
            return [{"id": folder * 10, "name": "->" if folder == 13 else order}]

        with (
            patch.object(wkrepo, "walk_folders", return_value=folders),
            patch.object(wkrepo, "list_recipes", side_effect=in_folder),
        ):
            found_folders, recipes = sync.remote_state("profile", {"folder_id": 10})
        files = sorted(recipe["file"] for recipe in recipes)
        self.assertEqual(
            files,
            sorted(
                [
                    f"100-{order.lower()}.recipe.json",
                    "unnamed/130-unnamed.recipe.json",
                    f"{archive.lower()}/110-{order.lower()}.recipe.json",
                    f"{archive.lower()}/unnamed/120-{order.lower()}.recipe.json",
                ]
            ),
        )
        for path in [*files, *(folder["path"] for folder in found_folders)]:
            with self.subTest(path=path):
                self.assertFalse(path.startswith("/"))
                self.assertNotIn("//", path)
        keys = {recipe["match_key"] for recipe in recipes}
        self.assertEqual(len(keys), len(recipes), "two folders must not share a match key")

    def test_a_pull_that_is_not_a_recipe_document_is_refused(self):
        self.assertEqual(sync.recipe_version(document(7)), 7)
        for invalid in (b"", b"null", b'{"code": "text"}'):
            with self.subTest(invalid=invalid), self.assertRaises(cli.Error):
                sync.recipe_version(invalid)


if __name__ == "__main__":
    unittest.main()

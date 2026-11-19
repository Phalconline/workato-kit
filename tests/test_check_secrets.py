"""scripts/check_secrets.py: a token-shaped string is found and its value is never printed.

The samples are put together at run time, so this file holds nothing the scan would report.
"""

import json
import unittest
from unittest.mock import patch

import check_secrets
from tests import support

SAMPLES = {
    "Slack token": "xox" + "b-" + "1" * 10 + "-abcdefghij",
    "AWS access key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "GitHub token": "gh" + "p_" + "a" * 36,
    "private key": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "bearer token": "Bearer " + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4",
    "Workato API token": "wrk" + "prod_" + "b" * 40,
    "API key (sk-)": "sk" + "-" + "c" * 40,
    "Workato webhook address": "https://{}.workato.com/webhooks/rest/".format("webhooks")
    + "a1b2-" * 6,
    "secret assigned in text": "api_key" + " = " + "a1" * 12,
}


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_dir(self, "secrets-")
        support.start(self, patch.object(check_secrets, "ROOT", self.root))

    def scan(self, name, text):
        file = self.root / name
        file.write_text(text, encoding="utf-8")
        return list(check_secrets.findings(file))

    def test_each_token_format_is_found_and_its_value_is_not_printed(self):
        for kind, sample in SAMPLES.items():
            with self.subTest(kind=kind):
                found = self.scan("notes.md", f"first line\nvalue: {sample}\n")
                self.assertEqual(found, [f"notes.md:2: {kind}"])
                self.assertNotIn(sample, " ".join(found))

    def test_ordinary_text_is_not_reported(self):
        text = (
            "Use the token of the connection.\nNever paste a password here.\nsk-short\n"
            "token: recipe_builder_list_connections\npassword = <ask the maintainer>\n"
            "https://www.workato.com/webhooks is a page of the docs\n"
        )
        self.assertEqual(self.scan("notes.md", text), [])

    def test_a_secret_is_found_whatever_the_case_of_its_keyword(self):
        for line in (
            "authorization: bearer " + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4",
            "Authorization: BEARER " + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4",
            "TOKEN=" + "9z" * 12,
        ):
            with self.subTest(line=line[:14]):
                self.assertEqual(len(self.scan("notes.md", line + "\n")), 1)

    def test_a_literal_secret_in_recipe_json_is_reported_by_its_path(self):
        recipe = {"code": {"input": {"api_key": "A1b2C3d4E5f6G7h8", "password": "#{_dp('x')}"}}}
        found = self.scan("1-example.recipe.json", json.dumps(recipe))
        self.assertEqual(found, ["1-example.recipe.json: literal value under /code/input/api_key"])

    def test_datapills_formulas_labels_and_sentences_are_not_literal_secrets(self):
        step_input = {
            "password": '=_dp(\'{"pill_type":"project_property"}\')',
            "token": "ask the owner for it",
            "client_secret": "short",
            "authorization": {"label": "Authorization header value"},
            "secret": '{"nested": "object text"}',
        }
        found = self.scan("1-example.recipe.json", json.dumps({"code": {"input": step_input}}))
        self.assertEqual(found, [])

    def test_a_binary_file_is_skipped(self):
        file = self.root / "image.png"
        file.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
        self.assertEqual(list(check_secrets.findings(file)), [])


if __name__ == "__main__":
    unittest.main()

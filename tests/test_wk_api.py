"""scripts/wk_api.py with a fake transport: no Workato call and no real credential."""

import http.server
import io
import json
import threading
import unittest
import urllib.error
from unittest.mock import patch

import wk_api as api
from lib import wkrepo
from tests import support

TOKEN = "fake-token-for-tests"
US_API = "https://www.workato.com/api"
US_RECORDS = "https://data-tables.workato.com/api/v1"
TABLE = "/tables/0f1e2d3c-4b5a-4978-8695-a4b3c2d1e0f9"


class Response:
    """What the opener returns for a successful call."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        return False

    def read(self):
        return self.body


class WkApiTests(unittest.TestCase):
    def call(self, *argv, response=b'{"ok": true}', error=None, api_root=US_API):
        """Run main() with a fake transport.

        Returns the result, the requests that were sent, and how often `wk` was asked for the
        token or for the API root of the profile.
        """
        sent = []

        def open_(request, timeout=None):
            sent.append(request)
            if error:
                raise error
            return Response(response)

        with (
            patch.object(wkrepo, "token", return_value=TOKEN) as token,
            patch.object(wkrepo, "profile", return_value="profile"),
            patch.object(wkrepo, "api_url", return_value=api_root) as located,
            patch.object(wkrepo, "data_tables_api_url", return_value=US_RECORDS),
            patch.object(wkrepo.OPENER, "open", open_),
        ):
            result = support.run_main(api.main, *argv)
        return result, sent, token.call_count + located.call_count

    def test_get_sends_token_only_in_the_header_and_never_prints_it(self):
        result, sent, _ = self.call(
            "dev", "GET", "/deployments", "-q", "project_id=1", "-q", "includes[]=tags"
        )
        self.assertEqual(result.code, 0)
        self.assertEqual(
            sent[0].full_url,
            "https://www.workato.com/api/deployments?project_id=1&includes%5B%5D=tags",
        )
        self.assertEqual(sent[0].get_method(), "GET")
        self.assertEqual(sent[0].get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(json.loads(result.out), {"ok": True})
        self.assertNotIn(TOKEN, result.out + result.err)

    def test_the_request_goes_to_the_data_center_of_the_profile(self):
        _, sent, _ = self.call("dev", "GET", "/recipes", api_root="https://app.eu.workato.com/api")
        self.assertEqual(sent[0].full_url, "https://app.eu.workato.com/api/recipes")

    def test_leading_api_segment_and_lower_case_method_are_accepted(self):
        _, sent, _ = self.call("prod", "get", "/api/deployments")
        self.assertEqual(sent[0].full_url, "https://www.workato.com/api/deployments")

    def test_data_tables_calls_go_to_the_record_api_and_a_query_needs_no_write_flag(self):
        result, sent, _ = self.call(
            "dev", "POST", f"{TABLE}/query", "--data-tables", "--json", '{"limit": 5}'
        )
        self.assertEqual(result.code, 0)
        self.assertEqual(sent[0].full_url, f"{US_RECORDS}{TABLE}/query")
        self.assertEqual(sent[0].get_header("Authorization"), f"Bearer {TOKEN}")
        _, sent, _ = self.call("dev", "post", f"/api/v1{TABLE}/query", "--data-tables")
        self.assertEqual(sent[0].full_url, f"{US_RECORDS}{TABLE}/query")
        _, sent, _ = self.call("dev", "GET", f"{TABLE}/records/7/fields/2/file", "--data-tables")
        self.assertEqual(sent[0].full_url, f"{US_RECORDS}{TABLE}/records/7/fields/2/file")

    def test_a_record_write_needs_the_flag_like_every_other_write(self):
        cases = (("POST", f"{TABLE}/records"), ("PUT", f"{TABLE}/records/7"), ("DELETE", TABLE))
        for method, path in cases:
            with self.subTest(method=method, path=path):
                result, sent, lookups = self.call("dev", method, path, "--data-tables")
                self.assertEqual((result.code, sent, lookups), (2, [], 0))
                self.assertIn("--write", result.err)
        result, sent, _ = self.call(
            "dev", "POST", f"{TABLE}/records", "--data-tables", "--write", "--json", "{}"
        )
        self.assertEqual((result.code, sent[0].get_method()), (0, "POST"))
        # Without --data-tables a path that ends in /query is a write like any other POST.
        result, sent, _ = self.call("dev", "POST", f"{TABLE}/query")
        self.assertEqual((result.code, sent), (2, []))

    def test_data_tables_calls_stay_below_tables(self):
        for path in ("/recipes", "/properties", "/tables", "/api/v1/users"):
            with self.subTest(path=path):
                result, sent, lookups = self.call("dev", "GET", path, "--data-tables")
                self.assertEqual((result.code, sent, lookups), (2, [], 0))
                self.assertIn("must start with /tables/", result.err)

    def test_write_needs_the_flag_and_is_refused_before_any_credential_lookup(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                result, sent, lookups = self.call(
                    "dev", method, "/projects/1/deploy", "--json", '{"environment_type": "prod"}'
                )
                self.assertEqual((result.code, sent, lookups), (2, [], 0))
                self.assertIn("--write", result.err)

    def test_write_with_the_flag_sends_the_json_body(self):
        result, sent, _ = self.call(
            "dev",
            "POST",
            "/projects/1/deploy",
            "--json",
            '{"environment_type": "prod"}',
            "--write",
        )
        self.assertEqual(result.code, 0)
        self.assertEqual(sent[0].get_method(), "POST")
        self.assertEqual(json.loads(sent[0].data), {"environment_type": "prod"})
        self.assertEqual(sent[0].get_header("Content-type"), "application/json")

    def test_a_path_that_could_leave_the_api_is_refused(self):
        paths = (
            "https://example.com/x",
            "deployments",
            "//example.com/x",
            "/a/../b",
            "/x?y=1",
            "/x#y",
            "/x y",
            "/recipes/%2e%2e/properties",
            "/a/./b",
            "/.hidden",
        )
        for path in paths:
            with self.subTest(path=path):
                result, sent, lookups = self.call("dev", "GET", path)
                self.assertEqual((result.code, sent, lookups), (2, [], 0))

    def test_a_redirect_is_never_followed_with_the_token(self):
        # Two real local servers: the first redirects to the second, which must see nothing.
        seen = []

        class Redirecting(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{other.server_port}/elsewhere")
                self.end_headers()

            do_POST = do_GET  # noqa: N815 - the name http.server looks for

            def log_message(self, *_args):
                pass

        class Other(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            do_POST = do_GET  # noqa: N815 - the name http.server looks for

            def log_message(self, *_args):
                pass

        first = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)
        other = http.server.HTTPServer(("127.0.0.1", 0), Other)
        for server in (first, other):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        local_api = f"http://127.0.0.1:{first.server_port}/api"
        with (
            patch.object(wkrepo, "token", return_value=TOKEN),
            patch.object(wkrepo, "profile", return_value="profile"),
            patch.object(wkrepo, "api_url", return_value=local_api),
        ):
            read = support.run_main(api.main, "dev", "GET", "/packages/1/download")
            write = support.run_main(
                api.main, "dev", "POST", "/packages/export/1", "--json", "{}", "--write"
            )
        self.assertEqual((read.code, write.code), (1, 1))
        self.assertEqual(seen, [])
        self.assertIn("HTTP 302", read.err)
        self.assertNotIn(TOKEN, read.err + write.err)

    def test_malformed_query_and_body_are_refused(self):
        cases = (
            ["-q", "novalue"],
            ["-q", "=x"],
            ["--json", "{not json", "--write"],
            ["--json-file", "no-such-file.json", "--write"],
        )
        for extra in cases:
            with self.subTest(extra=extra):
                method = "POST" if "--write" in extra else "GET"
                result, sent, lookups = self.call("dev", method, "/recipes", *extra)
                self.assertEqual((result.code, sent, lookups), (2, [], 0))
                self.assertNotIn("Traceback", result.err)
        result, sent, _ = self.call("dev", "GET", "/recipes", "--json", "{}")
        self.assertEqual((result.code, sent), (2, []))

    def test_every_property_at_once_is_refused_in_every_spelling(self):
        paths = (
            "/properties",
            "/properties/",
            "/properties.json",
            "/api/properties.json",
            "/Properties",
        )
        for path in paths:
            for query in ([], ["-q", "prefix="], ["-q", "project_id=1"]):
                with self.subTest(path=path, query=query):
                    result, sent, lookups = self.call("dev", "GET", path, *query)
                    self.assertEqual((result.code, sent, lookups), (2, [], 0))
                    self.assertIn("prefix", result.err)

    def test_only_the_named_property_is_printed(self):
        values = {"slack_channel": "C1", "slack_channel_token": "do-not-print", "other": "x"}
        answer = json.dumps(values).encode()
        result, sent, _ = self.call(
            "dev",
            "GET",
            "/properties",
            "-q",
            "prefix=slack_channel",
            "-q",
            "project_id=1",
            response=answer,
        )
        self.assertEqual((result.code, len(sent)), (0, 1))
        self.assertEqual(json.loads(result.out), {"slack_channel": "C1"})
        self.assertNotIn("do-not-print", result.out)
        result, _, _ = self.call(
            "dev", "GET", "/properties", "-q", "prefix=slack", response=answer
        )
        self.assertEqual(json.loads(result.out), {})
        self.assertIn("No property named 'slack'", result.err)

    def test_a_property_answer_of_another_shape_is_withheld(self):
        for answer in (b'[{"name": "a", "value": "do-not-print"}]', b"a=do-not-print"):
            with self.subTest(answer=answer):
                result, _, _ = self.call(
                    "dev", "GET", "/properties", "-q", "prefix=a", response=answer
                )
                self.assertEqual(result.code, 1)
                self.assertNotIn("do-not-print", result.out + result.err)

    def test_a_failed_property_read_is_not_reported_as_an_empty_success(self):
        result, _, _ = self.call(
            "dev", "GET", "/properties", "-q", "prefix=a", response=b'{"success": false}'
        )
        self.assertEqual(result.code, 1)
        self.assertIn("did not do what was asked", result.err)

    def test_write_cannot_be_abbreviated(self):
        result, sent, lookups = self.call("dev", "POST", "/recipes/1/stop", "--w")
        self.assertEqual((result.code, sent, lookups), (2, [], 0))

    def test_success_false_in_a_200_answer_is_a_failed_call(self):
        result, _, _ = self.call(
            "dev",
            "PUT",
            "/recipes/1/start",
            "--write",
            response=b'{"success": false, "code_errors": []}',
        )
        self.assertEqual(result.code, 1)
        self.assertIn('"success": false', result.out)
        self.assertIn("did not do what was asked", result.err)

    def test_http_error_is_reported_without_the_token(self):
        failure = urllib.error.HTTPError(
            "https://www.workato.com/api/x",
            403,
            "Forbidden",
            {},  # type: ignore[arg-type]
            io.BytesIO(f"denied for {TOKEN}".encode()),
        )
        result, _, _ = self.call("dev", "GET", "/x", error=failure)
        self.assertEqual(result.code, 1)
        self.assertIn("HTTP 403", result.err)
        self.assertNotIn(TOKEN, result.out + result.err)

    def test_an_error_answer_whose_body_cannot_be_read_is_still_reported(self):
        class Gone(io.BytesIO):
            def read(self, *_args):
                raise ConnectionResetError("reset by peer")

        failure = urllib.error.HTTPError(
            "https://www.workato.com/api/x",
            302,
            "Found",
            {},  # type: ignore[arg-type]
            Gone(),
        )
        result, _, _ = self.call("dev", "GET", "/x", error=failure)
        self.assertEqual(result.code, 1)
        self.assertIn("HTTP 302", result.err)

    def test_network_error_is_reported(self):
        result, _, _ = self.call("dev", "GET", "/x", error=urllib.error.URLError("no route"))
        self.assertEqual(result.code, 1)
        self.assertIn("no route", result.err)

    def test_a_connection_that_breaks_is_named_by_its_kind_not_traced(self):
        for failure in (TimeoutError("timed out"), ConnectionResetError("reset by peer")):
            result, _, _ = self.call("dev", "GET", "/x", error=failure)
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(result.code, 1)
                self.assertIn(f"({type(failure).__name__})", result.err)
                self.assertNotIn("Traceback", result.err)

    def test_non_json_and_empty_responses_do_not_crash(self):
        plain, _, _ = self.call("dev", "GET", "/x", response=b"plain text")
        self.assertEqual((plain.code, plain.out), (0, "plain text\n"))
        empty, _, _ = self.call("dev", "GET", "/x", response=b"")
        self.assertEqual((empty.code, empty.out), (0, ""))

    def test_an_unknown_environment_is_a_bad_argument(self):
        result, sent, lookups = self.call("test", "GET", "/recipes")
        self.assertEqual((result.code, sent, lookups), (2, [], 0))


if __name__ == "__main__":
    unittest.main()

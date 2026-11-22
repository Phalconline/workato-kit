#!/usr/bin/env python3.14
"""Call one Workato API endpoint that `wk` does not cover; the token never reaches the shell.

    scripts/wk_api.py dev GET /deployments -q project_id=<id>
    scripts/wk_api.py prod GET /recipes -q folder_id=<id> -q 'includes[]=tags'
    scripts/wk_api.py dev POST /projects/<id>/deploy --write --json '{"environment_type": "prod"}'
    scripts/wk_api.py dev POST /tables/<uuid>/query --data-tables --json '{"limit": 5}'
    scripts/wk_api.py dev POST /tables/<uuid>/records --data-tables --write --json-file row.json

The environment (dev or prod) selects the `wk` profile of the registry. The path is relative to
the developer API of that profile's data center (https://www.workato.com/api for the US one) and
starts with a slash; a leading /api is accepted. The token is read from `wk` inside this process
and is never printed. It is sent only to the host `wk` holds for the profile: a redirect is
reported as an error, never followed.

With --data-tables the call goes to the record API of data tables instead: the host
`data-tables` of the same data center, below /api/v1, with the same token and the same rules.
Only paths under /tables/ are allowed there (a leading /api/v1 is accepted), and a table is named
by its UUID, not by its numeric id. A POST to .../query only reads, so it needs no --write. What a
query returns is table data: it can hold personal data and never goes into the repository
(AGENTS.md, "No secrets and no table data in the repository").

Anything but GET changes Workato and needs --write. The flag only stops an accident. Whether the
change may be made at all is decided by AGENTS.md: a start, a stop, a deletion and any write in
Prod need the request to say so. Workato can answer HTTP 200 with "success": false; that is
reported as a failed call.

GET /properties prints a property value, and a property can hold a secret. Name the property
with -q prefix=<full name>: only that property is printed; a request for all of them is refused.

Exit status: 0 success; 1 the call failed; 2 the request was refused, or `wk` gave no token.
"""

import argparse
import http.client
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
FORBIDDEN_IN_PATH = "?#\\% \t\r\n"
SHOWN_ERROR_LENGTH = 2000
RECORD_API_PREFIX = "/api/v1"  # where the data tables host serves its record API
# The method, the path with its query (relative to the API root), the body, and the one property
# a property read may print.
type Call = tuple[str, str, bytes | None, str | None]


def api_path(path: str) -> str:
    """Return the path relative to the API root, or refuse one that could leave it."""
    if path == "/api" or path.startswith("/api/"):
        path = path.removeprefix("/api")
    if not path.startswith("/") or path.startswith("//"):
        raise cli.Error("the path must start with one slash, relative to the API: /deployments")
    if any(char in path for char in FORBIDDEN_IN_PATH):
        raise cli.Error(
            "the path may not contain a query, a fragment, percent-encoding or whitespace; "
            "pass query fields with -q"
        )
    if any(segment.startswith(".") for segment in path.split("/")):
        raise cli.Error("the path may not contain a segment that starts with a dot")
    return path


def data_tables_path(path: str) -> str:
    """Return a path of the data tables record API, or refuse one outside /tables/."""
    if path == RECORD_API_PREFIX or path.startswith(RECORD_API_PREFIX + "/"):
        path = path.removeprefix(RECORD_API_PREFIX)
    path = api_path(path)
    if not path.startswith("/tables/"):
        raise cli.Error(
            "with --data-tables the path must start with /tables/: /tables/<uuid>/query"
        )
    return path


def query_pairs(items: list[str]) -> list[tuple[str, str]]:
    """Split each KEY=VALUE of -q; refuse an item without a key or without `=`."""
    pairs = []
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise cli.Error(f"-q needs KEY=VALUE, got '{item}'")
        pairs.append((key, value))
    return pairs


def request_body(args: argparse.Namespace) -> bytes | None:
    """Return the JSON body of the request, checked to be valid JSON."""
    text = args.body
    if args.json_file:
        try:
            text = Path(args.json_file).read_text(encoding="utf-8")
        except OSError as error:
            raise cli.Error(f"cannot read {args.json_file}: {error.strerror}") from None
    if text is None:
        return None
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        raise cli.Error(f"the body is not valid JSON: {error}") from None
    return str(text).encode("utf-8")


def build(args: argparse.Namespace) -> Call:
    """Return the request to send, or refuse it. Neither `wk` nor a credential is touched here."""
    path = data_tables_path(args.path) if args.data_tables else api_path(args.path)
    pairs = query_pairs(args.query)
    body = request_body(args)
    if args.method == "GET" and body is not None:
        raise cli.Error("a GET takes no body")
    # A query of the record API is a POST that only reads.
    record_query = args.data_tables and args.method == "POST" and path.endswith("/query")
    if args.method != "GET" and not record_query and not args.write:
        raise cli.Error(
            f"{args.method} changes Workato; repeat the command with --write "
            "if the request asked for this change"
        )
    only_property = None
    # Any path segment named "properties", with or without an extension, reads property values.
    segments = {segment.split(".")[0].lower() for segment in path.split("/")}
    if args.method == "GET" and "properties" in segments:
        only_property = dict(pairs).get("prefix")
        if not only_property:
            raise cli.Error(
                "GET /properties prints property values; "
                "name the property with -q prefix=<full name>"
            )
    if pairs:
        path += "?" + urllib.parse.urlencode(pairs)
    return args.method, path, body, only_property


def parse(raw: bytes) -> Any:
    """Return the answer as parsed JSON, or as text when it is not JSON."""
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def error_body(error: urllib.error.HTTPError) -> str:
    """Return the body of an error answer; empty when the server already closed the connection."""
    try:
        return error.read().decode("utf-8", "replace")
    except OSError:
        return ""


def send(call: Call, api_url: str, token: str) -> Any:
    """Send the request to an API root and return the parsed answer; None when the call failed."""
    method, path, data, _only_property = call
    url = api_url + path
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 - api_url is the https root wk holds for the profile
    try:
        with wkrepo.OPENER.open(request, timeout=wkrepo.TIMEOUT) as response:
            return parse(response.read())
    except urllib.error.HTTPError as error:
        with error:
            detail = error_body(error).replace(token, "<token>")
        print(
            f"HTTP {error.code} {error.reason}: {method} {url}\n{detail[:SHOWN_ERROR_LENGTH]}",
            file=sys.stderr,
        )
    except urllib.error.URLError as error:
        print(f"Request failed: {method} {url}: {error.reason}", file=sys.stderr)
    except (OSError, ValueError, http.client.HTTPException) as error:
        # The text of such an error can quote the request, its headers included: name its type.
        print(f"Request failed: {method} {url} ({type(error).__name__})", file=sys.stderr)
    return None


def main(argv: list[str] | None = None) -> int:
    """Send one API request and print the answer; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("environment", choices=wkrepo.ENVIRONMENTS)
    parser.add_argument("method", type=str.upper, choices=METHODS)
    parser.add_argument("path", help="API path, for example /deployments")
    parser.add_argument(
        "-q",
        "--query",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="query field; repeatable",
    )
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--json", dest="body", metavar="JSON", help="request body")
    body.add_argument("--json-file", metavar="FILE", help="file holding the request body")
    parser.add_argument("--write", action="store_true", help="required for anything but GET")
    parser.add_argument(
        "--data-tables",
        action="store_true",
        help="call the record API of data tables (paths under /tables/) instead of the main API",
    )
    args = parser.parse_args(argv)

    call = build(args)
    only_property = call[3]
    profile = wkrepo.profile(args.environment)
    root = wkrepo.data_tables_api_url(profile) if args.data_tables else wkrepo.api_url(profile)
    answer = send(call, root, wkrepo.token(profile))
    if answer is None:
        return cli.EXIT_FINDINGS

    failed = isinstance(answer, dict) and answer.get("success") is False
    if only_property is not None and not failed:
        if not isinstance(answer, dict):
            # Not the name-to-value object a property read returns: it could hold every value.
            print("The answer is not a property list; it is withheld.", file=sys.stderr)
            return cli.EXIT_FINDINGS
        if only_property not in answer:
            print(f"No property named '{only_property}'.", file=sys.stderr)
        answer = {name: value for name, value in answer.items() if name == only_property}
    if isinstance(answer, str):
        if answer.strip():
            print(answer)
    else:
        print(json.dumps(answer, indent=2, ensure_ascii=False))
    if failed:
        print(
            'Workato answered "success": false: the call did not do what was asked.',
            file=sys.stderr,
        )
        return cli.EXIT_FINDINGS
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

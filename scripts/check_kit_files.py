#!/usr/bin/env python3.14
"""Check that the files the kit owns hold nothing of a workspace.

    scripts/check_kit_files.py

The kit is public; a repository built from it is private. The ids, addresses, hosts and names of
a workspace belong in workato/workspaces/<workspace>/ and in docs/<project>/. They must never
enter a file the kit owns (scripts, tests, skills, rules, setup docs), because such a file can
travel back to the kit with a contribution. This check runs in the kit and in every repository
built from it.

A finding in a kit-owned file is:
- NUMBER: a number of five or more digits, the shape of a Workato id;
- ADDRESS: an e-mail address outside the example domains;
- HOST: a web address whose host is not on the list of public hosts in this script, or the
  address of a webhook or of an API endpoint at Workato;
- CODE: a bracket code such as [XY] other than the ones the examples use;
- TICKET: the key of a ticket, such as XY-12, other than the ones the examples use;
- DATE: a date before 2030 (examples use 2030; CHANGELOG.md is exempt);
- SCRIPT: text in a non-Latin script;
- PATH: the home directory of a person;
- NAME: a name the registry of this repository holds: a wk profile, the name of a Workato
  workspace, a company domain, and a project name or a maintainer of two or more words;
- LINK: a symbolic link, which can make a tracked file out of any file.

A shape cannot catch every name: a one-word project name, a connection or a recipe name passes.
Read a change to a kit-owned file before you send it anywhere.

Not checked, because a workspace owns them: workato/workspaces/<workspace>/, docs/<project>/,
docs/recipe-index.md, docs/conventions/decisions.md, docs/knowledge/workspace/, the last section
of AGENTS.md ("Rules of this workspace"), the workspace's own scripts, tests, skills and CI
workflows (scripts/ws_*.py, scripts/lib/ws_*.py, tests/test_ws_*.py, .agents/skills/ws-*/,
.github/workflows/ws-*), and the generated harness files. The two vendor skills are checked by
their publisher, not here. The copyright line of LICENSE is not checked either: it names the
copyright holder of the kit.

A real exception is added to the lists in this script, in a commit that says why.

Exit status: 0 nothing found; 1 at least one finding.
"""

import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo

ROOT = wkrepo.ROOT
WORKSPACE_SECTION = "## Rules of this workspace"
KIT_DOCS = {"setup", "conventions", "knowledge"}  # folders of docs/ that the kit owns
WORKSPACE_FILES = {"docs/recipe-index.md", "docs/conventions/decisions.md"}
WORKSPACE_PREFIXES = (
    "docs/knowledge/workspace/",
    "scripts/ws_",
    "scripts/lib/ws_",
    "tests/test_ws_",
    ".agents/skills/ws-",
    ".github/workflows/ws-",
    "tmp/",
)
GENERATED_PREFIXES = (".claude/", ".codex/agents/", ".cursor/", ".gemini/")
GENERATED_FILES = {
    ".mcp.json",
    ".codex/config.toml",
    ".agents/mcp_config.json",
    ".agents/generated-files.json",
}
VENDOR_PREFIXES = (
    ".agents/skills/search-company-knowledge/",
    ".agents/skills/triage-issue/",
    ".agents/licenses/",
)

# An id may end a sentence, start a file name (<id>-<name>.md) or follow a "#".
NUMBER = re.compile(r"(?<![\w.])\d{5,}(?!\w|\.\d)")
# The last label of a domain has letters only: `python@3.14` is a package, not an address.
ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")
CODE = re.compile(r"\[([A-Z]{2,6})\]")
HOME = re.compile(r"/Users/[A-Za-z]|/home/[a-z]|[A-Z]:\\\\?Users\\")

TICKET = re.compile(r"(?<![A-Za-z0-9-])([A-Z][A-Z0-9]{1,9})-\d+(?![A-Za-z0-9-])")
EARLY_DATE = re.compile(r"(?<![\d-])(?:19\d\d|20[0-2]\d)-\d\d-\d\d(?![\d-])")
DATED_FILES = {"CHANGELOG.md"}  # release dates are real dates
# The copyright line of the license names the holder of the kit: a real name and real pages.
NOTICE_FILES = {"LICENSE"}
NOTICE_LINE = "Copyright "

EXAMPLE_HOST = re.compile(r"(^|\.)example(\.(com|org|net))?$")
# Hosts a kit-owned file may name: the vendor's own, and public documentation. Nothing else.
PUBLIC_HOSTS = {
    "workato.com",
    "app.workatoapp.cn",
    "github.com",
    "raw.githubusercontent.com",
    "docs.github.com",
    "users.noreply.github.com",
    "mcp.atlassian.com",
    "www.atlassian.com",
    "developer.atlassian.com",
    "support.atlassian.com",
    "json.schemastore.org",
    "www.apache.org",
    "docs.astral.sh",
    "mypy.readthedocs.io",
    "docs.python.org",
    "peps.python.org",
    "code.claude.com",
    "docs.claude.com",
    "developers.openai.com",
    "cursor.com",
    "docs.cursor.com",
    "geminicli.com",
    "brew.sh",
    "scoop.sh",
    "localhost",
    "127.0.0.1",
}
PUBLIC_DOMAINS = (".workato.com",)
# Hosts of Workato that address one workspace: a webhook starts a recipe without a credential,
# and an API endpoint carries the workspace's own prefix.
PRIVATE_HOST_LABELS = ("webhooks", "apim")
# Bracket codes of the examples, and one that is a character class of a regular expression.
EXAMPLE_CODES = {"SO", "CM", "CG"}
# Prefixes that look like a ticket key and are none: the examples' own, and names of standards.
PLAIN_PREFIXES = {
    "SO", "CM", "UTF", "ISO", "SHA", "PEP", "RFC", "CVE", "HTTP", "TLS", "ADR", "RSA", "AES",
    "UTC", "GMT", "MD", "PLR", "SIM", "RUF", "ISC", "BLE",
}  # fmt: skip
# Names of the examples: a workspace that is really called so is not reported for it.
EXAMPLE_NAMES = {
    "acme", "acme-dev", "acme-prod", "acme (dev)", "acme.example", "sales orders", "common",
    "sandbox", "the maintainer", "integration lead",
}  # fmt: skip
MIN_NAME_LENGTH = 4
# Numbers that are not ids: none so far. Add one here only with the reason in the commit.
PLAIN_NUMBERS: set[str] = set()


def kit_owned(relative: str) -> bool:
    """Tell whether the kit owns a file, by its path in the repository."""
    if relative in WORKSPACE_FILES | GENERATED_FILES:
        return False
    if relative.startswith(WORKSPACE_PREFIXES + GENERATED_PREFIXES + VENDOR_PREFIXES):
        return relative == "tmp/README.md"
    match PurePosixPath(relative).parts:
        case ("workato", "workspaces", _, _, *_):  # inside a workspace folder
            return False
        case ("docs", folder, _, *_):  # docs/<project>/ belongs to the workspace
            return folder in KIT_DOCS
    return True


def candidate_files() -> list[str]:
    """Return every file git tracks or would track, relative to the repository root."""
    listed = subprocess.run(
        [wkrepo.executable("git"), "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(path for path in listed.stdout.split("\0") if path)


def public_host(host: str) -> bool:
    """Tell whether a host is the vendor's, public documentation or an example."""
    host = host.lower().rstrip(".")
    if host.endswith(PUBLIC_DOMAINS) and host.split(".")[0] in PRIVATE_HOST_LABELS:
        return False
    return host in PUBLIC_HOSTS or host.endswith(PUBLIC_DOMAINS) or bool(EXAMPLE_HOST.search(host))


def workspace_names() -> list[re.Pattern[str]]:
    """Return a pattern for each name of this repository's workspace that a kit file must not hold.

    Read from every registry: both wk profiles, the names of the two Workato workspaces, the
    company domains, the maintainer, and project names of two or more words. A name that is one
    plain word is left out: it would match ordinary prose.
    """
    names: set[str] = set()
    for path in sorted(wkrepo.WORKSPACES.glob(f"*/{wkrepo.REGISTRY_NAME}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if not isinstance(data, dict):
            continue
        environments = data.get("environments")
        for env in environments.values() if isinstance(environments, dict) else []:
            if isinstance(env, dict):
                names.update(str(env.get(key) or "") for key in ("profile", "workspace"))
        domains = data.get("company_domains")
        names.update(str(domain) for domain in (domains if isinstance(domains, list) else []))
        projects = data.get("projects")
        entries = projects.values() if isinstance(projects, dict) else []
        phrases = [str(entry.get("name") or "") for entry in entries if isinstance(entry, dict)]
        phrases.append(str(data.get("maintainer") or ""))
        names.update(phrase for phrase in phrases if len(phrase.split()) > 1)
    kept = sorted(
        name.strip()
        for name in names
        if len(name.strip()) >= MIN_NAME_LENGTH and name.strip().lower() not in EXAMPLE_NAMES
    )
    return [re.compile(rf"(?<![\w.@-]){re.escape(name)}(?![\w-])", re.IGNORECASE) for name in kept]


def foreign_script(text: str) -> str | None:
    """Return the first letter of the text that is not Latin, or None."""
    for char in text:
        if not char.isascii() and char.isalpha() and "LATIN" not in unicodedata.name(char, ""):
            return char
    return None


def shape_findings(line: str) -> Iterator[tuple[str, str]]:
    """Yield what has the shape of an id, an address, a host, a code or a ticket key."""
    for number in NUMBER.findall(line):
        if number not in PLAIN_NUMBERS:
            yield "NUMBER", number
    for match in ADDRESS.finditer(line):
        if not public_host(match.group(1)):
            yield "ADDRESS", match.group(0)
    for host in URL_HOST.findall(line):
        if not public_host(host):
            yield "HOST", host
    for code in CODE.findall(line):
        if code not in EXAMPLE_CODES:
            yield "CODE", f"[{code}]"
    for ticket in TICKET.finditer(line):
        if ticket.group(1) not in PLAIN_PREFIXES:
            yield "TICKET", ticket.group(0)


def line_findings(
    line: str, names: list[re.Pattern[str]] | None = None, *, dated: bool = False
) -> Iterator[tuple[str, str]]:
    """Yield (kind, token) for everything in one line that has the shape of workspace data.

    Args:
        line: One line of a kit-owned file, or its path.
        names: The names of this repository's workspace, as patterns.
        dated: The file holds real dates, so a date before 2030 is no finding.
    """
    yield from shape_findings(line)
    for date in [] if dated else EARLY_DATE.findall(line):
        yield "DATE", date
    for name in names or []:
        found = name.search(line)
        if found:
            yield "NAME", found.group(0)
    letter = foreign_script(line)
    if letter:
        yield "SCRIPT", unicodedata.name(letter, "a non-Latin letter").lower()
    if HOME.search(line):
        yield "PATH", "a home directory"


def file_findings(relative: str, names: list[re.Pattern[str]] | None = None) -> Iterator[str]:
    """Yield one report line per finding in a kit-owned file; a binary file yields nothing."""
    for kind, token in line_findings(relative, names, dated=True):
        yield f"{relative}: {kind} in the file name: {token}"
    if (ROOT / relative).is_symlink():
        yield f"{relative}: LINK a symbolic link"
        return
    try:
        text = (ROOT / relative).read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return
    if relative == "AGENTS.md":
        text = text.split(WORKSPACE_SECTION, 1)[0]
    for number, line in enumerate(text.split("\n"), 1):
        if relative in NOTICE_FILES and line.startswith(NOTICE_LINE):
            continue
        for kind, token in line_findings(line, names, dated=relative in DATED_FILES):
            yield f"{relative}:{number}: {kind} {token}"


def main(argv: list[str] | None = None) -> int:
    """Check every kit-owned file; return the exit status."""
    cli.parser(__doc__).parse_args(argv)
    this_script = Path(__file__).resolve()
    owned = [
        relative
        for relative in candidate_files()
        if kit_owned(relative) and (ROOT / relative).resolve() != this_script
    ]
    found = 0
    names = workspace_names()
    for relative in owned:
        for line in file_findings(relative, names):
            print(line)
            found += 1
    print(f"checked {len(owned)} kit-owned files, {found} finding(s)")
    if found:
        print("Move workspace data to workato/workspaces/<workspace>/ or docs/<project>/.")
    return cli.EXIT_FINDINGS if found else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

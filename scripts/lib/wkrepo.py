"""The repository's view of Workato: the workspace folder, the registry, `wk` and the API.

Everything here only reads Workato. The API token is taken from `wk auth token` inside this
process and is never printed or written to disk. It is sent only to the host that `wk` itself
holds for the profile, and only when that is a host of Workato; never to a host named in a file
of the repository. A read that cannot be made raises `cli.Error`.

`wk` keeps a token in the OS keychain or, for a machine without one, in `profiles.env` in the
repository root (its file store). `wk auth list` says which store a profile uses; the functions
here pass `--store-type file` for a file profile, so the callers never have to.
"""

import functools
import http.client
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib import cli

type Json = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
WORKSPACES = ROOT / "workato" / "workspaces"
DEV_CACHE = ROOT / "tmp" / "wk" / "dev"
ENVIRONMENTS = ("dev", "prod")
REGISTRY_NAME = "registry.json"
NO_WORKSPACE = "no workspace yet: run scripts/init_workspace.py (docs/setup/new-workspace.md)"
US_API_HOST = "https://www.workato.com"
US_APP_HOST = "https://app.workato.com"
# Every data center and preview host of Workato is below one of these two domains.
WORKATO_DOMAINS = (".workato.com", ".workatoapp.cn")
# A project slug is a folder name in three places, so it may hold nothing a path could abuse.
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
RESERVED_SLUGS = frozenset({"setup", "conventions", "knowledge", "kit"})  # folders of docs/
# A profile name becomes an argument of `wk` and part of a permission rule.
PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
# The house checks of scripts/lint_recipes.py that a project switches on with `lint_checks`.
LINT_CHECKS = ("ACCOUNT_PROPERTY", "NO_GUARD_PROPERTY")
HTML_PAGE = re.compile(r"<!doctype|<html", re.IGNORECASE)
ERROR_SHOWN = 400
TIMEOUT = 60
PAGE_SIZE = 100


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would send the Authorization header on to the new host."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


# Every API call of the repository goes through this opener; a redirect ends as an HTTPError.
OPENER = urllib.request.build_opener(_NoRedirect)


def workspaces() -> list[str]:
    """Return the names of the workspace folders: the folders that hold a registry."""
    if not WORKSPACES.is_dir():
        return []
    return sorted(path.name for path in WORKSPACES.iterdir() if (path / REGISTRY_NAME).is_file())


def workspace() -> Path:
    """Return the folder of the workspace this repository serves.

    One repository serves one workspace. With several workspace folders the environment variable
    WK_WORKSPACE names the one to use.
    """
    names = workspaces()
    wanted = os.environ.get("WK_WORKSPACE")
    if wanted:
        if wanted not in names:
            known = ", ".join(names) or "none"
            raise cli.Error(f"WK_WORKSPACE is '{wanted}', but the workspaces here are: {known}")
        return WORKSPACES / wanted
    if not names:
        raise cli.Error(NO_WORKSPACE)
    if len(names) > 1:
        raise cli.Error(f"several workspaces ({', '.join(names)}): set WK_WORKSPACE to one")
    return WORKSPACES / names[0]


def registry_path() -> Path:
    """Return the path of the registry of the workspace."""
    return workspace() / REGISTRY_NAME


def inventory() -> Path:
    """Return the folder of the generated recipe index data."""
    return workspace() / "inventory"


def lookup_tables() -> Path:
    """Return the folder of the lookup-table descriptions."""
    return workspace() / "lookup-tables"


def registry() -> Json:
    """Return the registry of the workspace: environments, projects and their settings.

    Only what the scripts rely on for safety is checked here: the file is JSON with environments
    and projects, and every project key is a slug. scripts/check_data.py checks the rest.
    """
    path = registry_path()
    where = path.relative_to(ROOT).as_posix()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise cli.Error(f"{where} is not valid JSON: run scripts/check_data.py") from None
    usable = isinstance(data, dict) and all(
        isinstance(data.get(key), dict) for key in ("environments", "projects")
    )
    if not usable:
        raise cli.Error(f"{where} needs `environments` and `projects`: run scripts/check_data.py")
    for key in data["projects"]:
        if not SLUG.fullmatch(key):
            raise cli.Error(
                f"{where}: the project key '{key}' is not a slug (lower-case words joined by "
                "dashes)"
            )
    checked: Json = data
    return checked


def environments() -> list[str]:
    """Return the names of the two environments every workspace has here: dev and prod."""
    return list(ENVIRONMENTS)


def environment(env: str) -> Json:
    """Return the registry entry of an environment."""
    try:
        entry: Json = registry()["environments"][env]
    except KeyError:
        raise cli.Error(f"unknown environment '{env}'; known: {', '.join(ENVIRONMENTS)}") from None
    return entry


def profile(env: str) -> str:
    """Return the wk profile of an environment; WK_PROFILE_DEV / WK_PROFILE_PROD override it."""
    variable = f"WK_PROFILE_{env.upper()}"
    name = os.environ.get(variable) or environment(env).get("profile")
    if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
        source = variable if os.environ.get(variable) else "the registry"
        raise cli.Error(
            f"{source} holds no usable wk profile for {env}: a profile name is letters, digits, "
            ". _ -"
        )
    return name


def app_url() -> str:
    """Return the address of the Workato web app of the workspace, for links to assets."""
    url: str = registry().get("app_url") or US_APP_HOST
    return url.rstrip("/")


def recipe_url(recipe_id: int | str) -> str:
    """Return the link to a recipe in the Workato web app."""
    return f"{app_url()}/recipes/{recipe_id}"


def company_domains() -> list[str]:
    """Return the e-mail domains of the company, for the lint's hardcoded-address check."""
    domains: list[str] = registry().get("company_domains", [])
    return domains


def snapshot_dir(env: str, slug: str | None = None) -> Path:
    """Return where the recipe JSON of an environment is kept, optionally of one project.

    Prod is in the workspace folder (in git); Dev is in tmp/wk/dev (a personal cache).
    """
    if env not in ENVIRONMENTS:
        raise cli.Error(f"unknown environment '{env}'; known: {', '.join(ENVIRONMENTS)}")
    base = workspace() / "projects" if env == "prod" else DEV_CACHE
    return base / slug if slug else base


def project(slug: str) -> Json:
    """Return the registry entry of a project."""
    try:
        entry: Json = registry()["projects"][slug]
    except KeyError:
        where = registry_path().relative_to(ROOT).as_posix()
        raise cli.Error(f"unknown project '{slug}'; see {where}") from None
    return entry


def snapshot_projects(env: str) -> list[str]:
    """Return the slugs of the projects whose recipe JSON is synced for this environment."""
    return [
        slug
        for slug, entry in registry()["projects"].items()
        if entry.get("snapshots") and env in entry
    ]


def slug(text: str) -> str:
    """Turn a Workato name into a file name: `[SO] REC | New order` -> `so-rec-new-order`.

    Letters and digits of every alphabet are kept, so that two names in another script do not
    become one file. Everything else becomes a dash. A name without a letter or a digit gives
    an empty string: the caller decides what to do with it.
    """
    return re.sub(r"[\W_]+", "-", text.lower()).strip("-")


def executable(name: str) -> str:
    """Return the full path of a command-line tool, or fail with what to install."""
    path = shutil.which(name)
    if path is None:
        hint = "; see docs/setup/workato.md" if name == "wk" else ""
        raise cli.Error(f"{name} is not installed or not on PATH{hint}")
    return path


def run_wk(*args: str) -> str:
    """Run `wk <args>` from the repository root and return its output.

    The root is where `wk` looks for a file store. A failure is an expected error.
    """
    command = [executable("wk"), *args]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        shown = " ".join(args[:5])
        if "token" in args:
            raise cli.Error(f"wk {shown} failed; check `wk auth status` (output withheld)")
        raise cli.Error(f"wk {shown} failed: {short_error(done.stderr or done.stdout)}")
    return done.stdout


def short_error(text: str) -> str:
    """Return what a failed command said, without the body of an HTML error page."""
    text = text.strip()
    page = HTML_PAGE.search(text)
    if page:
        text = f"{text[: page.start()].strip()} (Workato answered with an HTML error page)".strip()
    return text if len(text) <= ERROR_SHOWN else text[:ERROR_SHOWN] + " ..."


def wk(prof: str, *args: str) -> str:
    """Run `wk -p <profile> <args>` and return its output."""
    return run_wk("-p", prof, *store_flags(prof), *args)


def wk_json(prof: str, *args: str) -> Any:
    """Run a wk command with -j and return the parsed answer."""
    try:
        return json.loads(wk(prof, *args, "-j"))
    except ValueError:
        raise cli.Error(f"wk -p {prof} {' '.join(args[:3])} did not answer with JSON") from None


@functools.cache
def profiles() -> list[Json]:
    """Return what `wk auth list` knows of each profile.

    Each entry has a name, a base URL, an environment (dev or prod), the name and the id of its
    workspace, and a store type (keychain or file). The listing holds no token. It is read once
    per run.
    """
    try:
        listed = json.loads(run_wk("auth", "list", "-j"))
    except ValueError:
        raise cli.Error("wk auth list did not answer with JSON") from None
    items = (listed.get("items") or listed.get("profiles")) if isinstance(listed, dict) else listed
    return [item for item in items or [] if isinstance(item, dict)]


def wk_profile(prof: str) -> Json:
    """Return the `wk auth list` entry of one profile."""
    for item in profiles():
        if item.get("name") == prof:
            return item
    raise cli.Error(f"wk has no profile '{prof}'; see `wk auth list` and docs/setup/workato.md")


def store_flags(prof: str) -> list[str]:
    """Return the flags `wk` needs to find the credential of a profile.

    A profile of the file store (profiles.env) is only found with `--store-type file`.
    """
    return ["--store-type", "file"] if wk_profile(prof).get("store_type") == "file" else []


def base_url(prof: str) -> str:
    """Return the base URL `wk` holds for a profile, for example https://www.workato.com.

    Workato has several data centers, each with its own host. The token of a profile is sent to
    this host only: it comes from the person's own sign-in, not from a file of the repository
    that someone else may have changed.
    """
    url = str(wk_profile(prof).get("base_url") or "").rstrip("/")
    if not workato_address(url):
        raise cli.Error(
            f"wk profile '{prof}' has no https base URL on a Workato host; sign in again (the "
            "scripts send a token to Workato only)"
        )
    return url


def workato_address(url: str) -> bool:
    """Tell whether a text is the plain https address of a Workato host and nothing more."""
    try:
        parts = urllib.parse.urlsplit(url)
        extra = parts.username or parts.password or parts.port or parts.query or parts.fragment
    except ValueError:
        return False
    host = parts.hostname or ""
    plain = not extra and parts.path in ("", "/")
    return parts.scheme == "https" and plain and host.endswith(WORKATO_DOMAINS)


def app_host(base: str) -> str:
    """Return the web app address that belongs to a base URL.

    Only the US data center serves its API and its app from two hosts.
    """
    return US_APP_HOST if base.rstrip("/") == US_API_HOST else base.rstrip("/")


def token(prof: str) -> str:
    """Return the API token of a profile. Never print it.

    `wk` must answer with the token alone. An answer with a second line or a space in it (a
    notice printed before the token, for example) is refused without being shown: used as a
    header it would fail inside the HTTP library with an error message that quotes it.
    """
    answer = wk(prof, "auth", "token").strip()
    if not answer or len(answer.split()) != 1:
        raise cli.Error(
            f"wk did not answer with a token alone for profile {prof}; check `wk auth status` "
            "(output withheld)"
        )
    return answer


@dataclass(frozen=True)
class Api:
    """The developer API of one environment: where it is and the token that reads it."""

    url: str
    token: str = field(repr=False)  # kept out of every repr, so out of logs and tracebacks

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one API path, such as /recipes/1/jobs, and return the parsed JSON answer."""
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        headers = {"Authorization": f"Bearer {self.token}"}
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - base_url() gave an https URL
        try:
            with OPENER.open(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            error.close()
            raise cli.Error(f"Workato answered HTTP {error.code} to GET {path}") from None
        except urllib.error.URLError as error:
            raise cli.Error(
                f"Workato could not be reached for GET {path}: {error.reason}"
            ) from None
        except (OSError, ValueError, http.client.HTTPException) as error:
            # The text of such an error can quote the request, its headers included: name its type.
            raise cli.Error(f"GET {path} failed ({type(error).__name__})") from None


def api_url(prof: str) -> str:
    """Return the root of the developer API a profile reaches."""
    return base_url(prof) + "/api"


def api(env: str, prof: str | None = None) -> Api:
    """Return the API of an environment, read with its profile (or with `prof`)."""
    prof = prof or profile(env)
    return Api(api_url(prof), token(prof))


def list_recipes(prof: str, folder: int | str | None = None) -> list[Json]:
    """Return every recipe of the workspace, or of one folder, reading all pages."""
    found: list[Json] = []
    page = 1
    while True:
        args = ["recipes", "list", "--per-page", str(PAGE_SIZE), "--page", str(page)]
        if folder:
            args += ["--folder", str(folder)]
        data = wk_json(prof, *args)
        found += data["items"]
        if not data.get("has_next"):
            return found
        page += 1


def list_connections(prof: str) -> list[Json]:
    """Return every connection of the workspace, reading all pages."""
    found: list[Json] = []
    page = 1
    while True:
        data = wk_json(
            prof, "connections", "list", "--per-page", str(PAGE_SIZE), "--page", str(page)
        )
        found += data.get("items", data) if isinstance(data, dict) else data
        if not (isinstance(data, dict) and data.get("has_next")):
            return found
        page += 1


def list_projects(prof: str) -> list[Json]:
    """Return the projects of an environment: name, project id and root folder id."""
    listed = wk_json(prof, "folders", "list", "--projects")
    items = listed.get("items", listed) if isinstance(listed, dict) else listed
    try:
        return [
            {"name": item["name"], "project_id": item["project_id"], "folder_id": item["id"]}
            for item in items
        ]
    except KeyError, TypeError:
        raise cli.Error(
            f"wk -p {prof} folders list --projects did not answer with name, project_id and id "
            "for each project; is wk up to date?"
        ) from None


def property_values(env: str, project_id: int | str) -> dict[str, str]:
    """Return the properties of a project with their values. Callers must never print a value."""
    values: dict[str, str] = api(env).get("/properties", {"prefix": "", "project_id": project_id})
    return values


def property_names(env: str, project_id: int | str) -> list[str]:
    """Return the names of a project's properties. Values never leave this function."""
    return sorted(property_values(env, project_id))


def walk_folders(prof: str, root_id: int) -> list[tuple[int, list[str]]]:
    """Return every folder of a project as (folder id, names below the root), root first."""
    found: list[tuple[int, list[str]]] = [(root_id, [])]
    queue: list[tuple[int, list[str]]] = [(root_id, [])]
    while queue:
        parent, names = queue.pop(0)
        children = wk_json(prof, "folders", "list", "--parent", str(parent))
        children = children.get("items", children) if isinstance(children, dict) else children
        for child in sorted(children, key=lambda folder: folder["name"]):
            entry = (child["id"], [*names, child["name"]])
            found.append(entry)
            queue.append(entry)
    return found

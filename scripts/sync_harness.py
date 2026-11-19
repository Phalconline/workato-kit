#!/usr/bin/env python3.14
"""Write the files each AI harness reads from their sources in .agents/ and in the workspace.

    scripts/sync_harness.py            write the files
    scripts/sync_harness.py --check    write nothing; exit 1 if a file is out of date

Sources of the kit (edit these):
    .agents/skills/<name>/         procedures as Agent Skills (other harnesses read them here)
    .agents/agents.json            subagent roles; their prompts are in .agents/roles/
    .agents/models.json            default model and effort of each role, per provider
    .agents/mcp.json               the MCP servers; `{app_url}` stands for the workspace's web app.
                                   A server is left out for a workspace whose app address is in
                                   its `unavailable_at` list. An optional server names the
                                   `skills` that need it
    .agents/claude-settings.json   the permissions and hooks of Claude Code

Sources of the workspace, when there is one (workato/workspaces/<workspace>/):
    registry.json                  `app_url`, and the two `wk` profiles that get read permissions
    harness.json                   optional: `mcp_servers` (optional servers to switch on),
                                   `claude_allow` (extra allow rules: the workspace's own
                                   scripts/ws_*.py and tools of a switched-on optional server),
                                   `models` (overrides)

Generated (never edit by hand):
    .claude/settings.json          Claude Code: permissions and hooks
    .claude/skills/<name>/         copy of .agents/skills for Claude Code
    .claude/agents/<name>.md       Claude subagents
    .codex/agents/<name>.toml      Codex subagents
    .mcp.json                      Claude Code (also read by GitHub Copilot)
    .cursor/mcp.json               Cursor
    .codex/config.toml             Codex CLI, IDE extension and ChatGPT desktop
    .gemini/settings.json          Gemini CLI
    .agents/mcp_config.json        Antigravity CLI
    .agents/generated-files.json   the list of the files above, as this run wrote them

A generated file whose source is gone (a removed skill or role) is deleted, but only a file the
list above names: a file a person put into .claude/agents/ or .claude/skills/ is left alone and
named in the output. A skill that needs an optional server is copied for Claude Code only while
that server is switched on. A symbolic link among the sources is refused. No credentials are
written anywhere: every server is a remote HTTP server with per-user sign-in.

.claude/settings.json decides what Claude Code may run without asking, and .mcp.json where a
harness connects. When one of them is rewritten, or with --check when it is out of date, the
script prints what is added (+) and removed (-) compared with the file on disk:

      allow + Bash(scripts/ws_orders.py *)
      deny - Bash(wk push *)
      server + atlassian https://mcp.atlassian.com/v2/mcp

A file that did not exist before gets the number of its rules or servers instead. After a merge
conflict in one of the two files, compare with the last commit instead:
`git diff HEAD -- .claude/settings.json .mcp.json`.

Exit status: 0 done, or with --check everything is up to date; 1 with --check otherwise;
2 when a source is invalid.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
SKILLS_SOURCE = ".agents/skills"
SKILLS_COPY = ".claude/skills"
SETTINGS_SOURCE = ".agents/claude-settings.json"
SETTINGS_FILE = ".claude/settings.json"
MCP_FILE = ".mcp.json"
MANIFEST = ".agents/generated-files.json"
ROLES_SOURCE = ".agents/roles"
PERMISSION_LISTS = ("allow", "deny")
AGENT_FOLDERS = {".claude/agents": ".md", ".codex/agents": ".toml"}
# Names of roles, skills and servers become file names, YAML values and TOML table headers.
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
# What a workspace may add to the shared allow list of Claude Code, and nothing else.
WS_SCRIPT_RULE = re.compile(r"Bash\(scripts/ws_[a-z0-9_]+\.py( \*)?\)")
MCP_TOOL_RULE = re.compile(r"mcp__([a-z0-9][a-z0-9-]*)__[A-Za-z0-9_-]+")
EFFORTS = {
    "claude": {"low", "medium", "high", "xhigh", "max"},
    "codex": {"minimal", "low", "medium", "high", "xhigh"},
}
CACHE_SUFFIXES = {".pyc", ".pyo"}
SKILL_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
APP_URL = "{app_url}"
HARNESS_KEYS = ("mcp_servers", "claude_allow", "models")


@dataclass(frozen=True)
class Workspace:
    """What the generated files take from the workspace of a repository."""

    app_url: str = wkrepo.US_APP_HOST
    profiles: tuple[str, ...] = ()
    mcp_servers: frozenset[str] = frozenset()
    claude_allow: tuple[str, ...] = ()
    models: Json = field(default_factory=dict)


def dump(data: Json) -> str:
    """Serialize a config file the way every generated JSON file is written."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def read_json(root: Path, relative: str) -> Json:
    """Read one of the JSON sources."""
    try:
        data: Json = json.loads((root / relative).read_text(encoding="utf-8"))
    except OSError:
        raise cli.Error(f"{relative} is missing") from None
    except ValueError:
        raise cli.Error(f"{relative} is not valid JSON") from None
    return data


def workspace_folder(root: Path) -> Path | None:
    """Return the workspace folder of a repository, or None when it has none yet."""
    base = root / "workato" / "workspaces"
    names = sorted(
        path.name
        for path in (base.iterdir() if base.is_dir() else [])
        if (path / wkrepo.REGISTRY_NAME).is_file()
    )
    wanted = os.environ.get("WK_WORKSPACE")
    if wanted in names:
        return base / wanted
    if wanted and names:
        raise cli.Error(
            f"WK_WORKSPACE is '{wanted}', but the workspaces here are: {', '.join(names)}"
        )
    if len(names) > 1:
        raise cli.Error(f"several workspaces ({', '.join(names)}): set WK_WORKSPACE to one")
    return base / names[0] if names else None


def workspace(root: Path) -> Workspace:
    """Read what the generated files need from the registry and harness.json of the workspace."""
    folder = workspace_folder(root)
    if folder is None:
        return Workspace()
    relative = folder.relative_to(root).as_posix()
    registry = read_json(root, f"{relative}/{wkrepo.REGISTRY_NAME}")
    harness = (
        read_json(root, f"{relative}/harness.json") if (folder / "harness.json").exists() else {}
    )
    environments = registry.get("environments", {})
    profiles = tuple(
        environments[env].get("profile") for env in wkrepo.ENVIRONMENTS if env in environments
    )
    for profile in profiles:
        if not isinstance(profile, str) or not wkrepo.PROFILE_NAME.fullmatch(profile):
            raise cli.Error(
                f"{relative}/registry.json: a profile name may hold letters, digits, . _ -"
            )
    app_url = registry.get("app_url") or wkrepo.US_APP_HOST
    if not isinstance(app_url, str) or not wkrepo.workato_address(app_url):
        # Every harness is sent to this address to sign in: it must be Workato's own.
        raise cli.Error(
            f"{relative}/registry.json: app_url must be the https address of a Workato web app"
        )
    unknown = sorted(set(harness) - set(HARNESS_KEYS)) if isinstance(harness, dict) else []
    if not isinstance(harness, dict) or unknown:
        raise cli.Error(
            f"{relative}/harness.json: {f'unknown key {unknown[0]}; ' if unknown else ''}"
            f"it is an object with the keys {', '.join(HARNESS_KEYS)}"
        )
    allow = harness.get("claude_allow", [])
    servers = harness.get("mcp_servers", [])
    models = harness.get("models", {})
    lists_ok = all(
        isinstance(items, list) and all(isinstance(item, str) for item in items)
        for items in (allow, servers)
    )
    models_ok = isinstance(models, dict) and all(
        isinstance(roles, dict) and all(isinstance(choice, dict) for choice in roles.values())
        for roles in models.values()
    )
    if not lists_ok or not models_ok:
        raise cli.Error(
            f"{relative}/harness.json: mcp_servers and claude_allow must be lists of text, "
            "models an object of providers, each an object of roles"
        )
    return Workspace(app_url.rstrip("/"), profiles, frozenset(servers), tuple(allow), models)


def mcp_servers(root: Path) -> Json:
    """Return the MCP servers of the kit by name, after checking each name."""
    servers: Json = read_json(root, ".agents/mcp.json")["servers"]
    for name in servers:
        if not NAME.fullmatch(name):
            raise cli.Error(f".agents/mcp.json: the server name '{name}' is not a plain name")
    return servers


def mcp_files(root: Path, space: Workspace) -> dict[str, str]:
    """Return the MCP config of every harness, by path."""
    servers = mcp_servers(root)
    unknown = space.mcp_servers - {name for name, spec in servers.items() if spec.get("optional")}
    if unknown:
        raise cli.Error(
            f"harness.json switches on MCP servers that are not optional ones: {sorted(unknown)}"
        )
    urls = {
        name: spec["url"].replace(APP_URL, space.app_url)
        for name, spec in servers.items()
        if (not spec.get("optional") or name in space.mcp_servers)
        and space.app_url not in spec.get("unavailable_at", [])
    }
    # A JSON string is a valid TOML basic string: a quote in a URL cannot break the file.
    toml = "".join(
        f"[mcp_servers.{name}]\nurl = {json.dumps(url, ensure_ascii=False)}\n\n"
        for name, url in urls.items()
    )
    return {
        ".mcp.json": dump(
            {"mcpServers": {n: {"type": "http", "url": u} for n, u in urls.items()}}
        ),
        ".cursor/mcp.json": dump({"mcpServers": {n: {"url": u} for n, u in urls.items()}}),
        ".agents/mcp_config.json": dump(
            {"mcpServers": {n: {"serverUrl": u} for n, u in urls.items()}}
        ),
        ".gemini/settings.json": dump(
            {"mcpServers": {n: {"httpUrl": u} for n, u in urls.items()}}
        ),
        ".codex/config.toml": toml.rstrip("\n") + "\n",
    }


def settings_file(root: Path, space: Workspace) -> dict[str, str]:
    """Return .claude/settings.json: the kit's permissions and hooks plus the workspace's.

    Each read-only `wk` command of the source is allowed without a profile and with each of the
    registry's two profiles. Nothing here allows a command that changes Workato.
    """
    source = read_json(root, SETTINGS_SOURCE)
    settings: Json = json.loads(json.dumps(source["settings"]))
    commands: list[str] = source.get("wk_read_commands", [])
    # The workspace's rules come first and the kit's last: an update of the kit then changes
    # lines that no workspace has touched, and the merge of this file stays clean.
    allow: list[str] = []
    for profile in space.profiles:
        allow += [f"Bash(wk -p {profile} {command} *)" for command in commands]
    allow += checked_allow(space)
    allow += settings["permissions"]["allow"]
    allow += [f"Bash(wk {command} *)" for command in commands]
    settings["permissions"]["allow"] = list(dict.fromkeys(allow))
    return {SETTINGS_FILE: dump(settings)}


def checked_allow(space: Workspace) -> list[str]:
    """Return the allow rules of harness.json, or refuse one that widens more than it may.

    A workspace may allow its own scripts (scripts/ws_<name>.py) and single tools of an optional
    MCP server it switched on. Anything else, a `wk` command or a tool of the Workato server
    above all, is not for a shared file: a person keeps it in .claude/settings.local.json.
    """
    for rule in space.claude_allow:
        tool = MCP_TOOL_RULE.fullmatch(rule)
        if WS_SCRIPT_RULE.fullmatch(rule) or (tool and tool.group(1) in space.mcp_servers):
            continue
        raise cli.Error(
            f"harness.json: claude_allow accepts `Bash(scripts/ws_<name>.py *)` and "
            f"`mcp__<server>__<tool>` of an optional server that is switched on, not '{rule}'. "
            "Keep any other permission in your own .claude/settings.local.json"
        )
    return list(space.claude_allow)


def permission_rules(content: bytes) -> dict[str, list[str]]:
    """Return the allow and deny rules of a settings file; a file that is not JSON has none."""
    try:
        data = json.loads(content)
    except ValueError:
        data = {}
    permissions = data.get("permissions") if isinstance(data, dict) else None
    if not isinstance(permissions, dict):
        permissions = {}
    return {kind: [str(rule) for rule in permissions.get(kind) or []] for kind in PERMISSION_LISTS}


def permission_changes(before: bytes | None, after: bytes) -> list[str]:
    """Return the permission rules a new .claude/settings.json adds and removes, one per line.

    Args:
        before: The file on disk, or None when there is none yet.
        after: The generated file.

    Returns:
        "  allow + RULE" and "  deny - RULE" lines; for a new file the number of rules instead.
    """
    new = permission_rules(after)
    if before is None:
        return [f"  {kind}: {len(new[kind])} rule(s)" for kind in PERMISSION_LISTS]
    old = permission_rules(before)
    lines = []
    for kind in PERMISSION_LISTS:
        lines += [f"  {kind} + {rule}" for rule in new[kind] if rule not in old[kind]]
        lines += [f"  {kind} - {rule}" for rule in old[kind] if rule not in new[kind]]
    return lines or ["  no permission rule changed"]


def server_urls(content: bytes) -> dict[str, str]:
    """Return the servers of an .mcp.json file by name; a file that is not JSON has none."""
    try:
        servers = json.loads(content)["mcpServers"]
        return {str(name): str(spec.get("url")) for name, spec in servers.items()}
    except ValueError, KeyError, TypeError, AttributeError:
        return {}


def server_changes(before: bytes | None, after: bytes) -> list[str]:
    """Return the MCP servers a new .mcp.json adds and removes, one per line."""
    new = server_urls(after)
    if before is None:
        return [f"  {len(new)} server(s)"]
    old = server_urls(before)
    lines = [f"  server + {name} {url}" for name, url in new.items() if old.get(name) != url]
    lines += [f"  server - {name} {url}" for name, url in old.items() if new.get(name) != url]
    return lines or ["  no server changed"]


def is_cache(relative: Path) -> bool:
    """Tell a local cache file (Python bytecode, Finder metadata) from a skill source."""
    return (
        "__pycache__" in relative.parts
        or relative.suffix in CACHE_SUFFIXES
        or relative.name == ".DS_Store"
    )


def refuse_links(root: Path, folder: str) -> None:
    """Refuse a symbolic link among the sources: it would copy any file into a tracked one."""
    base = root / folder
    for path in [base, *sorted(base.rglob("*"))] if base.exists() else []:
        if path.is_symlink():
            raise cli.Error(
                f"{path.relative_to(root).as_posix()} is a symbolic link; a source must be a file"
            )


def hidden_skills(root: Path, space: Workspace) -> frozenset[str]:
    """Return the skills that need an optional MCP server the workspace has not switched on."""
    return frozenset(
        str(skill)
        for name, spec in mcp_servers(root).items()
        if spec.get("optional") and name not in space.mcp_servers
        for skill in spec.get("skills", [])
    )


def skill_files(root: Path, hidden: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Return the Claude copy of every skill file, by path, after checking each SKILL.md.

    Args:
        root: The repository root.
        hidden: Skills that are not copied: those of an optional server that is switched off.
    """
    source = root / SKILLS_SOURCE
    refuse_links(root, SKILLS_SOURCE)
    for skill in sorted(path for path in source.iterdir() if path.is_dir()):
        if is_cache(skill.relative_to(source)):
            continue
        if not NAME.fullmatch(skill.name):
            raise cli.Error(
                f"{SKILLS_SOURCE}/{skill.name}: a skill folder is named with lower-case letters, "
                "digits and dashes"
            )
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        head = text.split("\n---", 1)[0]
        name = SKILL_NAME.search(head)
        named = name is not None and name.group(1).strip("\"'") == skill.name
        if not text.startswith("---\n") or not named or "description:" not in head:
            raise cli.Error(
                f"{SKILLS_SOURCE}/{skill.name}/SKILL.md: the frontmatter needs "
                "`name` equal to the folder name, and a `description`"
            )
    return {
        f"{SKILLS_COPY}/{path.relative_to(source).as_posix()}": path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file()
        and not is_cache(path.relative_to(source))
        and path.relative_to(source).parts[0] not in hidden
    }


def model_choices(root: Path, space: Workspace, name: str) -> dict[str, Json]:
    """Return the model and effort of a role per provider: the kit's, then the workspace's."""
    defaults = read_json(root, ".agents/models.json")
    choices = {}
    for provider, efforts in EFFORTS.items():
        choice = {
            **defaults.get(provider, {}).get(name, {}),
            **space.models.get(provider, {}).get(name, {}),
        }
        if choice.get("effort") and choice["effort"] not in efforts:
            raise cli.Error(
                f"{provider}/{name}: effort must be one of {', '.join(sorted(efforts))}"
            )
        if not isinstance(choice.get("model") or "", str):
            raise cli.Error(f"{provider}/{name}: model must be text or null")
        choices[provider] = choice
    return choices


def role_prompt(root: Path, name: str, role: Json) -> str:
    """Return the prompt of a role after checking everything that is rendered into a file."""
    relative = PurePosixPath(str(role.get("instructions_file", "")))
    path = root / relative
    in_roles = relative.parent.as_posix() == ROLES_SOURCE and relative.suffix == ".md"
    if not NAME.fullmatch(name) or not in_roles or path.is_symlink() or not path.is_file():
        raise cli.Error(
            f"role {name}: needs a plain name and an instructions_file in {ROLES_SOURCE}/"
        )
    if role.get("color") not in COLORS:
        raise cli.Error(f"role {name}: color must be one of {', '.join(sorted(COLORS))}")
    if not isinstance(role.get("description"), str):
        raise cli.Error(f"role {name}: needs a description")
    for skill in role.get("skills", []):
        known = isinstance(skill, str) and NAME.fullmatch(skill)
        if not known or not (root / SKILLS_SOURCE / skill / "SKILL.md").is_file():
            raise cli.Error(f"role {name}: skill {skill} does not exist")
    return path.read_text(encoding="utf-8").strip()


def agent_files(root: Path, space: Workspace | None = None) -> dict[str, str]:
    """Return every subagent file, by path. A missing model or effort means: use the session's."""
    space = space or Workspace()
    roles = read_json(root, ".agents/agents.json")["roles"]
    rendered = {}
    for name, role in roles.items():
        instructions = role_prompt(root, name, role)
        skills: list[str] = role.get("skills", [])
        choices = model_choices(root, space, name)
        description = json.dumps(role["description"], ensure_ascii=False)
        rendered[f".claude/agents/{name}.md"] = claude_agent(
            name, description, role["color"], skills, choices["claude"], instructions
        )
        rendered[f".codex/agents/{name}.toml"] = codex_agent(
            name, description, skills, choices["codex"], instructions
        )
    return rendered


def claude_agent(
    name: str, description: str, color: str, skills: list[str], choice: Json, instructions: str
) -> str:
    """Render a Claude Code subagent: YAML frontmatter, then the role prompt."""
    head = f"---\nname: {name}\ndescription: {description}\n"
    if choice.get("model"):
        head += f"model: {json.dumps(choice['model'])}\n"
    if choice.get("effort"):
        head += f"effort: {choice['effort']}\n"
    head += f"color: {color}\n"
    if skills:
        head += "skills:\n" + "".join(f"  - {skill}\n" for skill in skills)
    return head + "---\n\n" + instructions + "\n"


def codex_agent(
    name: str, description: str, skills: list[str], choice: Json, instructions: str
) -> str:
    """Render a Codex subagent as TOML."""
    lines = [f"name = {json.dumps(name)}", f"description = {description}"]
    if choice.get("model"):
        lines.append(f"model = {json.dumps(choice['model'])}")
    if choice.get("effort"):
        lines.append(f"model_reasoning_effort = {json.dumps(choice['effort'])}")
    if skills:  # Codex has no skills field: say which ones to load
        loaded = ", ".join(skills)
        instructions = (
            f"Load the task-matched skills from {SKILLS_SOURCE}/: {loaded}.\n\n{instructions}"
        )
    lines.append("developer_instructions = " + json.dumps(instructions, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def generated(root: Path) -> dict[str, bytes]:
    """Return every generated file with its content, by path, the list of them included."""
    space = workspace(root)
    refuse_links(root, ROLES_SOURCE)
    texts = {
        **agent_files(root, space),
        **mcp_files(root, space),
        **settings_file(root, space),
    }
    files = {path: text.encode("utf-8") for path, text in texts.items()}
    files.update(skill_files(root, hidden_skills(root, space)))
    record = {
        "description": (
            "The files scripts/sync_harness.py generated here. It removes only a file that this "
            "list names. Never edit the list by hand."
        ),
        "files": sorted([*files, MANIFEST]),
    }
    files[MANIFEST] = dump(record).encode("utf-8")
    return files


def recorded(root: Path) -> set[str] | None:
    """Return the generated files the last run recorded, or None when there is no record."""
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        return {str(item) for item in data["files"]}
    except OSError, ValueError, KeyError, TypeError:
        return None


def extra_files(root: Path, wanted: dict[str, bytes]) -> list[str]:
    """Return the files in the generated folders that this run does not generate."""
    found = []
    copy = root / SKILLS_COPY
    if copy.exists():
        found += [
            path.relative_to(root).as_posix()
            for path in copy.rglob("*")
            if path.is_file() and not is_cache(path.relative_to(copy))
        ]
    for folder, suffix in AGENT_FOLDERS.items():
        found += [path.relative_to(root).as_posix() for path in (root / folder).glob(f"*{suffix}")]
    return sorted(path for path in found if path not in wanted)


def orphans(root: Path, wanted: dict[str, bytes]) -> list[str]:
    """Return the generated files on disk whose source no longer exists.

    Only a file that the last run recorded as generated counts. A file a person put into one of
    the generated folders is not ours to delete, and neither is anything while no record exists.
    """
    known = recorded(root) or set()
    return [path for path in extra_files(root, wanted) if path in known]


def sync(root: Path = ROOT, *, check: bool = False) -> list[str]:
    """Bring the generated files in line with their sources; return what was out of date."""
    wanted = generated(root)  # every source is validated before the first write
    removed = orphans(root, wanted)  # read from the old record, before it is rewritten
    stale = []
    for relative, content in wanted.items():
        path = root / relative
        if path.is_symlink():
            raise cli.Error(f"{relative} is a symbolic link; remove it and run again")
        if path.exists() and path.read_bytes() == content:
            continue
        stale.append(relative)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    for relative in removed:
        stale.append(f"{relative} (removed)")
        if not check:
            (root / relative).unlink()
    copy = root / SKILLS_COPY
    if not check and copy.exists():
        for folder in sorted((path for path in copy.rglob("*") if path.is_dir()), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
    return stale


def print_permission_changes(before: bytes | None, stale: list[str]) -> None:
    """Print what changes in the permissions of Claude Code, when its settings are out of date."""
    if SETTINGS_FILE not in stale:
        return
    after = settings_file(ROOT, workspace(ROOT))[SETTINGS_FILE].encode("utf-8")
    print(f"Permission rules of {SETTINGS_FILE}:")
    for line in permission_changes(before, after):
        print(line)


def print_server_changes(before: bytes | None, stale: list[str]) -> None:
    """Print which MCP servers change, when the MCP config is out of date."""
    if MCP_FILE not in stale:
        return
    after = mcp_files(ROOT, workspace(ROOT))[MCP_FILE].encode("utf-8")
    print(f"MCP servers of {MCP_FILE}:")
    for line in server_changes(before, after):
        print(line)


def content(relative: str) -> bytes | None:
    """Return a file of the repository as it is on disk, or None when it is not there."""
    path = ROOT / relative
    return path.read_bytes() if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    """Write or check the generated files; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)
    settings, servers = content(SETTINGS_FILE), content(MCP_FILE)
    stale = sync(ROOT, check=args.check)
    if args.check:
        for relative in stale:
            print("out of date:", relative)
    else:
        print(f"{len(stale)} file(s) written." if stale else "Nothing to change.")
        for relative in stale:
            print("  ", relative)
    print_permission_changes(settings, stale)
    print_server_changes(servers, stale)
    known = recorded(ROOT) or set()
    for relative in extra_files(ROOT, generated(ROOT)):
        if relative not in known:
            print(f"left alone, not generated here: {relative}")
    if args.check:
        print("Run scripts/sync_harness.py." if stale else "Harness files are up to date.")
        return cli.EXIT_FINDINGS if stale else cli.EXIT_OK
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

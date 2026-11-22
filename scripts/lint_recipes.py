#!/usr/bin/env python3.14
"""Lint the Dev recipes of the managed projects: `wk lint` plus the house checks.

    scripts/lint_recipes.py                          every managed project
    scripts/lint_recipes.py sales-orders             only this project, managed or Dev-only
    scripts/lint_recipes.py --recipe <id> ...        only these Dev recipes (after a push)
    scripts/lint_recipes.py --no-pull [...]          check the Dev copy already in the cache

Unless --no-pull is given, the Dev copy is refreshed first with `scripts/sync_recipes.py dev`:
one GET per recipe, into tmp/wk/dev/<project>/. Then `wk lint` runs on the recipe files and the
house checks run on the same files. The lint configuration is scripts/wklintrc.json, or the
workspace's own wklintrc.json when its folder has one. The raw lint output is kept in
tmp/wk/lint.json.

What is reported:
- Lint findings that survive triage. Three lint rules misread platform-standard pills, so their
  known false positives are dropped here instead of switching the rule off: DP_LINE_RESOLVES
  (foreach and catch aliases), DP_PATH_RESOLVES (fields every step of that kind outputs) and
  FORMULA_METHOD_INVALID (methods that Workato runs although the linter does not know them).
- PROPERTY_MISSING: a pill on a project property that does not exist. Renaming a property leaves
  the pills of its recipes on the old name, where they read blank.
- MAGIC_LITERAL: a hardcoded value in a step input, outside a variable or config step: a Slack
  channel id, a URL, an e-mail address of the company (the registry names its domains under
  `company_domains`) and whatever the registry adds under `lint_literal_patterns`.
- UNFINISHED_STEP and SKIPPED_STEP.
- UNMASKED_CREDENTIAL: a step without "Mask data" that carries a credential by name (rule
  "Sensitive data stays out of job history" of AGENTS.md): an input field, a request header or
  parameter, a datapill, the output a code step declares or a parameter of a recipe function,
  named like a password, a passcode, a secret, an API key, an Authorization header or an access
  token. Only names are read, never values. A bare "token" is not reported: list actions name
  their paging tokens that way. A warning: a name tells what a field is called, not what it
  holds.
- PROSE_PATTERN: a recipe description, a step comment or a comment line of a code step that
  matches a pattern the registry lists under `lint_prose_patterns`: a word that does not belong
  in the text people read in Workato, for example the name of a system the recipe replaced.
- Only for a project that names the check under `lint_checks` in the registry:
  ACCOUNT_PROPERTY: a pill on a workspace account property instead of a project property;
  NO_GUARD_PROPERTY: a recipe function that takes a parameter whose name matches the project's
  `lint_guard_parameter` (a regular expression, for example for an account id), acts on
  something and never reads the property the project names with `lint_guard_property`: the list
  of records that automation must not touch. Skipped for a stub that only logs and returns, and
  for the functions listed under `lint_guard_exempt`: their only caller runs the guard first.
  JOB_VIEW: the columns of the Jobs tab (docs/conventions/job-view.md). JOB_VIEW_MISSING warns
  when the recipe has no job report; JOB_VIEW_STALE is an error when a column reads a step that
  is not in the recipe, JOB_VIEW_MASKED when it reads a step with data masking, which Workato
  blocks.

Step numbers are Workato UI numbers (the JSON indexes the trigger as 0, so +1).

Exit status: 0 no errors (warnings do not fail the run); 1 at least one error; 2 the Dev copy
could not be refreshed or read, or `wk lint` did not answer.
"""

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
CONFIG = ROOT / "scripts" / "wklintrc.json"
LINT_OUTPUT = ROOT / "tmp" / "wk" / "lint.json"
SHOWN_ERROR_LENGTH = 300

# Fields a step outputs whether or not its extended schema declares them (read from the
# builder's datapill list).
STANDARD_OUTPUTS = {
    "call_recipe": {"job_id", "job_url"},
    "execute": {"context"},
    "make_request_v2": {"status_code", "body", "error", "headers", "response"},
    "make_request": {"status_code", "body", "error", "headers", "response"},
}
# Formula methods the linter's allowlist lacks but Workato runs: `hours` and `days` were seen in
# successful jobs, `minutes` passed the builder's validator. `utc` is still reported: add it here
# once a job that uses it has succeeded.
KNOWN_GOOD_METHODS = {"hours", "minutes", "days"}
STEP_REFERENCE = re.compile(r'references step "([^"]+)"')
UNDECLARED_FIELD = re.compile(r'field "([^"]+)" is not declared in step "([^"]+)"')
METHOD = re.compile(r'method "([^"]+)"')

# Step inputs that legitimately carry ids or text.
SKIP_INPUT_KEYS = {"flow_id", "table_id", "lookup_table_id", "request_name", "label", "hint"}
CONFIG_STEP_NAME = re.compile(r"config|settings", re.IGNORECASE)
type Literals = list[tuple[str, re.Pattern[str]]]
LITERALS: Literals = [
    (
        "Slack channel id",
        re.compile(r"(?<![A-Za-z0-9_])[CG](?=[A-Z0-9]*\d)[A-Z0-9]{8,11}(?![A-Za-z0-9_])"),
    ),
    ("URL", re.compile(r"https?://[A-Za-z0-9.-]+[^\s\"'<>#|]*")),
]
PROPERTY_PILL = re.compile(
    r'pill_type\\*"\s*:\s*\\*"(project_property|account_property)\\*"\s*,\s*'
    r'\\*"property_name\\*"\s*:\s*\\*"([^"\\]+)'
)

# The checks a project switches on with `lint_checks` in the registry.
PROJECT_CHECKS = frozenset(wkrepo.LINT_CHECKS)
# NO_GUARD_PROPERTY: the providers of a step that acts on nothing.
PASSIVE_PROVIDERS = (None, "workato_recipe_function", "logger")
# UNMASKED_CREDENTIAL: field names that mean a credential. A bare "token" is left out, because
# list actions name their paging tokens that way.
CREDENTIAL = re.compile(
    r"password|passcode|passwd|secret|api[_-]?key|private[_-]?key|authorization"
    r"|(?:access|auth|refresh|id|bearer|api|session)[_-]?token",
    re.IGNORECASE,
)
# A name like `requirePassword` or `password_policy` is a setting about a credential, not one.
CREDENTIAL_SETTING = re.compile(
    r"^(?:require|has|is|force|must|need|reset|change|expire|enable|allow)"
    r"|(?:policy|expired|expires|changed|required|reset|length|age|hint|strength)$",
    re.IGNORECASE,
)
# The field names on the path of a datapill, as Workato stores a pill inside a string.
PILL_PATH = re.compile(r'\\*"path\\*"\s*:\s*\[([^\]]*)\]')
PATH_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_ -]*")
# A request header or parameter is a list item: {"header": <name>, "value": ...}.
NAMED_ITEM_KEYS = ("header", "param")
# Inputs that hold a schema a person wrote: the output of a code step, a function's parameters.
DECLARED_SCHEMAS = ("code_output_schema_json", "parameters_schema_json")
SCHEMA_NAME = re.compile(r'"name"\s*:\s*"([^"]+)"')
SHOWN_CREDENTIAL_FIELDS = 3
# JOB_VIEW: the step a job report column reads, in the two datapill forms Workato stores.
JOB_VIEW_PILL = re.compile(r"_\('data\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)")
JOB_VIEW_DP = re.compile(
    r'\\*"provider\\*"\s*:\s*\\*"([^"\\]+)\\*"\s*,\s*\\*"line\\*"\s*:\s*\\*"([^"\\]+)'
)
# PROSE_PATTERN: how a comment line starts in the code of a Ruby, Python or JavaScript step.
CODE_COMMENT = ("#", "//")


@dataclass(frozen=True)
class Settings:
    """What the registry says about linting one project."""

    checks: frozenset[str] = frozenset()  # the per-project checks that are switched on
    guard_property: str = ""  # the property NO_GUARD_PROPERTY looks for
    guard_parameter: str = ""  # a regular expression: the parameter names that need the guard
    guard_exempt: frozenset[str] = frozenset()  # recipe names the guard check skips
    company_domains: tuple[str, ...] = ()  # e-mail domains that count as hardcoded addresses
    extra_literals: tuple[tuple[str, str], ...] = ()  # (label, regular expression) pairs
    prose_patterns: tuple[tuple[str, str], ...] = ()  # the same, for descriptions and comments


class Finding(NamedTuple):
    """One line of the report."""

    level: str  # "error" or "warn"
    rule: str
    step: int | None  # Workato UI step number; None when the finding is about the whole recipe
    message: str


class Target(NamedTuple):
    """One recipe file of the Dev copy."""

    slug: str
    recipe_id: int
    path: Path


def steps(block: Json) -> Iterator[Json]:
    """Yield the trigger and every step nested in it."""
    yield block
    for child in block.get("block") or []:
        yield from steps(child)


def ui_step(block: Json) -> int | None:
    """Return the number the Workato UI shows for a step."""
    number = block.get("number")
    return number + 1 if isinstance(number, int) else None


def step_at(recipe: Json, pointer: str) -> Json | None:
    """Return the deepest step on a JSON pointer such as /code/block/3/input/message."""
    current: Any = recipe
    found = None
    for part in pointer.strip("/").split("/"):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            break
        if isinstance(current, dict) and "keyword" in current:
            found = current
    return found


def strings(value: Any, key: str | None = None) -> Iterator[tuple[str | None, str]]:
    """Yield (key, text) for every string inside a step input, skipping id-carrying keys."""
    if key in SKIP_INPUT_KEYS:
        return
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for name, item in value.items():
            yield from strings(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item, key)


def false_positive(rule: str, message: str, aliases: dict[str, Json]) -> bool:
    """Return True for a lint finding that misreads a platform-standard pill."""
    if rule == "DP_LINE_RESOLVES":
        match = STEP_REFERENCE.search(message)
        return bool(match and match.group(1) in aliases)
    if rule == "DP_PATH_RESOLVES":
        match = UNDECLARED_FIELD.search(message)
        if not match or match.group(2) not in aliases:
            return False
        action = (aliases[match.group(2)].get("name") or "").replace("_async", "")
        return match.group(1) in STANDARD_OUTPUTS.get(action, set())
    if rule == "FORMULA_METHOD_INVALID":
        match = METHOD.search(message)
        return bool(match and match.group(1) in KNOWN_GOOD_METHODS)
    return False


def triage(recipe: Json, diagnostics: list[Json]) -> list[Finding]:
    """Return the `wk lint` findings of a recipe without the known false positives."""
    aliases = {step["as"]: step for step in steps(recipe["code"]) if step.get("as")}
    kept = []
    for diagnostic in diagnostics:
        rule, message = diagnostic["rule_id"], diagnostic["message"]
        if false_positive(rule, message, aliases):
            continue
        step = step_at(recipe, diagnostic.get("source", {}).get("json_pointer", ""))
        kept.append(Finding(diagnostic["level"], rule, ui_step(step) if step else None, message))
    return kept


def property_findings(
    text: str, properties: set[str] | None, checks: frozenset[str]
) -> list[Finding]:
    """Check every property pill of a recipe, given as its JSON text."""
    found = []
    for kind, name in sorted(set(PROPERTY_PILL.findall(text))):
        if kind == "account_property":
            if "ACCOUNT_PROPERTY" in checks:
                message = (
                    f'account property "{name}" is a workspace setting, not a project property'
                )
                found.append(Finding("warn", "ACCOUNT_PROPERTY", None, message))
        elif properties is not None and name not in properties:
            message = f'project property "{name}" does not exist'
            found.append(Finding("error", "PROPERTY_MISSING", None, message))
    return found


def holds_configuration(step: Json) -> bool:
    """Return True for a step whose job is to hold literals: a variable or a config step."""
    if step.get("provider") == "workato_variable":
        return True
    name = str((step.get("input") or {}).get("name", ""))
    return step.get("provider") == "workato_custom_code" and bool(CONFIG_STEP_NAME.search(name))


def literal_patterns(settings: Settings) -> Literals:
    """Return the patterns of hardcoded values: the built-in ones and the workspace's own."""
    patterns = list(LITERALS)
    if settings.company_domains:  # an empty list would otherwise match every address
        domains = "|".join(re.escape(domain) for domain in settings.company_domains)
        address = re.compile(rf"[A-Za-z0-9._%+-]+@(?:{domains})\b", re.IGNORECASE)
        patterns.append(("company e-mail", address))
    for label, expression in settings.extra_literals:
        try:
            patterns.append((label, re.compile(expression)))
        except re.error:
            raise cli.Error(
                f"lint_literal_patterns in the registry: '{label}' is not a regular expression"
            ) from None
    return patterns


def magic_literals(step: Json, patterns: Literals) -> list[str]:
    """Return one message per hardcoded id, URL or company address in the input of a step."""
    messages: dict[tuple[str, str], str] = {}
    for key, value in strings(step.get("input") or {}):
        for label, pattern in patterns:
            for hit in pattern.findall(value):
                messages.setdefault((label, hit), f"{label} {hit!r} in input {key!r}")
    return list(messages.values())


def step_findings(code: Json, patterns: Literals) -> list[Finding]:
    """Check each step: unfinished, skipped, hardcoded literals."""
    found = []
    for step in steps(code):
        number = ui_step(step)
        if step.get("unfinished") is True:
            found.append(Finding("error", "UNFINISHED_STEP", number, "step is marked unfinished"))
        if step.get("skip") is True:
            found.append(Finding("warn", "SKIPPED_STEP", number, "step is skipped"))
        if not holds_configuration(step):
            found += [
                Finding("warn", "MAGIC_LITERAL", number, message)
                for message in magic_literals(step, patterns)
            ]
    return found


def credential_fields(step: Json) -> list[str]:
    """Return the names under which a step carries or declares a credential.

    Read from the input of the step: a field, a request header or parameter with a value, the
    path of a datapill, and the schema a person wrote for a code step's output or a function's
    parameters. Values are never read.
    """
    found: set[str] = set()

    def credential(name: str) -> bool:
        return bool(CREDENTIAL.search(name)) and not CREDENTIAL_SETTING.search(name.strip())

    def visit(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            named = [value[name] for name in NAMED_ITEM_KEYS if isinstance(value.get(name), str)]
            if named and credential(named[0]) and str(value.get("value") or "").strip():
                found.add(named[0])
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, str) and value.strip():
            if key and key not in DECLARED_SCHEMAS and credential(key):
                found.add(key)
            for path in PILL_PATH.findall(value):
                found.update(part for part in PATH_SEGMENT.findall(path) if credential(part))

    step_input = step.get("input")
    if not isinstance(step_input, dict):
        return []
    visit(step_input)
    for schema in DECLARED_SCHEMAS:
        names = SCHEMA_NAME.findall(str(step_input.get(schema) or ""))
        found.update(name for name in names if credential(name))
    return sorted(found)


def unmasked_credentials(code: Json) -> list[Finding]:
    """Report every step that carries a credential by name and has no data masking."""
    found = []
    for step in steps(code):
        fields = [] if step.get("mask_data") is True else credential_fields(step)
        if fields:
            shown = ", ".join(repr(field) for field in fields[:SHOWN_CREDENTIAL_FIELDS])
            message = f"carries {shown} and is not masked"
            found.append(Finding("warn", "UNMASKED_CREDENTIAL", ui_step(step), message))
    return found


def guard_property_check(recipe: Json, text: str, settings: Settings) -> list[Finding]:
    """Check that a recipe function which takes a guarded parameter reads the guard property.

    The guard property lists the records automation must not touch. A function whose only
    caller runs the guard first is exempt by name.
    """
    trigger = recipe["code"]
    if trigger.get("provider") != "workato_recipe_function" or trigger.get("name") != "execute":
        return []
    try:
        parameters = json.loads((trigger.get("input") or {}).get("parameters_schema_json") or "[]")
    except ValueError:
        parameters = []
    names = [str(item.get("name", "")) for item in parameters if isinstance(item, dict)]
    guarded = [name for name in names if re.search(settings.guard_parameter, name)]
    # A stub that only logs and returns acts on nothing, so it needs no guard yet.
    acts = any(step.get("provider") not in PASSIVE_PROVIDERS for step in steps(trigger))
    guarded_by_caller = recipe.get("name", "") in settings.guard_exempt
    if guarded and acts and not guarded_by_caller and settings.guard_property not in text:
        message = f"takes '{guarded[0]}' but never reads {settings.guard_property}"
        return [Finding("warn", "NO_GUARD_PROPERTY", None, message)]
    return []


def job_view_findings(code: Json) -> list[Finding]:
    """Check the job report: there is one, and every column reads a step that exists unmasked."""
    config = code.get("job_report_config") or {}
    if not config:
        message = "no job report: the Jobs tab shows no columns of its own for this recipe"
        return [Finding("warn", "JOB_VIEW_MISSING", None, message)]
    blocks = {block.get("as"): block for block in steps(code)}
    labels = {item.get("name"): item.get("label") for item in code.get("job_report_schema") or []}
    found = []
    for column, value in sorted(config.items()):
        label = labels.get(column) or column
        text = str(value)
        read = {
            line for _provider, line in JOB_VIEW_PILL.findall(text) + JOB_VIEW_DP.findall(text)
        }
        for line in sorted(read):
            block = blocks.get(line)
            if block is None:
                message = f"column {label!r} reads step {line!r}, which is not in the recipe"
                found.append(Finding("error", "JOB_VIEW_STALE", None, message))
            elif block.get("mask_data") is True:
                message = f"column {label!r} reads a step with data masking, which Workato blocks"
                found.append(Finding("error", "JOB_VIEW_MASKED", ui_step(block), message))
    return found


def prose_patterns(settings: Settings) -> Literals:
    """Return the patterns that a description or a comment must not match."""
    patterns = []
    for label, expression in settings.prose_patterns:
        try:
            patterns.append((label, re.compile(expression, re.IGNORECASE)))
        except re.error:
            raise cli.Error(
                f"lint_prose_patterns in the registry: '{label}' is not a regular expression"
            ) from None
    return patterns


def prose_findings(recipe: Json, patterns: Literals) -> list[Finding]:
    """Report a description, a step comment or a code comment that matches a prose pattern."""
    if not patterns:
        return []
    found = []

    def check(text: object, where: str, number: int | None) -> None:
        for label, pattern in patterns:
            if pattern.search(str(text or "")):
                found.append(Finding("warn", "PROSE_PATTERN", number, f"{where} holds {label}"))

    check(recipe.get("description"), "the description", None)
    for step in steps(recipe["code"]):
        number = ui_step(step)
        check(step.get("comment"), "the step comment", number)
        code = (step.get("input") or {}).get("code")
        if isinstance(code, str):
            lines = [line for line in code.splitlines() if line.strip().startswith(CODE_COMMENT)]
            check("\n".join(lines), "a comment in the code", number)
    return found


def house_checks(
    recipe: Json, properties: set[str] | None, settings: Settings | None = None
) -> list[Finding]:
    """Run the house checks on one recipe.

    Args:
        recipe: The recipe document as `wk recipes pull` wrote it.
        properties: The names of the project's properties; None skips PROPERTY_MISSING.
        settings: What the registry says about linting the recipe's project.
    """
    settings = settings or Settings()
    text = json.dumps(recipe)
    found = property_findings(text, properties, settings.checks)
    found += step_findings(recipe["code"], literal_patterns(settings))
    found += unmasked_credentials(recipe["code"])
    found += prose_findings(recipe, prose_patterns(settings))
    if "NO_GUARD_PROPERTY" in settings.checks:
        found += guard_property_check(recipe, text, settings)
    if "JOB_VIEW" in settings.checks:
        found += job_view_findings(recipe["code"])
    return found


def project_settings(slug: str) -> Settings:
    """Return the lint settings of a project from the registry."""
    project = wkrepo.project(slug)
    checks = frozenset(project.get("lint_checks", []))
    if checks - PROJECT_CHECKS:
        unknown = sorted(checks - PROJECT_CHECKS)
        raise cli.Error(f"{slug}: unknown lint_checks in the registry: {unknown}")
    guard_property = project.get("lint_guard_property", "")
    guard_parameter = project.get("lint_guard_parameter", "")
    if "NO_GUARD_PROPERTY" in checks and not (guard_property and guard_parameter):
        raise cli.Error(
            f"{slug}: the check NO_GUARD_PROPERTY needs lint_guard_property and "
            "lint_guard_parameter"
        )
    try:
        re.compile(guard_parameter)
    except re.error:
        raise cli.Error(f"{slug}: lint_guard_parameter is not a regular expression") from None
    return Settings(
        checks=checks,
        guard_property=guard_property,
        guard_parameter=guard_parameter,
        guard_exempt=frozenset(project.get("lint_guard_exempt", [])),
        company_domains=tuple(wkrepo.company_domains()),
        extra_literals=tuple(wkrepo.registry().get("lint_literal_patterns", {}).items()),
        prose_patterns=tuple(wkrepo.registry().get("lint_prose_patterns", {}).items()),
    )


def lint_config() -> Path:
    """Return the configuration `wk lint` runs with: the workspace's own, else the kit's."""
    own = wkrepo.workspace() / CONFIG.name
    return own if own.is_file() else CONFIG


def dev_index(slug: str) -> Json | None:
    """Return index.json of the Dev copy of a project; None when there is no copy yet."""
    path = wkrepo.snapshot_dir("dev", slug) / "index.json"
    if not path.exists():
        return None
    index: Json = json.loads(path.read_text(encoding="utf-8"))
    return index


def narrowed(slugs: list[str], only: set[int]) -> list[str]:
    """Return only the projects whose Dev copy already lists the wanted recipes.

    This saves reading every project from Workato when the recipes are known. When one of them
    is in no local copy yet, all projects are kept and the sync looks for it.
    """
    owners: dict[int, str] = {}
    for slug in slugs:
        for recipe in (dev_index(slug) or {}).get("recipes", []):
            owners[recipe["id"]] = slug
    if not only or not only <= set(owners):
        return slugs
    wanted = {owners[recipe_id] for recipe_id in only}
    return [slug for slug in slugs if slug in wanted]


def pull(slugs: list[str], only: set[int]) -> None:
    """Refresh the Dev copy with scripts/sync_recipes.py: one GET per recipe."""
    command = [sys.executable, "-I", "-B", str(ROOT / "scripts" / "sync_recipes.py"), "dev"]
    command += slugs
    if only:
        command += ["--recipe", *(str(recipe_id) for recipe_id in sorted(only))]
    if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:
        raise cli.Error("the Dev copy could not be refreshed; see the message above")


def targets(slugs: list[str], only: set[int]) -> list[Target]:
    """Return the recipe files to check, from the index of each project's Dev copy."""
    found = []
    for slug in slugs:
        index = dev_index(slug)
        if index is None:
            if only:
                continue  # the wanted recipes are in another project
            raise cli.Error(f"no Dev copy of {slug} in tmp/wk/dev: run without --no-pull first")
        base = wkrepo.snapshot_dir("dev", slug)
        found += [
            Target(slug, recipe["id"], base / recipe["file"])
            for recipe in index["recipes"]
            if not only or recipe["id"] in only
        ]
    missing = only - {target.recipe_id for target in found}
    if missing:
        raise cli.Error(f"not in the Dev copy of the selected projects: {sorted(missing)}")
    if not found:
        raise cli.Error("no recipe files to check")
    return found


def run_lint(paths: list[Path]) -> dict[int, list[Json]]:
    """Run `wk lint` on the files and return its diagnostics by recipe id."""
    command = [wkrepo.executable("wk"), "lint", *(str(path) for path in paths)]
    command += ["--json", "--config-path", str(lint_config())]
    # wk lint exits 1 when it finds anything; the triage decides what counts.
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        files = json.loads(done.stdout).get("files", [])
    except ValueError, AttributeError:
        detail = (done.stderr.strip() or done.stdout.strip())[:SHOWN_ERROR_LENGTH]
        raise cli.Error(
            f"wk lint returned no result (is the recipe-lint plugin registered?): {detail}"
        ) from None
    LINT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LINT_OUTPUT.write_text(done.stdout, encoding="utf-8")
    diagnostics: dict[int, list[Json]] = {}
    for file in files:
        leading_id = re.match(r"\d+", Path(file["file"]).name)
        if leading_id:
            diagnostics[int(leading_id.group(0))] = file["diagnostics"]
    return diagnostics


def check_project(slug: str, selected: list[Target], diagnostics: dict[int, list[Json]]) -> int:
    """Check the recipes of one project, print what was found and return the number of errors."""
    properties = (dev_index(slug) or {}).get("properties")
    settings = project_settings(slug)
    results = []
    for target in selected:
        recipe = json.loads(target.path.read_text(encoding="utf-8"))
        found = triage(recipe, diagnostics.get(target.recipe_id, []))
        names = None if properties is None else set(properties)
        found += house_checks(recipe, names, settings)
        results.append((recipe.get("name", ""), target.recipe_id, found))

    errors = sum(finding.level == "error" for _, _, found in results for finding in found)
    warnings = sum(finding.level == "warn" for _, _, found in results for finding in found)
    print(f"\n== {slug}: {len(results)} recipes, {errors} errors, {warnings} warnings")
    for name, recipe_id, found in sorted(results):
        if not found:
            continue
        print(f"\n{name}  {wkrepo.recipe_url(recipe_id)}")
        width = max(len(finding.rule) for finding in found)
        for finding in sorted(found, key=lambda f: (f.level != "error", f.step or 0, f.rule)):
            where = f"step {finding.step}" if finding.step else "recipe"
            print(
                f"  {finding.level.upper():5} {finding.rule:{width}} {where:9} {finding.message}"
            )
    if properties is None:
        print(f"Property check SKIPPED for {slug}: its index.json lists no property names.")
    return errors


def main(argv: list[str] | None = None) -> int:
    """Refresh the Dev copy, lint it and print the findings; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "projects",
        nargs="*",
        metavar="project",
        help="project slugs (default: every managed project)",
    )
    parser.add_argument(
        "--recipe", nargs="+", type=int, default=[], metavar="ID", help="only these Dev recipes"
    )
    parser.add_argument(
        "--no-pull", action="store_true", help="check the Dev copy that is already in tmp/wk/dev"
    )
    args = parser.parse_args(argv)

    slugs = args.projects or wkrepo.snapshot_projects("dev")
    for slug in slugs:
        wkrepo.project(slug)  # an unknown project fails here, before anything is read
    only = set(args.recipe)
    if not args.no_pull:
        pull(narrowed(slugs, only), only)
    selected = targets(slugs, only)
    diagnostics = run_lint([target.path for target in selected])

    errors = 0
    for slug in slugs:
        of_project = [target for target in selected if target.slug == slug]
        if of_project:
            errors += check_project(slug, of_project, diagnostics)
    print(f"\n{len(selected)} recipes checked: {errors} errors.")
    return cli.EXIT_FINDINGS if errors else cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

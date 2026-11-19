#!/usr/bin/env python3.14
"""Collect every job of the Prod environment for a time window. Read-only towards Workato.

    scripts/prod_jobs_report.py --since 2030-01-31T08:00:00Z [--until ISO] [--out FILE]

Reads with the Prod `wk` profile of the registry (another one with --profile): the recipe list,
then for each recipe its jobs in the window, the failing step of each failed job, and the audit
log (starts, stops, edits, connection changes). Only GET requests. E-mail addresses in titles and
errors are replaced with <user>. The result is one JSON file, by default in tmp/wk/prod-jobs/.

A recipe whose jobs could not be read is listed under "errors" in the report; the run goes on.

Exit status: 0 done, 2 when Workato could not be read at all or a time is not ISO 8601.
"""

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cli, wkrepo
from lib.wkrepo import Json

ROOT = wkrepo.ROOT
OUT_DIR = ROOT / "tmp" / "wk" / "prod-jobs"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
AUDIT_EVENTS = {
    "recipe_started", "recipe_stopped", "recipe_updated", "recipe_created", "recipe_deleted",
    "connection_connected", "connection_disconnected", "connection_updated",
}  # fmt: skip
AUDIT_TIME = "%Y-%m-%dT%H:%M:%SZ"
# A read that failed, or an answer of an unexpected shape: listed in the report, never fatal.
READ_ERRORS = (cli.Error, OSError, ValueError, KeyError, TypeError, AttributeError)


def redact(value: Any) -> Any:
    """Return the value with every e-mail address replaced by <user>."""
    if isinstance(value, str):
        return EMAIL.sub("<user>", value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def parse_time(text: str) -> datetime:
    """Parse an ISO 8601 time into UTC."""
    cleaned = text.strip().replace(" UTC", "+00:00")
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned).astimezone(UTC)
    except ValueError:
        raise cli.Error(
            f"'{text}' is not an ISO 8601 time, for example 2030-01-31T08:00:00Z"
        ) from None


def jobs_in_window(
    api: wkrepo.Api, recipe_id: int, since: datetime, until: datetime
) -> list[Json]:
    """Return the jobs of a recipe inside the window; jobs come newest first, page by page."""
    found: list[Json] = []
    offset = None
    while True:
        params = {"offset_job_id": offset} if offset else None
        items = api.get(f"/recipes/{recipe_id}/jobs", params).get("items", [])
        if not items:
            return found
        for job in items:
            started = parse_time(job["started_at"]) if job.get("started_at") else None
            if started and started < since:
                return found
            if started is None or started <= until:
                found.append(job)
        if offset == items[-1]["id"]:
            return found
        offset = items[-1]["id"]


def failing_lines(api: wkrepo.Api, recipe_id: int, job_id: str) -> list[Json]:
    """Return the steps of a job that ended in an error."""
    detail = api.get(f"/recipes/{recipe_id}/jobs/{job_id}")
    return [
        {
            "ui_step": (line.get("recipe_line_number") or 0) + 1,
            "adapter": line.get("adapter_name"),
            "operation": line.get("adapter_operation"),
            "error": line.get("error"),
        }
        for line in detail.get("lines") or []
        if line.get("error")
    ]


def audit_log(api: wkrepo.Api, since: datetime, until: datetime) -> list[Json]:
    """Return the starts, stops, edits and connection changes of the window."""
    events: list[Json] = []
    after = None
    while True:
        params: Json = {
            "from": since.strftime(AUDIT_TIME),
            "to": until.strftime(AUDIT_TIME),
            "page[size]": wkrepo.PAGE_SIZE,
        }
        if after:
            params["page[after]"] = after
        data = api.get("/activity_logs", params).get("data", [])
        for event in data:
            if event.get("event_type") not in AUDIT_EVENTS:
                continue
            resource = event.get("resource") or {}
            details = event.get("details") or {}
            events.append(
                {
                    "time": event.get("timestamp"),
                    "event": event.get("event_type"),
                    "user": (event.get("user") or {}).get("name"),
                    "resource_type": resource.get("type"),
                    "resource_id": resource.get("id"),
                    "resource_name": resource.get("name"),
                    "stop_reason": details.get("stop_reason"),
                    "error": details.get("error"),
                }
            )
        if len(data) < wkrepo.PAGE_SIZE:
            return events
        after = data[-1]["id"]


def job_entry(api: wkrepo.Api, recipe_id: int, job: Json, errors: list[Json]) -> Json:
    """Return the report entry of one job, with its failing steps when it failed."""
    item: Json = {
        "id": job["id"],
        "status": job.get("status"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "title": job.get("title"),
        "is_poll_error": job.get("is_poll_error"),
        "is_repeat": job.get("is_repeat"),
        "calling_recipe_id": job.get("calling_recipe_id"),
        "root_recipe_id": job.get("root_recipe_id"),
        "error": job.get("error"),
        "url": f"{wkrepo.recipe_url(recipe_id)}/job/{job['id']}",
    }
    if job.get("status") == "failed" or job.get("is_error"):
        try:
            item["failing_lines"] = failing_lines(api, recipe_id, job["id"])
        except READ_ERRORS as error:
            errors.append(
                {
                    "recipe_id": recipe_id,
                    "job_id": job["id"],
                    "stage": "job detail",
                    "error": str(error),
                }
            )
    return item


def recipe_entry(
    api: wkrepo.Api, recipe: Json, since: datetime, until: datetime, errors: list[Json]
) -> Json:
    """Return the report entry of one recipe with its jobs of the window."""
    recipe_id = recipe["id"]
    try:
        jobs = jobs_in_window(api, recipe_id, since, until)
    except READ_ERRORS as error:  # keep going: the report lists what could not be read
        errors.append({"recipe_id": recipe_id, "stage": "jobs", "error": str(error)})
        jobs = []
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status"))
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = len(jobs)
    return {
        "id": recipe_id,
        "name": recipe["name"],
        "folder_id": recipe.get("folder_id"),
        "running": recipe.get("running"),
        "url": wkrepo.recipe_url(recipe_id),
        "counts": counts,
        "jobs": [job_entry(api, recipe_id, job, errors) for job in jobs],
        "last_job_at": jobs[0].get("started_at") if jobs else None,
    }


def main(argv: list[str] | None = None) -> int:
    """Collect the window into one JSON file; return the exit status."""
    parser = cli.parser(__doc__)
    parser.add_argument(
        "--since", help="window start, ISO 8601 (default: 24 hours before --until)"
    )
    parser.add_argument("--until", help="window end, ISO 8601 (default: now)")
    parser.add_argument("--profile", help="wk profile (default: the Prod profile of the registry)")
    parser.add_argument("--out", type=Path, help="output JSON file, under tmp/")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    until = parse_time(args.until) if args.until else now
    since = parse_time(args.since) if args.since else until - timedelta(hours=24)
    out: Path = args.out or OUT_DIR / f"jobs-{until:%Y%m%dT%H%M%SZ}.json"
    if not out.resolve().is_relative_to((ROOT / "tmp").resolve()):
        # The command is allowed without asking, so it must not be able to overwrite any file.
        raise cli.Error("--out must be a file under tmp/: a report holds job data")
    profile = args.profile or wkrepo.profile("prod")
    api = wkrepo.api("prod", profile)

    errors: list[Json] = []
    recipes = sorted(wkrepo.list_recipes(profile), key=lambda recipe: recipe["name"])
    report: Json = {
        "profile": profile,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "collected_at": now.isoformat(),
        "recipes": [recipe_entry(api, recipe, since, until, errors) for recipe in recipes],
        "errors": errors,
    }
    try:
        report["audit"] = audit_log(api, since, until)
    except READ_ERRORS as error:
        errors.append({"stage": "audit log", "error": str(error)})
        report["audit"] = []

    report = redact(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(recipe["counts"]["total"] for recipe in report["recipes"])
    failed = sum(recipe["counts"].get("failed", 0) for recipe in report["recipes"])
    shown = out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out
    print(
        f"{len(report['recipes'])} recipes, {total} jobs, {failed} failed, "
        f"{len(report['audit'])} audit events, {len(errors)} read errors -> {shown}"
    )
    return cli.EXIT_OK


if __name__ == "__main__":
    cli.run(main)

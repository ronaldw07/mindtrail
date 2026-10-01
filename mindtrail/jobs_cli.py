"""`mindtrail jobs ...` commands, registered onto cli.py's parser."""

from __future__ import annotations

from mindtrail.ingest.job_posting import add_from_link
from mindtrail.integrations.google_sheets import SheetsClient
from mindtrail.llm import LLMClient
from mindtrail.organize.app_state import AppState
from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore
from mindtrail.web.jobs_api import handle_import_sheet


def cmd_jobs_add(args) -> int:
    initialize()
    app, warning = add_from_link(JobStore(), LLMClient(), args.url,
                                 stage="saved" if args.saved else "applied")
    role = f" - {app.role}" if app.role else ""
    print(f"{app.stage}: {app.company}{role}" + (f" (deadline {app.deadline})" if app.deadline else ""))
    if warning:
        print(f"note: {warning}")
    return 0


def cmd_jobs_list(args) -> int:
    initialize()
    apps = JobStore().all()
    if not apps:
        print("no applications yet - try: mindtrail jobs add <link>")
        return 0
    for app in apps:
        role = f" - {app.role}" if app.role else ""
        print(f"  {app.stage:<10} {app.company}{role}")
    return 0


def cmd_jobs_sheet(args) -> int:
    initialize()
    result = handle_import_sheet(
        JobStore(), AppState(), LLMClient(), SheetsClient(),
        {"link": getattr(args, "link", ""), "dry_run": getattr(args, "dry_run", False)},
    )
    if "error" in result:
        print(f"error: {result['error']}")
        return 1
    s = result["summary"]
    verb = "imported" if result["applied"] else "would import"
    print(f"{verb} {s['new']} new, filled gaps in {s['filled']}, "
          f"{s['unchanged']} already up to date, {s['skipped_rows']} rows skipped")
    for row in s["preview"]:
        print(f"  + {row['stage']:<10} {row['company']}" + (f" - {row['role']}" if row["role"] else ""))
    return 0


def register(sub) -> None:
    jobs = sub.add_parser("jobs", help="track job applications")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)

    add = jobs_sub.add_parser("add", help="add an application from a posting link")
    add.add_argument("url")
    add.add_argument("--saved", action="store_true", help="not applied yet, just saving it")
    add.set_defaults(func=cmd_jobs_add)

    list_cmd = jobs_sub.add_parser("list", help="list applications")
    list_cmd.set_defaults(func=cmd_jobs_list)

    sheet = jobs_sub.add_parser("import-sheet", help="import from a Google Sheet link")
    sheet.add_argument("link")
    sheet.add_argument("--dry-run", action="store_true", help="show what would change")
    sheet.set_defaults(func=cmd_jobs_sheet)

    sync = jobs_sub.add_parser("sync-sheet", help="re-import new rows from the linked sheet")
    sync.set_defaults(func=cmd_jobs_sheet)

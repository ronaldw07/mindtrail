"""`mindtrail jobs ...` commands, registered onto cli.py's parser."""

from __future__ import annotations

from mindtrail.ingest.job_posting import add_from_link
from mindtrail.llm import LLMClient
from mindtrail.organize.db import initialize
from mindtrail.organize.jobs import JobStore


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


def register(sub) -> None:
    jobs = sub.add_parser("jobs", help="track job applications")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)

    add = jobs_sub.add_parser("add", help="add an application from a posting link")
    add.add_argument("url")
    add.add_argument("--saved", action="store_true", help="not applied yet, just saving it")
    add.set_defaults(func=cmd_jobs_add)

    list_cmd = jobs_sub.add_parser("list", help="list applications")
    list_cmd.set_defaults(func=cmd_jobs_list)

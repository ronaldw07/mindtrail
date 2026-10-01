"""Import job applications from spreadsheet rows (a linked Google Sheet).

Column headers are matched by keyword in code; the model is asked only
when that can't find the company column, and its answer is cached per
header row. Rows are always parsed in code - never one model call per row.

Importing is add-only. A row matching an existing application (same
company, same role) only fills that application's *empty* fields, so
re-syncing the sheet can never undo an edit made in Mind Trail.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime

from mindtrail.advice.json_reply import extract_json_object
from mindtrail.organize.jobs import Application, JobStore, normalize_company

FIELDS = ("company", "role", "url", "location", "stage", "applied_at", "deadline", "notes")
FILLABLE = ("role", "url", "location", "applied_at", "deadline", "notes")

# First match wins, so more specific phrases come before general ones.
HEADER_KEYWORDS = (
    ("applied_at", ("date applied", "applied on", "application date", "applied date",
                    "date submitted", "submitted")),
    ("deadline", ("deadline", "due", "closes", "close date")),
    ("company", ("company", "employer", "organization", "organisation", "firm")),
    # Before role, so "Job Link" is a link and not a job title.
    ("url", ("link", "url", "website")),
    ("role", ("role", "position", "title", "job")),
    ("location", ("location", "city", "office")),
    ("stage", ("status", "stage", "progress", "result")),
    ("notes", ("notes", "note", "comments", "comment")),
)

# Checked in order: a "rejected after interview" status is a rejection.
STAGE_KEYWORDS = (
    ("withdrawn", ("withdr",)),
    ("rejected", ("reject", "declin", "no offer", "denied", "not selected", "unsuccessful")),
    ("offer", ("offer",)),
    ("interview", ("interview", "screen", "onsite", "on-site", "superday", "final round")),
    ("oa", ("oa", "assessment", "hackerrank", "codesignal", "coding test", "challenge")),
    ("saved", ("not applied", "wishlist", "saved", "to apply", "interested", "planning")),
    ("applied", ("applied", "submitted", "pending", "waiting", "ghost", "no response")),
)

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y",
                "%b %d %Y", "%B %d %Y", "%d %b %Y", "%m-%d-%Y")
SHORT_DATE_FORMATS = ("%m/%d", "%b %d", "%B %d")

MAPPING_SYSTEM_PROMPT = (
    "You map spreadsheet column headers to fields of a job application "
    "tracker. Fields: company, role, url, location, stage, applied_at, "
    "deadline, notes. Respond with JSON only, mapping each field to the "
    'exact header text or to null: {"company": "Header", "role": null, ...}. '
    "Use a header at most once."
)


def heuristic_mapping(header: list[str]) -> dict[str, int]:
    """field -> column index, by keyword. Columns are claimed once."""
    mapping: dict[str, int] = {}
    claimed: set[int] = set()
    for fld, keywords in HEADER_KEYWORDS:
        for i, raw in enumerate(header):
            text = raw.strip().lower()
            if i in claimed or not text:
                continue
            if any(k in text for k in keywords):
                mapping[fld] = i
                claimed.add(i)
                break
    return mapping


def model_mapping(llm, header: list[str], samples: list[list[str]]) -> dict[str, int]:
    preview = "\n".join(" | ".join(r) for r in samples[:3])
    reply = llm.complete(
        MAPPING_SYSTEM_PROMPT,
        f"HEADERS: {header}\nSAMPLE ROWS:\n{preview}",
        max_tokens=200,
    )
    data = extract_json_object(reply.text)
    index = {h.strip(): i for i, h in enumerate(header)}
    mapping: dict[str, int] = {}
    for fld in FIELDS:
        name = data.get(fld)
        if isinstance(name, str) and name.strip() in index:
            col = index[name.strip()]
            if col not in mapping.values():
                mapping[fld] = col
    return mapping


def header_key(header: list[str]) -> str:
    return hashlib.sha1("\x1f".join(h.strip().lower() for h in header).encode()).hexdigest()


def resolve_mapping(header: list[str], samples: list[list[str]], llm, cache: dict) -> dict[str, int]:
    """Keyword mapping, else the cached or freshly asked model mapping.
    `cache` (header_key -> mapping) is updated in place."""
    mapping = heuristic_mapping(header)
    if "company" in mapping:
        return mapping
    key = header_key(header)
    if key in cache:
        return {k: int(v) for k, v in cache[key].items()}
    if llm is None:
        raise ValueError("couldn't find a company column in that sheet")
    mapping = model_mapping(llm, header, samples)
    if "company" not in mapping:
        raise ValueError("couldn't find a company column in that sheet")
    cache[key] = mapping
    return mapping


def parse_stage(text: str) -> str:
    lowered = f" {text.strip().lower()} "
    if not lowered.strip():
        return "applied"
    for stage, keywords in STAGE_KEYWORDS:
        for k in keywords:
            # "oa" must be a whole word, or "board" would match it.
            if (f" {k} " in lowered) if len(k) <= 2 else (k in lowered):
                return stage
    return "applied"


def parse_date(text: str, today: date) -> str:
    """YYYY-MM-DD, or '' if the cell isn't a date this recognizes. A date
    without a year gets the most recent such date not after today."""
    text = " ".join(text.replace(",", ", ").split()).replace(" ,", ",").strip()
    if not text:
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    for fmt in SHORT_DATE_FORMATS:
        try:
            parsed = datetime.strptime(f"{text} {today.year}", f"{fmt} %Y").date()
        except ValueError:
            continue
        if parsed > today:
            parsed = parsed.replace(year=today.year - 1)
        return parsed.isoformat()
    return ""


def row_fields(row: list[str], mapping: dict[str, int], today: date) -> dict:
    def cell(fld: str) -> str:
        i = mapping.get(fld)
        return row[i].strip() if i is not None and i < len(row) else ""

    url = cell("url")
    return {
        "company": cell("company"),
        "role": cell("role"),
        "url": url if url.startswith(("http://", "https://")) else "",
        "location": cell("location"),
        "stage": parse_stage(cell("stage")) if "stage" in mapping else "applied",
        "applied_at": parse_date(cell("applied_at"), today),
        "deadline": parse_date(cell("deadline"), today),
        "notes": cell("notes"),
    }


@dataclass
class ImportPlan:
    create: list[dict] = field(default_factory=list)
    fill: list[tuple[Application, dict]] = field(default_factory=list)
    unchanged: int = 0
    skipped_rows: int = 0

    def summary(self) -> dict:
        return {
            "new": len(self.create),
            "filled": len(self.fill),
            "unchanged": self.unchanged,
            "skipped_rows": self.skipped_rows,
            "preview": [
                {"company": f["company"], "role": f["role"], "stage": f["stage"]}
                for f in self.create[:50]
            ],
        }


def plan_import(rows: list[list[str]], jobs: JobStore, llm, cache: dict,
                today: date | None = None) -> ImportPlan:
    """What importing these rows would do, writing nothing."""
    today = today or date.today()
    if not rows:
        raise ValueError("that sheet is empty")
    header, body = rows[0], rows[1:]
    mapping = resolve_mapping(header, body, llm, cache)
    plan = ImportPlan()
    seen: set[tuple[str, str]] = set()
    for row in body:
        fields = row_fields(row, mapping, today)
        if not fields["company"]:
            plan.skipped_rows += 1
            continue
        key = (normalize_company(fields["company"]), fields["role"].lower())
        if key in seen:
            plan.skipped_rows += 1
            continue
        seen.add(key)
        existing = jobs.find(fields["company"], fields["role"])
        if existing is None:
            plan.create.append(fields)
            continue
        gaps = {f: fields[f] for f in FILLABLE if fields[f] and not getattr(existing, f)}
        if gaps:
            plan.fill.append((existing, gaps))
        else:
            plan.unchanged += 1
    return plan


def apply_plan(plan: ImportPlan, jobs: JobStore) -> None:
    for fields in plan.create:
        jobs.create(**fields, source="sheet")
    for existing, gaps in plan.fill:
        jobs.update(existing.id, gaps)

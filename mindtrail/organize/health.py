"""Sleep and workouts from an Apple Health export (export.zip / export.xml).

The export can be hundreds of megabytes, so it's streamed with iterparse
and each element is cleared once read - memory stays flat no matter the
file size.

Sleep: Apple Watch and iPhone both record sleep, often for the same
night, so a night's asleep intervals are merged before summing - adding
them up raw would double-count. A night belongs to the date you woke up.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import iterparse

from mindtrail.organize.db import connect

SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"
ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}
WORKOUT_PREFIX = "HKWorkoutActivityType"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"


@dataclass(frozen=True)
class HealthImport:
    nights: int
    workouts: int


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, DATE_FORMAT).astimezone()


def _pretty_workout(raw: str) -> str:
    name = raw.removeprefix(WORKOUT_PREFIX)
    out = ""
    for ch in name:
        out += (" " + ch.lower()) if ch.isupper() and out else ch
    return out or "Workout"


def _merge_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    total, cur_start, cur_end = 0.0, None, None
    for start, end in sorted(intervals):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += (cur_end - cur_start).total_seconds()
    return round(total / 60)


def _open_export(path: str):
    p = Path(path)
    if p.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(p)
        name = next((n for n in archive.namelist() if n.endswith("export.xml")), None)
        if name is None:
            raise ValueError("no export.xml inside that zip - is it an Apple Health export?")
        return archive.open(name)
    return open(p, "rb")


def read_export(path: str) -> tuple[dict[str, int], list[dict]]:
    """(minutes asleep per wake-up date, workouts) from an export."""
    sleep: dict[str, list[tuple[datetime, datetime]]] = {}
    workouts: list[dict] = []
    with _open_export(path) as stream:
        for _, el in iterparse(stream, events=("end",)):
            if el.tag == "Record" and el.get("type") == SLEEP_TYPE:
                if el.get("value") in ASLEEP_VALUES:
                    try:
                        start, end = _parse_time(el.get("startDate")), _parse_time(el.get("endDate"))
                    except (TypeError, ValueError):
                        start = end = None
                    if start and end and end > start:
                        sleep.setdefault(end.date().isoformat(), []).append((start, end))
            elif el.tag == "Workout":
                try:
                    start, end = _parse_time(el.get("startDate")), _parse_time(el.get("endDate"))
                except (TypeError, ValueError):
                    start = end = None
                if start and end and end > start:
                    raw = el.get("workoutActivityType", "")
                    workouts.append({
                        "id": f"{start.isoformat()}|{raw}", "date": start.date().isoformat(),
                        "type": _pretty_workout(raw),
                        "minutes": round((end - start).total_seconds() / 60),
                    })
            if el.tag in ("Record", "Workout"):
                el.clear()
    return {d: _merge_minutes(iv) for d, iv in sleep.items()}, workouts


class HealthStore:
    def __init__(self, path: str | None = None):
        self._path = path

    def import_export(self, export_path: str) -> HealthImport:
        """Upsert nights (a re-export has the full, corrected night) and add
        workouts not seen before."""
        nights, workouts = read_export(export_path)
        with connect(self._path) as conn:
            conn.executemany(
                "INSERT INTO health_sleep (date, minutes) VALUES (?, ?) "
                "ON CONFLICT(date) DO UPDATE SET minutes = excluded.minutes",
                sorted(nights.items()),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO health_workouts (id, date, type, minutes) VALUES (?, ?, ?, ?)",
                [(w["id"], w["date"], w["type"], w["minutes"]) for w in workouts],
            )
        return HealthImport(nights=len(nights), workouts=len(workouts))

    def sleep_between(self, start: str, end: str) -> dict[str, int]:
        with connect(self._path) as conn:
            rows = conn.execute("SELECT date, minutes FROM health_sleep WHERE date BETWEEN ? AND ?",
                                (start, end)).fetchall()
        return {r["date"]: r["minutes"] for r in rows}

    def workouts_between(self, start: str, end: str) -> list[dict]:
        with connect(self._path) as conn:
            rows = conn.execute(
                "SELECT date, type, minutes FROM health_workouts WHERE date BETWEEN ? AND ? "
                "ORDER BY date", (start, end)).fetchall()
        return [dict(r) for r in rows]

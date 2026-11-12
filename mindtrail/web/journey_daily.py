"""Once a day, read Gmail, Calendar and Canvas into every journey's
suggestions, so you don't have to press the scan buttons yourself.

Runs on a daemon thread while the server is up. A day's run is recorded
before it starts, so a crash mid-run doesn't retry in a loop and burn
the model's daily limit. Nothing is applied: everything lands in
Suggestions, waiting for Accept.
"""

from __future__ import annotations

import threading
from datetime import date

from mindtrail.web import journey_api

LAST_RUN_KEY = "journeyDailyScan"
CHECK_EVERY_SECONDS = 3600


def run_daily(deps, today: date | None = None) -> dict | None:
    """Scan every journey once per day. None when today's run already happened."""
    today = today or date.today()
    if deps.state.get(LAST_RUN_KEY) == today.isoformat():
        return None
    deps.state.set(LAST_RUN_KEY, today.isoformat())
    if deps.canvas.url():
        deps.canvas.refresh()
    results = {}
    for j in deps.journey.all():
        pid = j["project_id"]
        results[pid] = {
            "gmail": journey_api.handle_scan_gmail(deps.journey, deps.profile, deps.llm,
                                                   deps.scanner._gmail, project_id=pid),
            "calendar": journey_api.handle_scan_calendar(deps.journey, deps.profile, deps.llm,
                                                         deps.calendar_events, today, project_id=pid),
            "canvas": journey_api.canvas_to_school(deps.journey, deps.canvas, pid, today),
        }
    return results


class DailyJourneyScan:
    def __init__(self, deps, interval: float = CHECK_EVERY_SECONDS):
        self._deps = deps
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="journey-daily")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                run_daily(self._deps)
            except Exception as exc:  # noqa: BLE001 - a background thread must not die
                print(f"journey daily scan failed: {type(exc).__name__}: {exc}")
            self._stop.wait(self._interval)

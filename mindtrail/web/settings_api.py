"""Settings handlers: what's connected, and backups."""

from __future__ import annotations

from datetime import date

from mindtrail import config
from mindtrail.integrations import google_auth


def _google() -> dict:
    out = {"client_configured": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
           "connected": False, "calendar": False, "gmail": False, "sheets": False}
    creds = google_auth.load_credentials(google_auth.default_token_path())
    if creds is None:
        return out
    out.update(connected=True,
               calendar=google_auth.has_scope(creds, google_auth.CALENDAR_SCOPE),
               gmail=google_auth.has_scope(creds, google_auth.GMAIL_SCOPE),
               sheets=google_auth.has_scope(creds, google_auth.SHEETS_SCOPE))
    return out


def handle_connections(canvas, github, health, backups, google=_google) -> dict:
    """One answer for the Settings checklist. Reads cached state only - it
    never calls out to Google, GitHub or Canvas."""
    g = google()
    gh = github.cached()
    sleep = health.summary()
    checklist = [
        {"key": "google", "label": "Google", "done": g["connected"] and g["calendar"] and g["gmail"],
         "detail": ("Calendar, Gmail and Sheets are allowed" if g["connected"] and g["calendar"]
                    and g["gmail"] and g["sheets"] else
                    "Reconnect to allow all three" if g["connected"] else
                    "Run: mindtrail google connect" if g["client_configured"] else
                    "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env, then: mindtrail google connect")},
        {"key": "canvas", "label": "Canvas", "done": bool(canvas.url()),
         "detail": "Linked" if canvas.url() else "Paste your Canvas calendar feed link below"},
        {"key": "github", "label": "GitHub", "done": bool(gh.get("connected")),
         "detail": f"Reading as @{gh['login']}" if gh.get("connected") and gh.get("login")
                   else "Run: gh auth login"},
        {"key": "health", "label": "Apple Health", "done": sleep["nights"] > 0,
         "detail": f"{sleep['nights']} nights imported" if sleep["nights"]
                   else "Run: mindtrail health import export.zip"},
        {"key": "backups", "label": "Backups", "done": backups.enabled() and bool(backups.last()),
         "detail": (f"Last backup {backups.last()}" if backups.last() else "Waiting for the first backup")
                   if backups.enabled() else "Off - turn on in Backups below"},
    ]
    return {"google": g, "checklist": checklist,
            "done": sum(1 for c in checklist if c["done"]), "total": len(checklist)}


def _backups_json(backups) -> dict:
    return {"enabled": backups.enabled(), "folder": str(backups.folder()), "last": backups.last(), "keep": 14,
            "backups": [{"date": b.date, "db_bytes": b.db_bytes, "life_bytes": b.life_bytes}
                        for b in backups.list()]}


def handle_backups(backups) -> dict:
    return _backups_json(backups)


def handle_backup_run(backups, today: date | None = None) -> dict:
    try:
        backups.run(today or date.today())
    except OSError as exc:
        return {"error": f"couldn't write the backup: {exc}"}
    return _backups_json(backups)


def handle_backup_folder(backups, body: dict) -> dict:
    try:
        backups.set_folder(str(body.get("path", "")))
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}
    return _backups_json(backups)


def handle_backup_enable(backups, body: dict, today: date | None = None) -> dict:
    """Turn nightly backups on or off. Turning on with a "path" also sets
    the folder; without one it uses the suggested default."""
    on = bool(body.get("enabled"))
    try:
        if on:
            backups.set_folder(str(body.get("path") or backups.folder()))
        backups.set_enabled(on)
        if on and backups.due(today or date.today()):
            backups.run(today or date.today())  # the first copy now, not at the next hourly check
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}
    return _backups_json(backups)


def handle_backup_restore(backups, journal, body: dict) -> dict:
    try:
        created, skipped, failed, warnings = backups.restore(str(body.get("date", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    journal.reindex_all()  # the memory copies of journal entries are derived
    return {"restored": created, "failed": failed, "warnings": warnings[:5]}


def handle_weather(weather) -> dict:
    """The cached forecast. Never waits on the network: a stale cache is
    refreshed in the background and the next visit sees it."""
    weather.refresh_in_background_if_stale()
    return weather.cached()


def handle_set_weather(weather, body: dict) -> dict:
    try:
        if "unit" in body:
            weather.set_unit(str(body["unit"]))
        if "city" in body:
            weather.set_city(str(body["city"]))
        if weather.place():
            weather.refresh()  # the first look right away, not on the next visit
    except (ValueError, Exception) as exc:  # noqa: BLE001 - WeatherError and bad input both read as a message
        return {"error": str(exc)}
    return weather.cached()

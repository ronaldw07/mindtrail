"""Dated backups of the database, kept in a folder you choose.

Each run writes two files into the folder:
  mindtrail-YYYY-MM-DD.db   a consistent copy of the whole database
  life-YYYY-MM-DD.json      the life tables (to-dos, habits, journal, ...)
and keeps the newest KEEP of each. A second run on the same day overwrites
that day's pair rather than piling up.

Restoring merges life-YYYY-MM-DD.json back in: anything that was deleted or
changed since comes back, anything added since is left alone. The .db copy
is the whole-file safety net, restored by hand.

Nothing is written until backups are turned on in Settings: the copy can
land in iCloud Drive, so that's a choice, not a surprise. The suggested
folder is iCloud Drive when it exists, otherwise your home directory. The
Canvas feed link is never written (see life_data.PRIVATE_STATE_KEYS).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mindtrail.organize.db import default_db_path
from mindtrail.organize.life_data import PRIVATE_STATE_KEYS, dump_tables, load_tables

KEEP = 14
FOLDER_KEY = "backup_dir"
LAST_KEY = "backup_last"
ENABLED_KEY = "backup_enabled"
ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
_NAME = re.compile(r"^(mindtrail|life)-(\d{4}-\d{2}-\d{2})\.(db|json)$")


@dataclass(frozen=True)
class Backup:
    date: str
    db_bytes: int
    life_bytes: int


def default_folder() -> Path:
    base = ICLOUD if ICLOUD.is_dir() else Path.home()
    return base / "mindtrail-backups"


class BackupStore:
    def __init__(self, db_path: str | None, state, keep: int = KEEP):
        # None means the default database, which connect() resolves itself -
        # but the raw sqlite backup below needs the real path.
        self._db_path = db_path or default_db_path()
        self._state = state
        self._keep = keep
        self._lock = threading.Lock()

    def folder(self) -> Path:
        saved = self._state.get(FOLDER_KEY, "")
        return Path(saved) if saved else default_folder()

    def set_folder(self, path: str) -> Path:
        folder = Path(path.strip()).expanduser()
        if not folder.is_absolute():
            raise ValueError("use a full folder path, like /Users/you/Backups")
        if folder.exists() and not folder.is_dir():
            raise ValueError("that path is a file, not a folder")
        folder.mkdir(parents=True, exist_ok=True)
        self._state.set(FOLDER_KEY, str(folder))
        return folder

    def enabled(self) -> bool:
        return bool(self._state.get(ENABLED_KEY, False))

    def set_enabled(self, on: bool) -> None:
        self._state.set(ENABLED_KEY, bool(on))

    def last(self) -> str:
        return self._state.get(LAST_KEY, "") or ""

    def due(self, today: date) -> bool:
        return self.enabled() and self.last() != today.isoformat()

    def run(self, today: date) -> Backup:
        stamp = today.isoformat()
        with self._lock:
            folder = self.folder()
            folder.mkdir(parents=True, exist_ok=True)
            db_file = folder / f"mindtrail-{stamp}.db"
            life_file = folder / f"life-{stamp}.json"
            source = sqlite3.connect(self._db_path)
            try:
                target = sqlite3.connect(db_file)
                try:
                    source.backup(target)
                    # The copy leaves this machine (iCloud), so credentials
                    # that act like passwords stay out of it.
                    target.executemany("DELETE FROM app_state WHERE key = ?",
                                       [(k,) for k in PRIVATE_STATE_KEYS])
                    target.commit()
                finally:
                    target.close()
            finally:
                source.close()
            life_file.write_text(json.dumps(dump_tables(self._db_path), indent=2) + "\n",
                                 encoding="utf-8")
            self._state.set(LAST_KEY, stamp)
            self._prune(folder)
            return Backup(stamp, db_file.stat().st_size, life_file.stat().st_size)

    def _prune(self, folder: Path) -> None:
        for prefix in ("mindtrail", "life"):
            files = sorted((f for f in folder.iterdir()
                            if (m := _NAME.match(f.name)) and m.group(1) == prefix),
                           key=lambda f: f.name)
            for old in files[:-self._keep]:
                old.unlink()

    def list(self) -> list[Backup]:
        folder = self.folder()
        if not folder.is_dir():
            return []
        found: dict[str, dict[str, int]] = {}
        for f in folder.iterdir():
            m = _NAME.match(f.name)
            if m:
                found.setdefault(m.group(2), {})[m.group(1)] = f.stat().st_size
        return [Backup(d, sizes.get("mindtrail", 0), sizes.get("life", 0))
                for d, sizes in sorted(found.items(), reverse=True)]

    def restore(self, day: str) -> tuple[int, int, int, list[str]]:
        """Merge that day's life.json back in. Returns load_tables' counts."""
        date.fromisoformat(day)  # also stops a path from sneaking in
        file = self.folder() / f"life-{day}.json"
        if not file.is_file():
            raise ValueError(f"no backup for {day}")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"that backup can't be read: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("that backup isn't a life.json file")
        return load_tables(self._db_path, data, overwrite=True)


class BackupTimer:
    """Checks every `interval` seconds and backs up once per calendar day -
    on start (the catch-up if the app wasn't open yesterday), then whenever
    the date has rolled over."""

    def __init__(self, backups: BackupStore, interval: float = 3600, today=date.today):
        self._backups = backups
        self._interval = interval
        self._today = today
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="backup")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                today = self._today()
                if self._backups.due(today):
                    self._backups.run(today)
            except Exception as exc:  # noqa: BLE001 - a background thread must not die
                print(f"backup failed: {type(exc).__name__}: {exc}")
            self._stop.wait(self._interval)

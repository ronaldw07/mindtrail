"""Apple Health import: sleep merging, wake-up dating, workouts, re-import."""

import zipfile
from datetime import date

import pytest

from mindtrail.organize.db import initialize
from mindtrail.organize.health import HealthStore, read_export
from mindtrail.web.today import health_today

TZ = "-0700"
EXPORT = f"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisInBed"
   startDate="2026-09-29 23:00:00 {TZ}" endDate="2026-09-30 08:00:00 {TZ}"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisAsleepCore"
   startDate="2026-09-29 23:30:00 {TZ}" endDate="2026-09-30 03:00:00 {TZ}"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisAwake"
   startDate="2026-09-30 03:00:00 {TZ}" endDate="2026-09-30 03:20:00 {TZ}"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisAsleepDeep"
   startDate="2026-09-30 03:20:00 {TZ}" endDate="2026-09-30 07:20:00 {TZ}"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="iPhone" value="HKCategoryValueSleepAnalysisAsleepUnspecified"
   startDate="2026-09-29 23:30:00 {TZ}" endDate="2026-09-30 02:00:00 {TZ}"/>
 <Record type="HKQuantityTypeIdentifierStepCount" value="500" startDate="2026-09-30 10:00:00 {TZ}" endDate="2026-09-30 10:05:00 {TZ}"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining" duration="45"
   startDate="2026-09-30 18:00:00 {TZ}" endDate="2026-09-30 18:45:00 {TZ}"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning"
   startDate="2026-10-01 07:00:00 {TZ}" endDate="2026-10-01 07:30:00 {TZ}"/>
</HealthData>
"""


@pytest.fixture
def export_zip(tmp_path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("apple_health_export/export.xml", EXPORT)
    return str(path)


def local_date(s):
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z").astimezone().date().isoformat()


def test_overlapping_sleep_is_merged_and_awake_and_in_bed_excluded(export_zip):
    nights, workouts = read_export(export_zip)
    wake = local_date(f"2026-09-30 07:20:00 {TZ}")
    # 23:30-03:00 (iPhone's 23:30-02:00 overlaps it) + 03:20-07:20 = 210 + 240
    assert nights == {wake: 450}
    assert [(w["type"], w["minutes"]) for w in workouts] == [
        ("Traditional strength training", 45), ("Running", 30)]


def test_reimport_updates_nights_and_does_not_duplicate_workouts(tmp_path, export_zip):
    db = str(tmp_path / "t.db")
    initialize(db)
    health = HealthStore(db)
    assert health.import_export(export_zip).workouts == 2
    health.import_export(export_zip)
    assert len(health.workouts_between("2026-01-01", "2026-12-31")) == 2


def test_rejects_a_zip_without_an_export(tmp_path):
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("notes.txt", "hi")
    with pytest.raises(ValueError):
        read_export(str(path))


def test_today_summary(tmp_path, export_zip):
    db = str(tmp_path / "t.db")
    initialize(db)
    health = HealthStore(db)
    assert health_today(health, date(2026, 10, 1)) is None
    health.import_export(export_zip)
    data = health_today(health, date(2026, 10, 1))
    assert len(data["sleep"]) == 7 and data["avg_sleep"] == 450
    assert {w["type"] for w in data["workouts"]} == {"Traditional strength training", "Running"}

"""Request handlers for life areas, habits, and the journal.

Same contract as web/api.py and web/jobs_api.py: pure functions over the
stores, returning dicts, with bad input as {"error": ...}.
"""

from __future__ import annotations

from dataclasses import asdict

from mindtrail.organize.areas import AreaStore


def handle_list_areas(areas: AreaStore) -> dict:
    return {
        "areas": [asdict(a) for a in areas.all()],
        "project_areas": areas.project_areas(),
    }


def handle_create_area(areas: AreaStore, body: dict) -> dict:
    try:
        area = areas.create(str(body.get("name", "")), str(body.get("color", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"area": asdict(area)}


def handle_update_area(areas: AreaStore, area_id: str, body: dict) -> dict:
    try:
        area = areas.update(area_id, str(body.get("name", "")), str(body.get("color", "")))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"area": asdict(area)}


def handle_delete_area(areas: AreaStore, area_id: str) -> dict:
    try:
        areas.delete(area_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}


def handle_set_project_area(areas: AreaStore, project_id: str, body: dict) -> dict:
    try:
        areas.set_project_area(project_id, str(body.get("area_id") or ""))
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True}

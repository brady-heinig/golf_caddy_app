from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .legacy import course_data

router = APIRouter(prefix="/course", tags=["course"])


@router.get("/courses")
def list_courses() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid, c in course_data.COURSES.items():
        out.append(
            {
                "id": cid,
                "name": c.get("name"),
                "center_lat": c.get("center_lat"),
                "center_lon": c.get("center_lon"),
                "par": c.get("par"),
                "holes": len(c.get("holes", [])),
            }
        )
    return out


@router.get("/{course_id}/hole/{hole_number}")
def get_hole(course_id: str, hole_number: int) -> dict[str, Any]:
    course = course_data.COURSES.get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Unknown course_id")
    holes = course.get("holes", [])
    if hole_number < 1 or hole_number > len(holes):
        raise HTTPException(status_code=404, detail="Unknown hole_number")
    hole = holes[hole_number - 1]
    return {"course": {"id": course_id, "name": course.get("name")}, "hole": hole}


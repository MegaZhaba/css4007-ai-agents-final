"""Deterministic planning rules: progress, prerequisites, conflicts, plan checks.

The LLM never decides these questions. It calls tools that run this code.
"""

from __future__ import annotations

from itertools import combinations

from .constraints import Constraints
from .data import Dataset, passed_courses


def degree_progress(ds: Dataset, student: dict) -> dict:
    """What the student has passed and what the degree program still requires."""
    passed = passed_courses(student)
    program = ds.programs[student["program"]]
    groups = []
    for group in program["elective_groups"]:
        taken = [c for c in group["courses"] if c in passed]
        groups.append({
            "name": group["name"],
            "still_to_choose": max(0, group["choose"] - len(taken)),
            "options": [c for c in group["courses"] if c not in passed],
        })
    return {
        "passed": sorted(passed),
        "failed": sorted({r["course"] for r in student["completed"]} - passed),
        "earned_credits": sum(ds.courses[c]["credits"] for c in passed),
        "remaining_required": [c for c in program["required_courses"] if c not in passed],
        "remaining_electives": groups,
    }


def prerequisite_status(ds: Dataset, student: dict, course_code: str) -> dict:
    """A course is eligible when every prerequisite is passed and the course is not."""
    passed = passed_courses(student)
    missing = [c for c in ds.courses[course_code]["prerequisites"] if c not in passed]
    already_passed = course_code in passed
    return {
        "course": course_code,
        "eligible": not missing and not already_passed,
        "missing": missing,
        "already_passed": already_passed,
    }


def find_conflicts(sections: list[dict]) -> list[list[str]]:
    """Pairs of section ids that meet at the same time.

    Times are zero-padded "HH:MM", so they compare correctly as strings.
    A class that starts exactly when another one ends is not a conflict.
    """
    return [
        [a["id"], b["id"]]
        for a, b in combinations(sections, 2)
        if a["semester"] == b["semester"]
        and set(a["days"]) & set(b["days"])
        and a["start"] < b["end"]
        and b["start"] < a["end"]
    ]


def resolve_course(ds: Dataset, text: str) -> str | None:
    """Find a course code from a code or exact title; spaces and case do not matter."""
    wanted = _normalize(text)
    for code, course in ds.courses.items():
        if wanted in (_normalize(code), _normalize(course["title"])):
            return code
    return None


def check_plan(
    ds: Dataset, student: dict, semester: str, sections: list[dict], constraints: Constraints | None
) -> dict:
    """Check a plan against university rules and the student's constraints.

    Violations make the plan invalid. Warnings (for example a preferred course
    that is not in the plan) do not, because a preference can be impossible.
    """
    violations: list[dict] = []
    warnings: list[dict] = []

    def violation(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    def warning(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    planned: list[str] = []
    for sec in sections:
        sid, course = sec["id"], sec["course"]
        if sec["semester"] != semester:
            violation("wrong_semester", f"{sid} is offered in {sec['semester']}, not in {semester}")
        if sec["enrolled"] >= sec["capacity"]:
            violation("section_full", f"{sid} has no free seats")
        if course in planned:
            violation("duplicate_course", f"{course} is in the plan more than once")
            continue
        planned.append(course)
        status = prerequisite_status(ds, student, course)
        if status["missing"]:
            violation("missing_prerequisite", f"{course} requires {', '.join(status['missing'])}")
        if status["already_passed"]:
            violation("already_passed", f"{course} is already passed")

    for first, second in find_conflicts(sections):
        violation("time_conflict", f"{first} and {second} meet at the same time")

    credits = sum(ds.courses[c]["credits"] for c in planned)
    program = ds.programs[student["program"]]
    low, high = program["min_credits_per_semester"], program["max_credits_per_semester"]
    if not low <= credits <= high:
        violation("program_credits", f"{credits} credits; the program allows {low}-{high}")

    if constraints is not None:
        if constraints.semester and constraints.semester != semester:
            violation("wrong_semester", f"the student asked for {constraints.semester}, the plan is for {semester}")
        if constraints.min_credits and credits < constraints.min_credits:
            violation("too_few_credits", f"{credits} credits; the student asked for at least {constraints.min_credits}")
        if constraints.max_credits and credits > constraints.max_credits:
            violation("too_many_credits", f"{credits} credits; the student asked for at most {constraints.max_credits}")
        for sec in sections:
            sid = sec["id"]
            if constraints.earliest_start and sec["start"] < constraints.earliest_start:
                violation("too_early", f"{sid} starts at {sec['start']}, before {constraints.earliest_start}")
            if constraints.latest_end and sec["end"] > constraints.latest_end:
                violation("too_late", f"{sid} ends at {sec['end']}, after {constraints.latest_end}")
            for day in sec["days"]:
                if day in constraints.days_off:
                    violation("day_off", f"{sid} meets on {day}")
        for text in constraints.excluded_courses:
            code = resolve_course(ds, text)
            if code is None:
                warning("unknown_course", f"excluded course {text!r} is not in the catalog")
            elif code in planned:
                violation("excluded_course", f"{code} was excluded by the student")
        for text in constraints.preferred_courses:
            code = resolve_course(ds, text)
            if code is None:
                warning("unknown_course", f"preferred course {text!r} is not in the catalog")
            elif code not in planned:
                warning("preferred_missing", f"preferred course {code} is not in the plan")

    return {
        "ok": not violations,
        "total_credits": credits,
        "courses": planned,
        "violations": violations,
        "warnings": warnings,
    }


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()

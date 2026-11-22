"""Mock university data: catalog, timetable, students and degree programs.

Everything is read from JSON files in data/. The loader checks that the files
are consistent with each other, so later tools can trust the data they read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
PASSING_GRADES = ("A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D")
GRADES = PASSING_GRADES + ("F",)
# \Z, not $: in Python, $ also accepts a newline at the end.
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d\Z")
SEMESTER_RE = re.compile(r"^(Fall|Spring|Summer) 20\d\d\Z")


class DataError(Exception):
    """The data files are missing, unreadable or inconsistent."""


@dataclass(frozen=True)
class Dataset:
    courses: dict[str, dict]   # course code -> course
    sections: dict[str, dict]  # section id -> section
    students: dict[str, dict]  # student id -> student
    programs: dict[str, dict]  # program id -> program


def passed_courses(student: dict) -> set[str]:
    """Course codes the student has passed (a failed course does not count)."""
    return {r["course"] for r in student["completed"] if r["grade"] in PASSING_GRADES}


def load_dataset(data_dir: Path = DATA_DIR) -> Dataset:
    """Load all four files and fail loudly if they are inconsistent."""
    dataset = Dataset(
        courses=_index(_read(data_dir / "catalog.json"), "code"),
        sections=_index(_read(data_dir / "timetable.json"), "id"),
        students=_index(_read(data_dir / "students.json"), "id"),
        programs=_index(_read(data_dir / "programs.json"), "id"),
    )
    problems = validate_dataset(dataset)
    if problems:
        raise DataError("Inconsistent data: " + "; ".join(problems))
    return dataset


def validate_dataset(ds: Dataset) -> list[str]:
    """Return a list of problems; an empty list means the data is consistent."""
    problems: list[str] = []

    for code, course in ds.courses.items():
        if not isinstance(course.get("credits"), int) or course["credits"] < 1:
            problems.append(f"{code}: credits must be a positive integer")
        for pre in course.get("prerequisites", []):
            if pre not in ds.courses:
                problems.append(f"{code}: unknown prerequisite {pre}")
    problems += [f"prerequisite cycle through {c}" for c in _courses_in_cycles(ds.courses)]

    for sid, sec in ds.sections.items():
        if sec.get("course") not in ds.courses:
            problems.append(f"{sid}: unknown course {sec.get('course')}")
        if not SEMESTER_RE.match(str(sec.get("semester"))):
            problems.append(f"{sid}: bad semester {sec.get('semester')!r}")
        days = sec.get("days", [])
        if not days or any(d not in DAYS for d in days):
            problems.append(f"{sid}: bad days {days}")
        start, end = str(sec.get("start")), str(sec.get("end"))
        if not TIME_RE.match(start) or not TIME_RE.match(end) or start >= end:
            problems.append(f"{sid}: bad time {start}-{end}")
        capacity, enrolled = sec.get("capacity"), sec.get("enrolled")
        if not isinstance(capacity, int) or not isinstance(enrolled, int) or not 0 <= enrolled <= capacity:
            problems.append(f"{sid}: enrolled must be between 0 and capacity")

    for pid, program in ds.programs.items():
        listed = list(program.get("required_courses", []))
        for group in program.get("elective_groups", []):
            listed += group["courses"]
            if not 1 <= group["choose"] <= len(group["courses"]):
                problems.append(f"{pid}: group {group['name']!r} asks for more courses than it lists")
        problems += [f"{pid}: unknown course {c}" for c in listed if c not in ds.courses]

    for sid, student in ds.students.items():
        if student.get("program") not in ds.programs:
            problems.append(f"{sid}: unknown program {student.get('program')}")
        for record in student.get("completed", []):
            if record.get("course") not in ds.courses:
                problems.append(f"{sid}: unknown course {record.get('course')}")
            if record.get("grade") not in GRADES:
                problems.append(f"{sid}: bad grade {record.get('grade')!r}")

    return problems


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise DataError(f"Cannot read {path.name}: {e}") from e
    except json.JSONDecodeError as e:
        raise DataError(f"{path.name} is not valid JSON: {e}") from e
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise DataError(f"{path.name} must contain a list of objects")
    return data


def _index(items: list[dict], key: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise DataError(f"Record without a valid {key!r}: {item}")
        if value in index:
            raise DataError(f"Duplicate {key}: {value}")
        index[value] = item
    return index


def _courses_in_cycles(courses: dict[str, dict]) -> list[str]:
    """Courses that (directly or indirectly) require themselves."""
    in_cycle = []
    for start in courses:
        stack = list(courses[start].get("prerequisites", []))
        seen: set[str] = set()
        while stack:
            code = stack.pop()
            if code == start:
                in_cycle.append(start)
                break
            if code in seen or code not in courses:
                continue
            seen.add(code)
            stack.extend(courses[code].get("prerequisites", []))
    return in_cycle

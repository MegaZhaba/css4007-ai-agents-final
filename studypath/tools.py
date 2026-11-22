"""Read-only tools for the agent.

Every call goes through `Toolbox.invoke`: the tool name must be known, the
arguments must match the tool's model, and only then the tool runs. A toolbox
belongs to one student, so a tool call cannot read another student's record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .constraints import Constraints
from .data import Dataset
from .planning import check_plan, degree_progress, find_conflicts, prerequisite_status

CourseCode = Annotated[str, Field(pattern=r"^[A-Z]{3} \d{3,4}$", description='Course code, for example "CSS 320"')]
SectionId = Annotated[str, Field(pattern=r"^[A-Z]{3}\d{3,4}-[A-Z]$", description='Section id, for example "CSS320-A"')]
Semester = Annotated[str, Field(pattern=r"^(Fall|Spring|Summer) 20\d\d$", description='For example "Spring 2027"')]
StudentId = Annotated[str, Field(pattern=r"^s\d{4}$", description='Student id, for example "s1001"')]
SectionIds = Annotated[list[SectionId], Field(min_length=1, max_length=10)]
Tag = Annotated[str, Field(min_length=1, max_length=30)]


class ToolError(Exception):
    """A tool call was rejected or failed. `code` is stable and safe to log."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Args(BaseModel):
    # strict: "3" is not accepted as 3. forbid: unknown arguments are rejected.
    model_config = ConfigDict(strict=True, extra="forbid")


class StudentArgs(_Args):
    student_id: StudentId


class ProgramArgs(_Args):
    program: Annotated[str, Field(min_length=1, max_length=40, description='Program id, for example "bsc-cs"')]


class SearchArgs(_Args):
    query: Annotated[str, Field(max_length=100, description="Words to find in code, title, description or tags")] = ""
    season: Annotated[
        Literal["Fall", "Spring", "Summer"] | None, Field(description="Only courses offered in this season")
    ] = None
    tags: Annotated[list[Tag], Field(max_length=5, description="Only courses that have all these tags")] = []


class SectionsArgs(_Args):
    course_code: CourseCode
    semester: Semester


class PrerequisiteArgs(_Args):
    student_id: StudentId
    course_code: CourseCode


class ConflictArgs(_Args):
    section_ids: SectionIds


class PlanArgs(_Args):
    student_id: StudentId
    semester: Semester
    section_ids: SectionIds


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[Any], dict]

    def definition(self) -> dict:
        """The tool in the form that the model API expects."""
        return {"name": self.name, "description": self.description, "input_schema": self.args.model_json_schema()}


class Toolbox:
    def __init__(self, dataset: Dataset, student_id: str, constraints: Constraints | None = None):
        if student_id not in dataset.students:
            raise ToolError("not_found", f"Unknown student {student_id!r}")
        self._ds = dataset
        self._student_id = student_id
        # Set by the application, not by the model, so the model cannot relax them.
        self._constraints = constraints
        tools = [
            Tool("get_student_record", "Read the student's passed and failed courses, earned credits and what the "
                 "degree program still requires.", StudentArgs, self._get_student_record),
            Tool("get_degree_requirements", "Read the rules of a degree program: required courses, elective groups and "
                 "credit limits per semester.", ProgramArgs, self._get_degree_requirements),
            Tool("search_courses", "Search the course catalog. Returns course codes, titles, credits, prerequisites "
                 "and descriptions. With no arguments it lists every course.", SearchArgs, self._search_courses),
            Tool("get_course_sections", "List the sections of one course in one semester with days, times and free "
                 "seats. An empty list means the course is not offered.", SectionsArgs, self._get_course_sections),
            Tool("check_prerequisites", "Check if the student may take a course and which prerequisites are missing.",
                 PrerequisiteArgs, self._check_prerequisites),
            Tool("check_schedule_conflicts", "Find sections that meet at the same time.", ConflictArgs,
                 self._check_schedule_conflicts),
            Tool("validate_plan", "Check a complete semester plan against prerequisites, conflicts, free seats, credit "
                 "limits and the student's constraints. Call it before you present a plan.", PlanArgs,
                 self._validate_plan),
        ]
        self._tools = {tool.name: tool for tool in tools}

    def definitions(self) -> list[dict]:
        return [tool.definition() for tool in self._tools.values()]

    def invoke(self, name: str, arguments: object) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError("unknown_tool", f"Unknown tool {name!r}")
        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as e:
            details = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors()
            )
            raise ToolError("invalid_arguments", f"{name}: {details}") from e
        return tool.run(args)

    def _get_student_record(self, args: StudentArgs) -> dict:
        student = self._student(args.student_id)
        return {
            "id": student["id"],
            "name": student["name"],
            "program": student["program"],
            "year": student["year"],
            **degree_progress(self._ds, student),
        }

    def _get_degree_requirements(self, args: ProgramArgs) -> dict:
        program = self._ds.programs.get(args.program)
        if program is None:
            raise ToolError("not_found", f"Unknown program {args.program!r}")
        return {
            "id": program["id"],
            "title": program["title"],
            "min_credits_per_semester": program["min_credits_per_semester"],
            "max_credits_per_semester": program["max_credits_per_semester"],
            "required_courses": list(program["required_courses"]),
            "elective_groups": [{**g, "courses": list(g["courses"])} for g in program["elective_groups"]],
        }

    def _search_courses(self, args: SearchArgs) -> dict:
        words = args.query.lower().split()
        wanted_tags = {t.lower() for t in args.tags}
        found = []
        for course in self._ds.courses.values():
            text = " ".join([course["code"], course["title"], course["description"], *course["tags"]]).lower()
            if (
                all(w in text for w in words)
                and wanted_tags <= set(course["tags"])
                and (args.season is None or args.season in course["semesters_offered"])
            ):
                found.append({
                    "code": course["code"],
                    "title": course["title"],
                    "credits": course["credits"],
                    "prerequisites": list(course["prerequisites"]),
                    "semesters_offered": list(course["semesters_offered"]),
                    "tags": list(course["tags"]),
                    "description": course["description"],
                })
        return {"courses": found}

    def _get_course_sections(self, args: SectionsArgs) -> dict:
        self._require_course(args.course_code)
        return {
            "course": args.course_code,
            "semester": args.semester,
            "sections": [
                {
                    "id": s["id"],
                    "days": list(s["days"]),
                    "start": s["start"],
                    "end": s["end"],
                    "seats_left": s["capacity"] - s["enrolled"],
                }
                for s in self._ds.sections.values()
                if s["course"] == args.course_code and s["semester"] == args.semester
            ],
        }

    def _check_prerequisites(self, args: PrerequisiteArgs) -> dict:
        student = self._student(args.student_id)
        self._require_course(args.course_code)
        return prerequisite_status(self._ds, student, args.course_code)

    def _check_schedule_conflicts(self, args: ConflictArgs) -> dict:
        conflicts = find_conflicts(self._sections(args.section_ids))
        return {"ok": not conflicts, "conflicts": conflicts}

    def _validate_plan(self, args: PlanArgs) -> dict:
        student = self._student(args.student_id)
        return check_plan(self._ds, student, args.semester, self._sections(args.section_ids), self._constraints)

    def _student(self, student_id: str) -> dict:
        # The same answer for another student and for an id that does not exist.
        if student_id != self._student_id:
            raise ToolError("forbidden", f"No access to student {student_id!r}")
        return self._ds.students[student_id]

    def _require_course(self, code: str) -> None:
        if code not in self._ds.courses:
            raise ToolError("not_found", f"Unknown course {code!r}")

    def _sections(self, section_ids: list[str]) -> list[dict]:
        unknown = [s for s in section_ids if s not in self._ds.sections]
        if unknown:
            raise ToolError("not_found", f"Unknown sections: {', '.join(unknown)}")
        if len(set(section_ids)) != len(section_ids):
            raise ToolError("invalid_arguments", "section_ids must not repeat a section")
        return [self._ds.sections[s] for s in section_ids]

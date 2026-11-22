import copy
from dataclasses import replace

import pytest

from studypath.__main__ import main
from studypath.constraints import Constraints
from studypath.data import load_dataset
from studypath.planning import find_conflicts, resolve_course
from studypath.tools import Toolbox, ToolError

SPRING = "Spring 2027"
# A valid 16-credit plan for s1001 with no class before 10:00.
GOOD_PLAN = ["CSS202-A", "MAT220-B", "CSS210-A", "CSS230-A", "CSS240-A"]


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


@pytest.fixture
def toolbox(dataset):
    return Toolbox(dataset, "s1001")


def constraints(**changes) -> Constraints:
    base = Constraints(
        is_planning_request=True, semester=SPRING, min_credits=15, max_credits=18, earliest_start="10:00",
        latest_end=None, days_off=(), preferred_courses=(), excluded_courses=(),
    )
    return replace(base, **changes)


def plan(toolbox, section_ids, student_id="s1001", semester=SPRING):
    return toolbox.invoke(
        "validate_plan", {"student_id": student_id, "semester": semester, "section_ids": section_ids}
    )


def codes(items):
    return [i["code"] for i in items]


def section(sid, days, start, end, semester=SPRING):
    return {"id": sid, "days": days, "start": start, "end": end, "semester": semester}


# --- reading tools ---


def test_student_record_shows_progress(toolbox):
    record = toolbox.invoke("get_student_record", {"student_id": "s1001"})

    assert record["earned_credits"] == 35
    assert record["failed"] == []
    assert "CSS 201" in record["passed"] and "MAT 220" in record["remaining_required"]
    ai = next(g for g in record["remaining_electives"] if g["name"] == "AI track")
    assert ai["still_to_choose"] == 3
    general = next(g for g in record["remaining_electives"] if g["name"] == "General electives")
    assert general["still_to_choose"] == 0  # HUM 110 is passed


def test_failed_course_stays_required_and_gives_no_credits(dataset):
    record = Toolbox(dataset, "s1002").invoke("get_student_record", {"student_id": "s1002"})

    assert record["failed"] == ["CSS 201"]
    assert "CSS 201" in record["remaining_required"]
    assert record["earned_credits"] == 28


def test_degree_requirements(toolbox):
    program = toolbox.invoke("get_degree_requirements", {"program": "bsc-cs"})

    assert (program["min_credits_per_semester"], program["max_credits_per_semester"]) == (12, 21)
    assert "CSS 310" in program["required_courses"]
    with pytest.raises(ToolError) as error:
        toolbox.invoke("get_degree_requirements", {"program": "bsc-art"})
    assert error.value.code == "not_found"


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"query": "machine learning"}, {"CSS 320"}),
        ({"query": "MACHINE  LEARNING"}, {"CSS 320"}),
        ({"tags": ["ai"], "season": "Spring"}, {"CSS 320", "CSS 350", "CSS 4007"}),
        ({"tags": ["ai", "theory"]}, {"CSS 4007"}),
        ({"query": "quantum cooking"}, set()),
    ],
)
def test_search_courses(toolbox, arguments, expected):
    found = toolbox.invoke("search_courses", arguments)["courses"]

    assert {c["code"] for c in found} == expected


def test_search_without_arguments_lists_every_course(toolbox, dataset):
    assert len(toolbox.invoke("search_courses", {})["courses"]) == len(dataset.courses)


def test_course_sections(toolbox):
    result = toolbox.invoke("get_course_sections", {"course_code": "CSS 102", "semester": SPRING})
    assert {s["id"]: s["seats_left"] for s in result["sections"]} == {"CSS102-A": 0, "CSS102-B": 18}

    not_offered = toolbox.invoke("get_course_sections", {"course_code": "CSS 310", "semester": SPRING})
    assert not_offered["sections"] == []

    with pytest.raises(ToolError) as error:
        toolbox.invoke("get_course_sections", {"course_code": "CSS 999", "semester": SPRING})
    assert error.value.code == "not_found"


def test_tool_results_cannot_change_the_dataset(toolbox, dataset):
    before = copy.deepcopy(dataset)

    toolbox.invoke("search_courses", {})["courses"][0]["tags"].append("changed")
    toolbox.invoke("get_degree_requirements", {"program": "bsc-cs"})["elective_groups"][0]["courses"].clear()
    toolbox.invoke("get_course_sections", {"course_code": "CSS 320", "semester": SPRING})["sections"][0]["days"].clear()
    toolbox.invoke("check_prerequisites", {"student_id": "s1001", "course_code": "CSS 320"})["missing"].clear()

    assert dataset == before


# --- prerequisites and conflicts ---


@pytest.mark.parametrize(
    "student, course, eligible, missing, already_passed",
    [
        ("s1001", "CSS 320", False, ["MAT 220"], False),
        ("s1001", "CSS 202", True, [], False),
        ("s1001", "CSS 101", False, [], True),
        ("s1002", "CSS 201", True, [], False),  # failed, so it can be taken again
        ("s1002", "CSS 301", False, ["CSS 201"], False),  # a failed prerequisite does not count
        ("s1003", "CSS 320", True, [], False),
    ],
)
def test_check_prerequisites(dataset, student, course, eligible, missing, already_passed):
    result = Toolbox(dataset, student).invoke("check_prerequisites", {"student_id": student, "course_code": course})

    assert result == {"course": course, "eligible": eligible, "missing": missing, "already_passed": already_passed}


@pytest.mark.parametrize(
    "a, b, conflict",
    [
        (section("A", ["Mon"], "10:00", "11:00"), section("B", ["Mon"], "10:30", "11:30"), True),
        (section("A", ["Mon"], "10:00", "12:00"), section("B", ["Mon"], "10:30", "11:00"), True),  # inside
        (section("A", ["Mon"], "10:00", "11:00"), section("B", ["Mon"], "11:00", "12:00"), False),  # back to back
        (section("A", ["Mon"], "10:00", "11:00"), section("B", ["Tue"], "10:00", "11:00"), False),
        (section("A", ["Mon", "Wed"], "10:00", "11:00"), section("B", ["Wed", "Fri"], "10:00", "11:00"), True),
        (section("A", ["Mon"], "10:00", "11:00"), section("B", ["Mon"], "10:00", "11:00", "Fall 2027"), False),
    ],
)
def test_find_conflicts(a, b, conflict):
    assert find_conflicts([a, b]) == ([["A", "B"]] if conflict else [])
    assert find_conflicts([b, a]) == ([["B", "A"]] if conflict else [])


def test_check_schedule_conflicts_tool(toolbox):
    clash = toolbox.invoke("check_schedule_conflicts", {"section_ids": ["CSS201-A", "CSS4007-A", "CSS210-A"]})
    assert clash == {"ok": False, "conflicts": [["CSS201-A", "CSS4007-A"]]}

    fine = toolbox.invoke("check_schedule_conflicts", {"section_ids": GOOD_PLAN})
    assert fine == {"ok": True, "conflicts": []}


# --- validate_plan ---


def test_good_plan_passes(dataset):
    result = plan(Toolbox(dataset, "s1001", constraints()), GOOD_PLAN)

    assert result["ok"] is True
    assert result["total_credits"] == 16
    assert result["violations"] == [] and result["warnings"] == []


@pytest.mark.parametrize(
    "section_ids, violation",
    [
        (["CSS202-A", "CSS320-A", "CSS210-A", "CSS230-A"], "missing_prerequisite"),
        (["CSS202-A", "CSS210-A", "CSS230-A", "CSS101-A"], "already_passed"),
        (["CSS202-A", "CSS210-A", "CSS230-A", "CSS102-A"], "section_full"),
        (["CSS202-A", "CSS210-A", "MAT220-A", "MAT220-B"], "duplicate_course"),
        (["CSS202-A", "MAT201-A", "CSS210-A", "CSS230-A"], "time_conflict"),
        (["CSS202-A"], "program_credits"),
    ],
)
def test_plan_rules(toolbox, section_ids, violation):
    result = plan(toolbox, section_ids)

    assert result["ok"] is False
    assert violation in codes(result["violations"])


def test_duplicate_course_counts_credits_once(toolbox):
    assert plan(toolbox, ["MAT220-A", "MAT220-B"])["total_credits"] == 3


def test_plan_for_another_semester_is_rejected(toolbox):
    assert "wrong_semester" in codes(plan(toolbox, GOOD_PLAN, semester="Fall 2027")["violations"])


@pytest.mark.parametrize(
    "changes, violation",
    [
        ({"semester": "Fall 2027"}, "wrong_semester"),
        ({"min_credits": 17}, "too_few_credits"),
        ({"min_credits": None, "max_credits": 15}, "too_many_credits"),
        ({"earliest_start": "11:00"}, "too_early"),
        ({"latest_end": "15:00"}, "too_late"),
        ({"days_off": ("Fri",)}, "day_off"),
        ({"excluded_courses": ("web development",)}, "excluded_course"),
    ],
)
def test_student_constraints(dataset, changes, violation):
    result = plan(Toolbox(dataset, "s1001", constraints(**changes)), GOOD_PLAN)

    assert result["ok"] is False
    assert codes(result["violations"]).count(violation) >= 1
    assert set(codes(result["violations"])) == {violation}


def test_preferences_are_warnings_not_violations(dataset):
    wishes = constraints(preferred_courses=("Machine Learning", "Underwater Basket Weaving", "css210"))

    result = plan(Toolbox(dataset, "s1001", wishes), GOOD_PLAN)

    assert result["ok"] is True
    assert codes(result["warnings"]) == ["preferred_missing", "unknown_course"]


def test_resolve_course_accepts_code_or_title(dataset):
    assert resolve_course(dataset, "css 320") == resolve_course(dataset, "Machine learning") == "CSS 320"
    assert resolve_course(dataset, "Learning") is None  # a part of a title is ambiguous


# --- argument validation and access ---


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("get_student_record", {}),
        ("get_student_record", {"student_id": 1001}),
        ("get_student_record", {"student_id": "s1001\n"}),
        ("get_student_record", {"student_id": "../students"}),
        ("get_student_record", {"student_id": "s1001", "admin": True}),
        ("get_student_record", None),
        ("get_student_record", "s1001"),
        ("search_courses", {"season": "Winter"}),
        ("search_courses", {"query": "x" * 101}),
        ("search_courses", {"tags": "ai"}),
        ("get_course_sections", {"course_code": "CSS320", "semester": SPRING}),
        ("get_course_sections", {"course_code": "CSS 320", "semester": "next spring"}),
        ("check_schedule_conflicts", {"section_ids": []}),
        ("check_schedule_conflicts", {"section_ids": ["CSS320-A"] * 11}),
        ("check_schedule_conflicts", {"section_ids": ["CSS320-A", "CSS320-A"]}),
        ("validate_plan", {"student_id": "s1001", "semester": SPRING, "section_ids": [1]}),
    ],
)
def test_invalid_arguments_are_rejected(toolbox, name, arguments):
    with pytest.raises(ToolError) as error:
        toolbox.invoke(name, arguments)

    assert error.value.code == "invalid_arguments"


def test_model_cannot_replace_the_constraints(dataset):
    toolbox = Toolbox(dataset, "s1001", constraints(days_off=("Fri",)))

    with pytest.raises(ToolError) as error:
        toolbox.invoke(
            "validate_plan",
            {"student_id": "s1001", "semester": SPRING, "section_ids": GOOD_PLAN, "constraints": {}},
        )

    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize("name", ["drop_course", "register_sections", "__init__", "_student", "invoke", ""])
def test_unknown_tools_are_rejected(toolbox, name):
    with pytest.raises(ToolError) as error:
        toolbox.invoke(name, {})

    assert error.value.code == "unknown_tool"


@pytest.mark.parametrize("other", ["s1002", "s9999"])
@pytest.mark.parametrize(
    "name, extra",
    [
        ("get_student_record", {}),
        ("check_prerequisites", {"course_code": "CSS 320"}),
        ("validate_plan", {"semester": SPRING, "section_ids": GOOD_PLAN}),
    ],
)
def test_no_access_to_other_students(toolbox, name, extra, other):
    with pytest.raises(ToolError) as error:
        toolbox.invoke(name, {"student_id": other, **extra})

    assert error.value.code == "forbidden"


def test_unknown_sections_are_reported(toolbox):
    with pytest.raises(ToolError, match="CSS999-A") as error:
        plan(toolbox, ["CSS202-A", "CSS999-A"])

    assert error.value.code == "not_found"


def test_toolbox_needs_a_known_student(dataset):
    with pytest.raises(ToolError):
        Toolbox(dataset, "s9999")


def test_definitions_describe_every_tool(toolbox):
    definitions = {d["name"]: d for d in toolbox.definitions()}

    assert set(definitions) == {
        "get_student_record", "get_degree_requirements", "search_courses", "get_course_sections",
        "check_prerequisites", "check_schedule_conflicts", "validate_plan",
    }
    for definition in definitions.values():
        assert definition["description"]
        assert definition["input_schema"]["type"] == "object"
        assert definition["input_schema"]["additionalProperties"] is False


# --- command line ---


def test_cli_runs_a_tool(capsys):
    assert main(["--tool", "check_prerequisites", "--args", '{"student_id": "s1001", "course_code": "CSS 320"}']) == 0
    assert '"MAT 220"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, exit_code, message",
    [
        (["--tool", "drop_course"], 1, "unknown_tool"),
        (["--tool", "search_courses", "--args", "{bad"], 2, "not valid JSON"),
        (["--tool", "get_student_record", "--args", '{"student_id": "s1002"}'], 1, "forbidden"),
    ],
)
def test_cli_reports_tool_errors(capsys, argv, exit_code, message):
    assert main(argv) == exit_code
    assert message in capsys.readouterr().err

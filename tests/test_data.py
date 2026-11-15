import copy
import json
from dataclasses import replace

import pytest

from studypath.config import DATA_DIR
from studypath.data import DataError, load_dataset, passed_courses, validate_dataset


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def test_mock_data_loads_and_is_consistent(dataset):
    assert validate_dataset(dataset) == []
    assert len(dataset.courses) >= 20
    assert {"s1001", "s1002", "s1003"} <= dataset.students.keys()
    assert dataset.courses["CSS 320"]["prerequisites"] == ["CSS 201", "MAT 201", "MAT 220"]


def test_failed_course_does_not_count_as_passed(dataset):
    daniyar = dataset.students["s1002"]

    assert "CSS 201" in {r["course"] for r in daniyar["completed"]}
    assert "CSS 201" not in passed_courses(daniyar)
    assert "CSS 102" in passed_courses(daniyar)


def test_scenarios_from_the_proposal_exist_in_the_data(dataset):
    # Aigerim wants Machine Learning but has not passed Probability and Statistics.
    missing = set(dataset.courses["CSS 320"]["prerequisites"]) - passed_courses(dataset.students["s1001"])
    assert missing == {"MAT 220"}
    # There is a full section, so "section is full -> replan" can be tested later.
    assert any(s["enrolled"] == s["capacity"] for s in dataset.sections.values())


def test_validation_finds_unknown_prerequisite(dataset):
    courses = copy.deepcopy(dataset.courses)
    courses["CSS 320"]["prerequisites"].append("CSS 999")

    assert "CSS 320: unknown prerequisite CSS 999" in validate_dataset(replace(dataset, courses=courses))


def test_validation_finds_prerequisite_cycle(dataset):
    courses = copy.deepcopy(dataset.courses)
    courses["CSS 101"]["prerequisites"] = ["CSS 201"]  # 101 -> 201 -> 102 -> 101

    problems = validate_dataset(replace(dataset, courses=courses))

    assert "prerequisite cycle through CSS 101" in problems


def test_validation_finds_bad_section(dataset):
    sections = copy.deepcopy(dataset.sections)
    sections["CSS320-A"].update(start="12:00", end="11:00", enrolled=99, days=["Sunday"])

    problems = validate_dataset(replace(dataset, sections=sections))

    assert "CSS320-A: bad time 12:00-11:00" in problems
    assert "CSS320-A: enrolled must be between 0 and capacity" in problems
    assert "CSS320-A: bad days ['Sunday']" in problems


def test_loading_fails_clearly_on_broken_files(tmp_path):
    with pytest.raises(DataError, match="Cannot read catalog.json"):
        load_dataset(tmp_path)

    for name in ("catalog", "timetable", "students", "programs"):
        (tmp_path / f"{name}.json").write_text((DATA_DIR / f"{name}.json").read_text())
    (tmp_path / "timetable.json").write_text("{ not json")
    with pytest.raises(DataError, match="timetable.json is not valid JSON"):
        load_dataset(tmp_path)

    students = json.loads((DATA_DIR / "students.json").read_text())
    students[0]["completed"][0]["course"] = "CSS 999"
    (tmp_path / "timetable.json").write_text((DATA_DIR / "timetable.json").read_text())
    (tmp_path / "students.json").write_text(json.dumps(students))
    with pytest.raises(DataError, match="s1001: unknown course CSS 999"):
        load_dataset(tmp_path)

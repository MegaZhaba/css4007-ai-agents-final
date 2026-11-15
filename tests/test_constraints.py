import json

import pytest

from studypath.config import MAX_GOAL_CHARS
from studypath.constraints import (
    CONSTRAINTS_SCHEMA,
    ConstraintError,
    InvalidGoalError,
    extract_constraints,
    validate_constraints,
)
from studypath.llm import LLMError
from studypath.testing import ScriptedLLM

GOAL = "Plan my Spring 2027 semester: 15-18 credits, no classes before 10:00, I want Machine Learning."


def answer(**changes) -> dict:
    """A valid model answer for GOAL, with optional field overrides."""
    base = {
        "is_planning_request": True,
        "semester": "Spring 2027",
        "min_credits": 15,
        "max_credits": 18,
        "earliest_start": "10:00",
        "latest_end": None,
        "days_off": [],
        "preferred_courses": ["Machine Learning"],
        "excluded_courses": [],
    }
    return {**base, **changes}


def test_valid_answer_becomes_constraints():
    llm = ScriptedLLM(json.dumps(answer()))

    result = extract_constraints(GOAL, llm)

    assert result.semester == "Spring 2027"
    assert (result.min_credits, result.max_credits) == (15, 18)
    assert result.earliest_start == "10:00"
    assert result.preferred_courses == ("Machine Learning",)
    assert result.to_dict() == answer()
    assert len(llm.calls) == 1


def test_request_keeps_instructions_and_user_text_apart():
    llm = ScriptedLLM(json.dumps(answer()))

    extract_constraints(GOAL, llm)

    call = llm.calls[0]
    assert call["json_schema"] is CONSTRAINTS_SCHEMA
    assert GOAL not in call["system"]
    assert call["messages"] == [{"role": "user", "content": f"<request>\n{GOAL}\n</request>"}]


def test_rejected_answer_is_asked_again_with_the_reason():
    llm = ScriptedLLM("this is not JSON", json.dumps(answer(min_credits=20)), json.dumps(answer()))

    result = extract_constraints(GOAL, llm)

    assert result.max_credits == 18
    assert len(llm.calls) == 3
    assert "not valid JSON" in llm.calls[1]["messages"][0]["content"]
    assert "min_credits must not be greater than max_credits" in llm.calls[2]["messages"][0]["content"]


def test_gives_up_after_the_retry_limit():
    llm = ScriptedLLM(*["{}"] * 3)

    with pytest.raises(ConstraintError) as error:
        extract_constraints(GOAL, llm, max_retries=2)

    assert len(llm.calls) == 3  # first attempt + 2 retries, then stop
    assert "missing field semester" in error.value.problems


@pytest.mark.parametrize("goal", ["", "   \n", None, 42, "x" * (MAX_GOAL_CHARS + 1)])
def test_unusable_goal_is_rejected_without_calling_the_model(goal):
    llm = ScriptedLLM()

    with pytest.raises(InvalidGoalError):
        extract_constraints(goal, llm)

    assert llm.calls == []


def test_api_failure_is_not_retried_or_hidden():
    llm = ScriptedLLM(LLMError("Rate limit reached. Try again later.", retryable=True))

    with pytest.raises(LLMError, match="Rate limit"):
        extract_constraints(GOAL, llm)

    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"semester": "next spring"}, "semester must look like"),
        ({"min_credits": 0}, "min_credits must be an integer"),
        ({"max_credits": 99}, "max_credits must be an integer"),
        ({"max_credits": "18"}, "max_credits must be an integer"),
        ({"min_credits": True}, "min_credits must be an integer"),
        ({"min_credits": 18, "max_credits": 15}, "must not be greater"),
        ({"earliest_start": "10am"}, "earliest_start must be a 24-hour time"),
        ({"earliest_start": "25:00"}, "earliest_start must be a 24-hour time"),
        ({"earliest_start": "16:00", "latest_end": "12:00"}, "earliest_start must be before latest_end"),
        ({"days_off": ["Funday"]}, "days_off must be a list"),
        ({"days_off": ["Fri", "Fri"]}, "days_off must be a list"),
        ({"preferred_courses": "Machine Learning"}, "preferred_courses must be a list"),
        ({"preferred_courses": [""]}, "preferred_courses must be a list"),
        ({"preferred_courses": ["x"] * 11}, "preferred_courses must be a list"),
        ({"excluded_courses": ["machine learning"]}, "both preferred and excluded"),
        ({"is_planning_request": "yes"}, "is_planning_request must be true or false"),
    ],
)
def test_validation_rejects_bad_values(changes, problem):
    with pytest.raises(ConstraintError, match=problem):
        validate_constraints(answer(**changes))


def test_validation_rejects_wrong_shape():
    with pytest.raises(ConstraintError, match="JSON object"):
        validate_constraints(["not", "an", "object"])
    with pytest.raises(ConstraintError, match="unexpected field register_now"):
        validate_constraints(answer(register_now=True))


def test_validation_reports_every_problem_at_once():
    with pytest.raises(ConstraintError) as error:
        validate_constraints(answer(semester="soon", days_off=["Funday"]))

    assert len(error.value.problems) == 2


def test_unstated_values_stay_empty():
    raw = answer(semester=None, min_credits=None, max_credits=None, earliest_start=None, preferred_courses=[])

    result = validate_constraints(raw)

    assert result.semester is None and result.min_credits is None
    assert result.preferred_courses == ()

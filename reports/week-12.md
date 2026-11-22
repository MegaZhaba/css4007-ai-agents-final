# Semester Week 12 Progress Report

## Completed Work

- **Seven read-only tools** (`studypath/tools.py`): `get_student_record`, `get_degree_requirements`, `search_courses`, `get_course_sections`, `check_prerequisites`, `check_schedule_conflicts`, `validate_plan`. Each tool has a description and a JSON schema in the form that the model API expects.
- **Deterministic planning rules** (`studypath/planning.py`): degree progress, prerequisites, time conflicts and the full plan check. The model does not decide these questions.
- **Plan check**: wrong semester, full section, duplicate course, missing prerequisite, course already passed, time conflict, program credit limits, and the student's own constraints (credits, earliest start, latest end, free days, excluded courses). A preferred course that is not in the plan is a warning, because a preference can be impossible.
- **Argument validation**: every call goes through `Toolbox.invoke`, which checks the tool name and validates the arguments with a strict Pydantic model before the tool runs. Unknown arguments, wrong types and malformed ids are rejected.
- **Access limit**: a toolbox belongs to one student. A call that names another student is rejected in code.
- **Command line**: `python -m studypath --tool NAME --args JSON --student ID` runs one tool without the model.
- **Tests**: 80 new cases, 131 in total.
- **Bug fix from Week 11**: the time and semester checks accepted a newline at the end (for example `"10:00\n"`). Two new tests fail without the fix.

## Important Commits

- "Add read-only tools, planning checks and argument validation (Week 12)" — everything listed above plus this report.
- `ec2a843` (Week 11) — mock data, model client and constraint extraction, which this work builds on.

## Current Functionality

- All read-only tools work on the mock data and can be run from the command line.
- The example from the proposal works at the tool level: for student s1001 the tools report that Machine Learning (CSS 320) is blocked by Probability and Statistics (MAT 220), and `validate_plan` accepts a 16-credit Spring 2027 plan with no class before 10:00.
- **The model does not call the tools yet.** The tool-calling connection is the Week 13 milestone.
- **The real Claude API has still not been called**, because no API key is configured. The Week 11 plan to test the extraction on the real model is not done and moves to Week 13.
- `get_registration`, `save_plan` and `register_sections` are not built. They belong to Week 14.

## Problems Encountered

- In the proposal, `validate_plan` takes the constraints as an argument. The model would then supply the rules that its own plan is checked against, and could relax them.
- The tools take a `student_id` from the model, so a wrong or injected id could expose the record of another student.
- A preferred course can be impossible to take (missing prerequisite). If that made the plan invalid, the agent could never finish.
- A failed course appears in the transcript, but it must not count as passed, must not give credits and must be possible to retake.
- In Python regular expressions `$` also matches before a newline at the end of the text, which caused the Week 11 bug.

## Solutions

- The application gives the constraints to the toolbox when it creates it, and `validate_plan` does not accept them from the model. This is a deliberate change from the proposal.
- The toolbox is bound to one student id. Other ids get the same "forbidden" answer whether they exist or not.
- Hard rules produce violations, and preferences produce warnings. Only violations make a plan invalid.
- All progress calculations use one function, `passed_courses`, which ignores failed grades. Tests cover the student with the failed course.
- The patterns now use `\Z` instead of `$`.

## What I Learned

- A tool parameter is part of the security design: what the model is allowed to supply is as important as what the tool does.
- Validation from one model (schema for the LLM and check in code) keeps the two from becoming different.
- A check needs tests for its boundaries: classes that are back to back, one inside the other, or on different days.
- AI assistance disclosure: the code and tests in this commit were written with Claude Code (an AI coding assistant).

## Next Week

- Get an API key and run the constraint extraction against the real model.
- Connect the tools to the model: send the definitions, execute the requested calls, return the results.
- Add permission classes to the tools and an execution trace log (JSON Lines) without secrets.
- Support requests that need no tools, add tests with the scripted fake model, and complete `reports/week-13.md`.

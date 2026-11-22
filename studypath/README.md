# StudyPath

Autonomous academic planning agent — see [reports/proposal.md](../reports/proposal.md) for the full design.

## Status (Week 12)

Working now:

- Mock university data in `data/` (catalog, timetable, students, degree program) with a consistency check.
- `LLMClient` interface and the real adapter for Claude (`studypath/llm.py`).
- Constraint extraction: a goal in plain language → validated JSON constraints (`studypath/constraints.py`).
- Seven read-only tools with strict argument validation (`studypath/tools.py`).
- Deterministic checks for prerequisites, time conflicts and complete plans (`studypath/planning.py`).

Not built yet: tool calling through the model, trace logging, the agent loop, write tools with approval (Weeks 13–15).

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # then put your API key into .env
```

## Run

```bash
.venv/bin/python -m studypath --check-data
.venv/bin/python -m studypath "Plan my Spring 2027 semester: 15-18 credits, no classes before 10:00, I want Machine Learning"
```

The second command calls the model and prints the extracted constraints as JSON.

Run one tool without the model (no API key needed):

```bash
.venv/bin/python -m studypath --student s1001 --tool check_prerequisites --args '{"student_id": "s1001", "course_code": "CSS 320"}'
.venv/bin/python -m studypath --tool validate_plan --args '{"student_id": "s1001", "semester": "Spring 2027", "section_ids": ["CSS202-A", "MAT220-B", "CSS210-A", "CSS230-A", "CSS240-A"]}'
```

## Test

```bash
.venv/bin/python -m pytest -q
```

Tests use a scripted fake model and a stubbed SDK client, so they need no API key and no network.

## Layout

| File | Purpose |
|---|---|
| `config.py` | Limits, default model, `.env` loading |
| `data.py` | Loads and validates the mock data |
| `llm.py` | `LLMClient` interface, `AnthropicClient`, `LLMError` |
| `constraints.py` | Prompt, JSON schema, validation, `extract_constraints` |
| `planning.py` | Progress, prerequisites, conflicts, plan check |
| `tools.py` | `Toolbox`: tool definitions, argument validation, access limit |
| `testing.py` | `ScriptedLLM` fake model for tests |
| `__main__.py` | Command line entry point |

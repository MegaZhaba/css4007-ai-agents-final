# Semester Week 11 Progress Report

## Completed Work

- **Mock university data** (`data/`): 22 courses with prerequisites, 23 sections for Spring 2027, 3 students with transcripts and one degree program. The data contains the situations from the proposal on purpose: a student who wants Machine Learning but has not passed Probability and Statistics, a student with a failed course, sections that overlap, and a full section.
- **Data loader with consistency checks** (`studypath/data.py`): unknown prerequisites, prerequisite cycles, bad section times, over-full sections and unknown courses in transcripts are reported before anything else uses the data.
- **LLM integration** (`studypath/llm.py`): an `LLMClient` interface and `AnthropicClient`, the adapter for Claude through the official Anthropic SDK. It sends the system prompt, messages, tools and a JSON schema for structured output, and returns text, tool calls, stop reason and token usage. API failures (bad key, unknown model, rate limit, server error, network error, refusal, cut-off answer) are converted into one `LLMError` type with a `retryable` flag.
- **Constraint extraction** (`studypath/constraints.py`): user goal → prompt → model → JSON → validation in code → `Constraints`. Every field is checked (types, credit range, 24-hour times, weekdays, semester format, contradictions). A rejected answer is asked again with the reasons, at most `MAX_RETRIES = 2` times, then the run stops with an error.
- **Command line** (`python -m studypath "<goal>"`, `python -m studypath --check-data`) and setup notes in `studypath/README.md`.
- **Tests**: 51 pytest cases, run in GitHub Actions by the new `StudyPath tests` workflow.

## Important Commits

- "Add mock data, Claude client and constraint extraction (Week 11)" — everything listed above plus this report.

## Current Functionality

- `python -m studypath --check-data` loads and validates the mock data.
- `python -m studypath "<goal>"` sends the goal to the model and prints validated constraints as JSON; an empty or over-long goal is rejected before the model is called, and API problems produce a readable error message instead of a traceback.
- Verified so far only with the automated tests: they replace the model with a scripted fake and the SDK with a stub. **A request to the real Claude API has not been run yet**, because no API key is configured on my machine; without a key the program stops with "Set LLM_API_KEY in .env".
- No tools, agent loop or guardrails yet.

## Problems Encountered

- The system Python on my Mac is 3.9, while the current Anthropic SDK needs Python 3.10 or newer.
- Structured output guarantees valid JSON of the right shape, but its schema language cannot express ranges or formats (for example "credits between 1 and 30" or "HH:MM").
- With no credentials, the SDK raised its own exception while the client object was being created, not when the request was sent, so my error handling around the request did not catch it and a test failed.
- When a rejected answer has to be asked again, replaying the model's previous turn is fragile with this model, because its thinking blocks must be sent back unchanged.

## Solutions

- Created a virtual environment with Python 3.12 using `uv`; the dependency is pinned in `requirements.txt` and CI runs on 3.12.
- Kept the JSON schema simple and put all range, format and consistency rules into `validate_constraints`, which reports every problem at once.
- Wrapped client creation as well as the request, so a missing key always gives the same clear `LLMError`; a test covers this.
- Each retry is a fresh single-message request that repeats the goal and lists why the previous answer was rejected, so no earlier model turn has to be replayed.

## What I Learned

- "The model returned JSON" and "the JSON is correct" are different things: structure can be enforced by the API, meaning has to be checked in code.
- Putting the model behind a small interface makes the application testable without a key or network and keeps provider details in one file.
- The user's text should be passed as data (inside `<request>` tags in the user message), separately from the instructions in the system prompt.
- AI assistance disclosure: the code, tests and data in this commit were written with Claude Code (an AI coding assistant).

## Next Week

- Get an API key, run the extraction against the real model on the example requests from the proposal and record the results.
- Implement the read-only tools: `get_student_record`, `get_degree_requirements`, `search_courses`, `get_course_sections`.
- Implement the deterministic checks `check_prerequisites` and `check_schedule_conflicts` with argument validation.
- Add unit tests for every tool and complete `reports/week-12.md`.

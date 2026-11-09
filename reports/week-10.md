# Semester Week 10 Progress Report

## Completed Work

- Read the project README and the A, C and D level requirements.
- Chose level A and the topic: StudyPath, an autonomous academic planning agent.
- Forked the instructor repository and cloned the fork.
- Wrote the project proposal (`reports/proposal.md`): problem, users, functions, LLM tools with permission classes, model choice, architecture, example requests, evaluation plan and weekly milestones.

## Important Commits

- "Add project proposal: StudyPath academic planning agent (A level)" — proposal and this report.

## Current Functionality

No application code yet. The repository contains the completed proposal and the instructor's starter files.

## Problems Encountered

- Choosing between several A-level topics (research assistant, academic planner, data analysis agent).
- The fork and the first push happened at the very start of Week 11 (9 November), so the proposal commit is dated after the Week 10 window.

## Solutions

- Chose the academic planner because its steps really depend on intermediate results (transcript → eligibility → sections → conflicts → replanning) and because it has a natural consequential action (registration) for the human-approval guardrail.
- Decided to use only mock university data so the project has no privacy issues and the tests are reproducible.

## What I Learned

- What separates an A-level agent from a tool-calling assistant: explicit state, replanning, bounded execution and verification of results.
- Guardrails must be enforced in code (allow-list, argument validation, approval gate), not only in the system prompt.

## Next Week

- Create mock data: catalog, timetable, degree requirements and three students.
- Implement the `LLMClient` adapter for the real model and load the key from `.env`.
- Implement constraint extraction from a natural-language goal with JSON schema validation.
- Write the first tests and complete `reports/week-11.md`.

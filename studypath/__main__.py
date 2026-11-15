"""Command line entry point.

    python -m studypath "Plan my Spring 2027 semester, 15-18 credits, no classes before 10:00"
    python -m studypath --check-data
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load_env
from .constraints import ConstraintError, InvalidGoalError, extract_constraints
from .data import DataError, load_dataset
from .llm import AnthropicClient, LLMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studypath", description="StudyPath academic planning agent")
    parser.add_argument("goal", nargs="?", help="planning goal in plain language")
    parser.add_argument("--check-data", action="store_true", help="validate the mock data files and exit")
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset()
    except DataError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.check_data:
        print(
            f"Data OK: {len(dataset.courses)} courses, {len(dataset.sections)} sections, "
            f"{len(dataset.students)} students, {len(dataset.programs)} programs."
        )
        return 0
    if args.goal is None:
        parser.error("a goal is required (or use --check-data)")

    load_env()
    try:
        constraints = extract_constraints(args.goal, AnthropicClient())
    except InvalidGoalError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except (LLMError, ConstraintError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(constraints.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

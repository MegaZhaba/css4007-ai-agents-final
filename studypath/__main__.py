"""Command line entry point.

    python -m studypath "Plan my Spring 2027 semester, 15-18 credits, no classes before 10:00"
    python -m studypath --check-data
    python -m studypath --student s1001 --tool check_prerequisites --args '{"student_id": "s1001", "course_code": "CSS 320"}'
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load_env
from .constraints import ConstraintError, InvalidGoalError, extract_constraints
from .data import DataError, load_dataset
from .llm import AnthropicClient, LLMError
from .tools import Toolbox, ToolError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studypath", description="StudyPath academic planning agent")
    parser.add_argument("goal", nargs="?", help="planning goal in plain language")
    parser.add_argument("--check-data", action="store_true", help="validate the mock data files and exit")
    parser.add_argument("--tool", metavar="NAME", help="run one tool directly, without the model")
    parser.add_argument("--args", default="{}", metavar="JSON", help="arguments for --tool as a JSON object")
    parser.add_argument("--student", default="s1001", metavar="ID", help="student for --tool (default: s1001)")
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
    if args.tool is not None:
        try:
            result = Toolbox(dataset, args.student).invoke(args.tool, json.loads(args.args))
        except json.JSONDecodeError as e:
            print(f"Error: --args is not valid JSON: {e}", file=sys.stderr)
            return 2
        except ToolError as e:
            print(f"Error ({e.code}): {e}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0
    if args.goal is None:
        parser.error("a goal is required (or use --check-data or --tool)")

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

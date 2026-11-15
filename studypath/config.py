"""Settings and limits for StudyPath. Values here are the single place to tune them."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Model used when LLM_MODEL is not set in the environment.
DEFAULT_MODEL = "claude-sonnet-5-5"
# Upper bound for one model answer (includes the model's thinking tokens).
MAX_OUTPUT_TOKENS = 4000

# How many times a rejected model answer may be asked again.
MAX_RETRIES = 2
# Longest goal text accepted from the user.
MAX_GOAL_CHARS = 2000
# Sanity bound for "credits per semester" in a user request.
MAX_CREDITS = 30


def load_env(path: Path | None = None) -> None:
    """Read KEY=VALUE lines from .env into os.environ.

    Variables that are already set win, so a real environment variable is never
    overwritten by the file. The file is git-ignored and must never be committed.
    """
    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value

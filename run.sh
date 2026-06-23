#!/bin/bash
# Wrapper script used by the launchd plist. Edit the python invocation to
# match your setup (system python, uv, pyenv, venv, etc.).
set -euo pipefail

cd "$(dirname "$0")"

# Default strategy is "random". Override via the LAUNCHD_STRATEGY env var or
# by editing this line.
STRATEGY="${LAUNCHD_STRATEGY:-llm}"

# Pick whichever python launcher you have.
if command -v uv >/dev/null 2>&1; then
    exec uv run python main.py --strategy "$STRATEGY" --max-hours-ahead 30
else
    exec python3 main.py --strategy "$STRATEGY" --max-hours-ahead 30
fi

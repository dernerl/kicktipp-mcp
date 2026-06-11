"""Tipping strategies: weighted_random and llm."""

from __future__ import annotations

import json
import math
import os
import random
from typing import Sequence

from kicktipp import Match


SCORE_CAP = 7
HOME_LAMBDA = 1.45
AWAY_LAMBDA = 1.15


def weighted_random_tip() -> tuple[int, int]:
    """Sample a realistic football score using Poisson rates."""
    return (
        min(_poisson_sample(HOME_LAMBDA), SCORE_CAP),
        min(_poisson_sample(AWAY_LAMBDA), SCORE_CAP),
    )


def _poisson_sample(lam: float) -> int:
    # Knuth's algorithm. Fine for the small lambdas we use.
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


# --- LLM strategy ----------------------------------------------------------
#
# Uses the Claude Code CLI (`claude -p ...`) so predictions run under the
# user's Pro subscription instead of the paid API. The CLI inherits the user's
# logged-in session and has WebSearch available by default.


CLAUDE_CLI = os.environ.get("CLAUDE_CLI", "claude")

LLM_PROMPT_TEMPLATE = """You are predicting final scores for these football matches:

{match_list}

Use web search to check current form, recent results, lineups, and injuries before predicting. Be realistic about football — most matches end with low scores (1-1, 1-0, 2-1, 0-0, 2-0). Scores above 4 are rare.

Output exactly one line at the very end of your response: a JSON array with one object per match in the same order as above, like:
[{{"home": 2, "away": 1}}, {{"home": 1, "away": 1}}]

The JSON array MUST be the last thing in your response. Do not add anything after it."""


def llm_tips(matches: Sequence[Match]) -> list[tuple[int, int]]:
    """Predict scores by shelling out to `claude -p` (Pro plan, no API key)."""
    import subprocess

    match_lines = []
    for i, m in enumerate(matches, start=1):
        line = f"{i}. {m.home_team} vs {m.away_team}"
        if m.kickoff is not None:
            line += f" — kickoff {m.kickoff.strftime('%Y-%m-%d %H:%M')}"
        match_lines.append(line)

    prompt = LLM_PROMPT_TEMPLATE.format(match_list="\n".join(match_lines))

    try:
        result = subprocess.run(
            [
                CLAUDE_CLI,
                "-p",
                prompt,
                "--allowed-tools",
                "WebSearch,WebFetch",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"`{CLAUDE_CLI}` not found on PATH. "
            "Install Claude Code or set CLAUDE_CLI to the full binary path."
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Claude CLI exited with status {e.returncode}.\n"
            f"stderr:\n{e.stderr}\nstdout:\n{e.stdout}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Claude CLI timed out after 10 minutes") from e

    return _parse_predictions(result.stdout, expected=len(matches))


def _parse_predictions(text: str, expected: int) -> list[tuple[int, int]]:
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                start = None

    for candidate in reversed(candidates):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list) or len(data) != expected:
            continue
        try:
            tips = [(int(d["home"]), int(d["away"])) for d in data]
        except (KeyError, TypeError, ValueError):
            continue
        if all(0 <= h <= 20 and 0 <= a <= 20 for h, a in tips):
            return tips

    raise RuntimeError(
        f"No JSON array of {expected} predictions found in LLM output:\n{text[:2000]}"
    )

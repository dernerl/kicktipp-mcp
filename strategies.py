"""Tipping strategies: weighted_random and llm."""

from __future__ import annotations

import json
import math
import os
import random
from typing import Sequence

from kicktipp import Match, PastResult, RankingEntry


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


# --- Tournament context builder --------------------------------------------

def build_tournament_context(results: list[PastResult]) -> str:
    """Summarise past results as a compact text block for the LLM prompt."""
    if not results:
        return ""

    # Group by spieltag
    by_spieltag: dict[str, list[PastResult]] = {}
    for r in results:
        by_spieltag.setdefault(r.spieltag_label, []).append(r)

    lines = ["## WM 2026 — bisherige Ergebnisse"]
    for label, matches in by_spieltag.items():
        lines.append(f"\n### {label}")
        for m in matches:
            winner = (
                f"→ {m.home_team} gewinnt"
                if m.home_goals > m.away_goals
                else f"→ {m.away_team} gewinnt"
                if m.away_goals > m.home_goals
                else "→ Unentschieden"
            )
            group = f" [{m.group}]" if m.group else ""
            lines.append(
                f"  {m.home_team} {m.home_goals}:{m.away_goals} {m.away_team}{group}  {winner}"
            )

    # Team form table
    stats: dict[str, dict] = {}
    for r in results:
        for team, gf, ga in [
            (r.home_team, r.home_goals, r.away_goals),
            (r.away_team, r.away_goals, r.home_goals),
        ]:
            s = stats.setdefault(team, {"gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0, "p": 0})
            s["gf"] += gf
            s["ga"] += ga
            if gf > ga:
                s["w"] += 1
                s["p"] += 3
            elif gf == ga:
                s["d"] += 1
                s["p"] += 1
            else:
                s["l"] += 1

    lines.append("\n### Teamform (Tore, Siege/Unentschieden/Niederlagen, Punkte)")
    for team, s in sorted(stats.items(), key=lambda x: -x[1]["p"]):
        lines.append(
            f"  {team}: {s['gf']}:{s['ga']} Tore  "
            f"{s['w']}S/{s['d']}U/{s['l']}N  {s['p']} Pkt"
        )

    return "\n".join(lines)


def build_standing_context(ranking: list[RankingEntry]) -> str:
    """Summarise the current leaderboard so the LLM can calibrate risk.

    Trailing by a lot late in the tournament favors chasing exact scores
    (3 pts) over safe tendency picks (1 pt); leading favors the opposite.
    """
    if not ranking:
        return ""

    self_entry = next((e for e in ranking if e.is_self), None)
    if self_entry is None:
        return ""

    leader = ranking[0]
    by_rank = sorted(ranking, key=lambda e: e.rank)
    ahead = next((e for e in by_rank if e.rank == self_entry.rank - 1), None)
    behind = next((e for e in by_rank if e.rank == self_entry.rank + 1), None)

    lines = [
        "\n## Aktueller Tabellenstand",
        f"  Wir: Platz {self_entry.rank}/{len(ranking)}, {self_entry.points} Punkte",
        f"  Tabellenführer: {leader.player}, {leader.points} Punkte "
        f"({leader.points - self_entry.points} Punkte Rückstand)",
    ]
    if ahead:
        lines.append(
            f"  Platz {ahead.rank} ({ahead.player}): {ahead.points} Punkte "
            f"({ahead.points - self_entry.points} Punkte vor uns)"
        )
    if behind:
        lines.append(
            f"  Platz {behind.rank} ({behind.player}): {behind.points} Punkte "
            f"({self_entry.points - behind.points} Punkte hinter uns)"
        )
    lines.append(
        "  Strategie-Hinweis: bei großem Rückstand lohnen sich riskantere "
        "Tipps auf exakte Ergebnisse (3 Pkt); bei knappem Vorsprung lieber "
        "sichere Tendenz-Tipps (mind. 1 Pkt) bevorzugen."
    )
    return "\n".join(lines)


# --- LLM strategy ----------------------------------------------------------
#
# Uses the Claude Code CLI (`claude -p ...`) so predictions run under the
# user's Pro subscription instead of the paid API. The CLI inherits the user's
# logged-in session and has WebSearch available by default.


CLAUDE_CLI = os.environ.get("CLAUDE_CLI", "claude")

LLM_PROMPT_TEMPLATE = """You are predicting final scores for a Kicktipp competition (German football prediction game).

{tournament_context}
{standing_context}

## Matches to predict
Bookmaker odds (1 = home win, X = draw, 2 = away win) are given inline where
available — use them directly, no need to search for odds separately.
{match_list}

## Scoring system (important for strategy)
- 3 points: exact score correct
- 2 points: correct goal difference (but wrong score)
- 1 point: correct tendency (winner/draw) only
- 0 points: wrong tendency

## Your task
For each match, search the web for:
1. Current injury/suspension news for both teams
2. Recent form (last 3-5 matches)
3. Likely starting lineup or rotation (group stage context: is a team already through?)
4. Head-to-head record if relevant

Then reason about which EXACT score is most likely — not just who wins. Think about:
- Strong favorites (odds < 1.40): most likely win 2:0 or 2:1 — don't fade a heavy
  favorite into a draw or upset just to be different, that has cost us tendency
  points before. Only deviate from the favorite's win when the underlying
  reasoning (injuries, lineup rotation, head-to-head) is genuinely strong.
- Close matches (odds > 1.80 for the favorite): consider 1:1 or 1:0
- Does the score matter for group advancement? Teams already through may rotate and concede more.

Most Kicktipp players will pick the obvious favorite to win 2:0. You score big by finding the correct exact result when it differs from the crowd — but getting the tendency right is worth more than a creative miss, so don't sacrifice the safe 1-2 points chasing a contrarian exact score.

Output exactly one JSON array as the very last line of your response — one object per match in the same order:
[{{"home": 2, "away": 1}}, {{"home": 0, "away": 0}}]

The JSON array MUST be the last thing in your response. Do not add anything after it."""


def llm_tips(
    matches: Sequence[Match],
    past_results: list[PastResult] | None = None,
    ranking: list[RankingEntry] | None = None,
) -> list[tuple[int, int]]:
    """Predict scores by shelling out to `claude -p` (Pro plan, no API key)."""
    import subprocess

    match_lines = []
    for i, m in enumerate(matches, start=1):
        line = f"{i}. {m.home_team} vs {m.away_team}"
        if m.kickoff is not None:
            line += f" — kickoff {m.kickoff.strftime('%Y-%m-%d %H:%M')}"
        if m.odds_home is not None and m.odds_draw is not None and m.odds_away is not None:
            line += f" — Quoten 1:{m.odds_home} X:{m.odds_draw} 2:{m.odds_away}"
        match_lines.append(line)

    tournament_context = build_tournament_context(past_results or [])
    standing_context = build_standing_context(ranking or [])
    prompt = LLM_PROMPT_TEMPLATE.format(
        match_list="\n".join(match_lines),
        tournament_context=tournament_context,
        standing_context=standing_context,
    )

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

    # Only the final JSON array gets used; the reasoning (odds, injuries, form)
    # that led to it would otherwise be lost once parsed - log it so picks can
    # be audited after the fact.
    print("--- Claude reasoning ---")
    print(result.stdout)
    print("--- end Claude reasoning ---")

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

"""MCP server exposing kicktipp tipping to Claude Desktop.

Tools:
- list_open_matches:    matches not yet tipped and not yet started
- list_submitted_tips:  already-tipped matches that haven't kicked off (still editable)
- submit_tips:          submit or overwrite predicted scores
- list_bonus_questions: bonus questions (e.g. "Wer wird Weltmeister?") still open
- submit_bonus_tips:    submit or overwrite bonus-question answers

Configure in claude_desktop_config.json (Claude Desktop -> Settings -> Developer):

    {
      "mcpServers": {
        "kicktipp": {
          "command": "/full/path/to/kicktipp-ai/run-mcp.sh"
        }
      }
    }

Credentials are read from `.env` in this directory (KICKTIPP_EMAIL,
KICKTIPP_PASSWORD, KICKTIPP_COMMUNITY).
"""

from __future__ import annotations

import os
from typing import Annotated

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from kicktipp import (
    KicktippClient,
    LoginFailed,
    RankingEntry,
    TippabgabePage,
    assign_global_indices,
    editable_matches,
    open_bonus_questions,
    tippable_matches,
)


load_dotenv()

EMAIL = os.environ.get("KICKTIPP_EMAIL")
PASSWORD = os.environ.get("KICKTIPP_PASSWORD")
COMMUNITY = os.environ.get("KICKTIPP_COMMUNITY")


mcp = FastMCP("kicktipp")


def _client() -> KicktippClient:
    if not (EMAIL and PASSWORD and COMMUNITY):
        raise RuntimeError(
            "KICKTIPP_EMAIL, KICKTIPP_PASSWORD, and KICKTIPP_COMMUNITY must be set "
            "in the .env file in the kicktipp-ai project directory."
        )
    client = KicktippClient(EMAIL, PASSWORD, COMMUNITY)
    try:
        client.login()
    except LoginFailed as e:
        raise RuntimeError(f"kicktipp login failed: {e}") from e
    return client


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OpenMatch(BaseModel):
    index: int = Field(description="Pass this back to submit_tips")
    spieltag: str = Field(description="e.g. '1. Spieltag'")
    home_team: str
    away_team: str
    kickoff: str | None = Field(description="ISO-8601 kickoff time, or null if unknown")
    odds_home: float | None = Field(
        default=None,
        description="Bookmaker odds for '1' (home win); null if no odds available",
    )
    odds_draw: float | None = Field(
        default=None,
        description="Bookmaker odds for 'X' (draw); null if no odds available",
    )
    odds_away: float | None = Field(
        default=None,
        description="Bookmaker odds for '2' (away win); null if no odds available",
    )


class SubmittedTip(BaseModel):
    index: int = Field(description="Pass this back to submit_tips to overwrite")
    spieltag: str = Field(description="e.g. '1. Spieltag'")
    home_team: str
    away_team: str
    home_score: int = Field(description="Currently tipped home goals")
    away_score: int = Field(description="Currently tipped away goals")
    kickoff: str | None = Field(description="ISO-8601 kickoff time, or null if unknown")


class TipInput(BaseModel):
    index: int = Field(description="The index from list_open_matches or list_submitted_tips")
    home: int = Field(ge=0, le=20, description="Predicted home team goals")
    away: int = Field(ge=0, le=20, description="Predicted away team goals")


class BonusQuestionOut(BaseModel):
    index: int = Field(description="Pass this back to submit_bonus_tips")
    question: str = Field(description="e.g. 'Wer wird Weltmeister?'")
    deadline: str | None = Field(description="ISO-8601 tip deadline, or null if unknown")
    answers_needed: int = Field(description="How many answers this question requires")
    options: list[str] = Field(description="Valid answer options")
    current_answers: list[str] = Field(
        description="Currently tipped answers (empty if not tipped yet)"
    )


class RankingEntryOut(BaseModel):
    rank: int
    player: str
    points: int
    tendency_points: int | None = None
    difference_points: int | None = None
    exact_points: int | None = None


class BonusTipInput(BaseModel):
    index: int = Field(description="The index from list_bonus_questions")
    answers: list[str] = Field(
        description="Chosen options, exactly answers_needed of them, by option text"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_open_matches() -> list[OpenMatch]:
    """List kicktipp matches that still need a tip and have not kicked off yet.

    Fetches all Spieltage.  Returns each match with an `index` and `spieltag`
    label, plus bookmaker odds (`odds_home`/`odds_draw`/`odds_away` for 1/X/2)
    when kicktipp shows them.  Pass the `index` to `submit_tips` to add a tip.
    Matches already tipped or already started are excluded.
    """
    client = _client()
    pages = client.fetch_all_editable()
    assign_global_indices(pages)

    out: list[OpenMatch] = []
    for page in pages:
        for m in tippable_matches(page.matches):
            out.append(OpenMatch(
                index=m.index,
                spieltag=m.spieltag_label,
                home_team=m.home_team,
                away_team=m.away_team,
                kickoff=m.kickoff.isoformat() if m.kickoff else None,
                odds_home=m.odds_home,
                odds_draw=m.odds_draw,
                odds_away=m.odds_away,
            ))
    return out


@mcp.tool()
def list_submitted_tips() -> list[SubmittedTip]:
    """List kicktipp matches that already have a tip but haven't kicked off yet.

    These tips can still be changed — pass the `index` to `submit_tips` with
    new scores to overwrite.  Matches that have already kicked off are excluded
    (those tips are locked in).
    """
    client = _client()
    pages = client.fetch_all_editable()
    assign_global_indices(pages)

    out: list[SubmittedTip] = []
    for page in pages:
        for m in editable_matches(page.matches):
            if not m.already_tipped:
                continue
            if m.home_score is None or m.away_score is None:
                continue
            out.append(SubmittedTip(
                index=m.index,
                spieltag=m.spieltag_label,
                home_team=m.home_team,
                away_team=m.away_team,
                home_score=m.home_score,
                away_score=m.away_score,
                kickoff=m.kickoff.isoformat() if m.kickoff else None,
            ))
    return out


@mcp.tool()
def submit_tips(
    tips: Annotated[list[TipInput], Field(description="Tips to submit, one per match")],
) -> str:
    """Submit or overwrite predicted scores on kicktipp.

    Works for both new tips (from list_open_matches) and overwriting existing
    ones (from list_submitted_tips), as long as the match hasn't kicked off.

    Re-fetches each Spieltag's form before submitting to pick up fresh hidden
    fields, then posts all tips for a Spieltag in a single request.
    """
    if not tips:
        return "No tips provided."

    client = _client()

    # Re-fetch the full editable picture to get fresh form state.
    pages = client.fetch_all_editable()
    assign_global_indices(pages)

    # Build a global index → (page, match) lookup.
    index_to_entry: dict[int, tuple[TippabgabePage, object]] = {}
    for page in pages:
        for m in page.matches:
            index_to_entry[m.index] = (page, m)

    page_by_st: dict[int, TippabgabePage] = {p.spieltag_index: p for p in pages}
    by_page: dict[int, dict[int, tuple[int, int]]] = {}
    skipped: list[int] = []

    for t in tips:
        entry = index_to_entry.get(t.index)
        if entry is None:
            skipped.append(t.index)
            continue
        page, match = entry
        # Accept any match that hasn't kicked off yet (tipped or not).
        if match not in editable_matches(page.matches):
            skipped.append(t.index)
            continue
        by_page.setdefault(page.spieltag_index, {})[t.index] = (t.home, t.away)

    if not by_page:
        return (
            f"Nothing submitted — no indices matched editable matches "
            f"(skipped: {skipped})."
        )

    summary_lines: list[str] = []
    for st_idx, tips_map in sorted(by_page.items()):
        page = page_by_st[st_idx]
        client.submit_tips(page, tips_map)

        by_idx = {m.index: m for m in page.matches}
        for idx, (h, a) in tips_map.items():
            m = by_idx.get(idx)
            if m is not None:
                verb = "updated" if m.already_tipped else "submitted"
                summary_lines.append(
                    f"  [{m.spieltag_label}] {m.home_team} {h} : {a} {m.away_team}"
                    + (f"  (was {m.home_score}:{m.away_score})" if m.already_tipped else "")
                )

    msg = (
        f"Submitted {sum(len(v) for v in by_page.values())} tip(s):\n"
        + "\n".join(summary_lines)
    )
    if skipped:
        msg += f"\n\nSkipped (not found / already kicked off): {skipped}"
    return msg


@mcp.tool()
def get_ranking() -> list[RankingEntryOut]:
    """Return the current overall standings (Gesamtübersicht) for this Tipprunde.

    Shows each player's rank, name, and points.  Call this to check your
    position and see how far ahead or behind the competition you are.
    """
    client = _client()
    entries = client.fetch_ranking()
    return [
        RankingEntryOut(
            rank=e.rank,
            player=e.player,
            points=e.points,
            tendency_points=e.tendency_points,
            difference_points=e.difference_points,
            exact_points=e.exact_points,
        )
        for e in entries
    ]


@mcp.tool()
def list_bonus_questions() -> list[BonusQuestionOut]:
    """List kicktipp bonus questions whose deadline hasn't passed.

    Bonus questions are things like "Wer wird Weltmeister?" or "Wer gewinnt
    die Gruppe A?".  Each question needs `answers_needed` answers chosen from
    `options`.  Pass the `index` to submit_bonus_tips to tip or overwrite.
    """
    client = _client()
    page = client.fetch_bonus_page()
    if page is None:
        return []

    out: list[BonusQuestionOut] = []
    for q in open_bonus_questions(page.questions):
        out.append(BonusQuestionOut(
            index=q.index,
            question=q.question,
            deadline=q.deadline.isoformat() if q.deadline else None,
            answers_needed=len(q.selects),
            options=sorted(q.selects[0].options),
            current_answers=[s.current for s in q.selects if s.current],
        ))
    return out


@mcp.tool()
def submit_bonus_tips(
    tips: Annotated[list[BonusTipInput], Field(description="Bonus tips, one per question")],
) -> str:
    """Submit or overwrite bonus-question answers on kicktipp.

    Each tip needs exactly `answers_needed` answers (option texts) for its
    question.  Questions not included keep their current answers.  Re-fetches
    the bonus page before submitting to pick up fresh form state.
    """
    if not tips:
        return "No tips provided."

    client = _client()
    page = client.fetch_bonus_page()
    if page is None:
        return "No bonus questions found in this Tipprunde."

    open_indices = {q.index for q in open_bonus_questions(page.questions)}
    answers_by_index: dict[int, list[str]] = {}
    skipped: list[int] = []
    for t in tips:
        if t.index in open_indices:
            answers_by_index[t.index] = t.answers
        else:
            skipped.append(t.index)

    if not answers_by_index:
        return f"Nothing submitted — no open questions matched (skipped: {skipped})."

    try:
        client.submit_bonus_tips(page, answers_by_index)
    except ValueError as e:
        return f"Nothing submitted — {e}"

    by_index = {q.index: q for q in page.questions}
    summary_lines = [
        f"  {by_index[idx].question} -> {', '.join(answers)}"
        for idx, answers in sorted(answers_by_index.items())
    ]
    msg = f"Submitted {len(answers_by_index)} bonus tip(s):\n" + "\n".join(summary_lines)
    if skipped:
        msg += f"\n\nSkipped (not found / deadline passed): {skipped}"
    return msg


if __name__ == "__main__":
    mcp.run()

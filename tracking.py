"""Structured history of bot tips vs. actual results, for performance tracking.

Kicktipp doesn't expose "my tip vs. result" anywhere after a match has kicked
off, so this is the only way to know whether the bot is actually any good.
Each submitted tip is appended to data/tips_history.jsonl; update_scores()
fills in the real result + points once a match completes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from kicktipp import Match, PastResult

HISTORY_PATH = Path(__file__).parent / "data" / "tips_history.jsonl"


@dataclass
class TipRecord:
    timestamp: str
    strategy: str
    spieltag: str
    home_team: str
    away_team: str
    home_tip: int
    away_tip: int
    kickoff: str | None
    home_result: int | None = None
    away_result: int | None = None
    points: int | None = None


def record_tips(matches: list[Match], tips: list[tuple[int, int]], strategy: str) -> None:
    """Append newly submitted tips to the history file."""
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        for m, (h, a) in zip(matches, tips):
            rec = TipRecord(
                timestamp=now,
                strategy=strategy,
                spieltag=m.spieltag_label,
                home_team=m.home_team,
                away_team=m.away_team,
                home_tip=h,
                away_tip=a,
                kickoff=m.kickoff.isoformat() if m.kickoff else None,
            )
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def _points(h_tip: int, a_tip: int, h_res: int, a_res: int) -> int:
    if h_tip == h_res and a_tip == a_res:
        return 4                                   # exakt
    diff_tip = h_tip - a_tip
    diff_res = h_res - a_res
    tendency_tip = (diff_tip > 0) - (diff_tip < 0)
    tendency_res = (diff_res > 0) - (diff_res < 0)
    if tendency_tip != tendency_res:
        return 0                                   # falsche Tendenz
    # Richtige Tordifferenz nur bei Nicht-Remis = 3; Remis (diff==0) gibt nur 2.
    return 3 if (diff_tip == diff_res and diff_res != 0) else 2


def update_scores(past_results: list[PastResult]) -> dict:
    """Fill in points for history entries whose match has since completed.

    Returns a summary: newly_scored count, totals, and a breakdown by strategy.
    """
    if not HISTORY_PATH.exists():
        return {}

    res_by_pair = {(r.home_team, r.away_team): r for r in past_results}

    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]

    newly_scored = 0
    for rec in records:
        if rec.get("points") is not None:
            continue
        r = res_by_pair.get((rec["home_team"], rec["away_team"]))
        if r is None:
            continue
        rec["home_result"] = r.home_goals
        rec["away_result"] = r.away_goals
        rec["points"] = _points(rec["home_tip"], rec["away_tip"], r.home_goals, r.away_goals)
        newly_scored += 1

    if newly_scored:
        with HISTORY_PATH.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    scored = [r for r in records if r.get("points") is not None]
    by_strategy: dict[str, dict] = {}
    for r in scored:
        s = by_strategy.setdefault(r["strategy"], {"matches": 0, "points": 0})
        s["matches"] += 1
        s["points"] += r["points"]

    return {
        "newly_scored": newly_scored,
        "total_points": sum(r["points"] for r in scored),
        "total_matches": len(scored),
        "by_strategy": by_strategy,
    }

"""Forward-only snapshots of bookmaker odds (1/X/2) for still-open matches.

Kicktipp only shows odds on the Tippabgabe page for matches that have not yet
kicked off; the historical tippuebersicht carries none, so odds can never be
fetched retroactively. This module therefore captures odds going forward: each
bot run upserts the current odds of every still-open match into
data/odds_history.jsonl. While a match stays open its row is overwritten with
the latest odds, so the stored value ends up as close to kickoff as the last
run before it started. Already-started (or vanished) matches keep their last
snapshot untouched.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from kicktipp import Match

HISTORY_PATH = Path(__file__).parent / "data" / "odds_history.jsonl"


@dataclass
class OddsSnapshot:
    captured_at: str
    spieltag_index: int
    spieltag_label: str
    home_team: str
    away_team: str
    kickoff: str | None
    odds_home: float | None
    odds_draw: float | None
    odds_away: float | None


def _key(rec: dict) -> tuple[int, str, str]:
    """Upsert key: one row per match."""
    return (rec["spieltag_index"], rec["home_team"], rec["away_team"])


def record_odds(matches: Iterable[Match]) -> int:
    """Upsert odds snapshots for open matches that currently expose odds.

    Key = (spieltag_index, home_team, away_team). For each match with at least
    one odd, the existing row is overwritten with the fresher snapshot (keeping
    the recorded odds as close to kickoff as the most recent run), or a new row
    is appended. Matches without any odds are skipped, and rows for matches not
    in this run (already kicked off) are preserved as-is.

    Returns the number of matches snapshotted this run.
    """
    now = datetime.now().isoformat(timespec="seconds")
    snapshots = [
        OddsSnapshot(
            captured_at=now,
            spieltag_index=m.spieltag_index,
            spieltag_label=m.spieltag_label,
            home_team=m.home_team,
            away_team=m.away_team,
            kickoff=m.kickoff.isoformat() if m.kickoff else None,
            odds_home=m.odds_home,
            odds_draw=m.odds_draw,
            odds_away=m.odds_away,
        )
        for m in matches
        if not (m.odds_home is None and m.odds_draw is None and m.odds_away is None)
    ]

    if not snapshots:
        return 0

    HISTORY_PATH.parent.mkdir(exist_ok=True)

    # Load existing rows, preserving file order, keyed for upsert.
    existing: dict[tuple[int, str, str], dict] = {}
    order: list[tuple[int, str, str]] = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            k = _key(rec)
            if k not in existing:
                order.append(k)
            existing[k] = rec

    for snap in snapshots:
        rec = asdict(snap)
        k = _key(rec)
        if k not in existing:
            order.append(k)
        existing[k] = rec

    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        for k in order:
            f.write(json.dumps(existing[k], ensure_ascii=False) + "\n")

    return len(snapshots)

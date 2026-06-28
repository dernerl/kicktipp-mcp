"""Snapshots of bookmaker odds (1/X/2) per match in data/odds_history.jsonl.

Each bot run upserts the current odds of every still-open match (`record_odds`).
Kicktipp also keeps showing the ODDSET odds on the Tippabgabe page for *already
played* Spieltage, so `backfill_odds` can pull the real historical odds in one
go — no external source or web scraping needed.

Upsert key = (spieltag_index, home_team, away_team): a match's row is overwritten
with a fresher forward snapshot while it stays open; the backfill only fills rows
that don't exist yet, so live-captured odds are never clobbered.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from kicktipp import KicktippClient, Match

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


def backfill_odds(client: KicktippClient) -> dict:
    """Backfill real Kicktipp/ODDSET odds for every Spieltag (incl. played ones).

    Scrapes the Tippabgabe pages via `client.fetch_all_odds()` and adds a row for
    every match that doesn't have one yet (key = spieltag_index, home, away).
    Existing rows — e.g. forward-captured pre-kickoff snapshots — are kept as-is.
    New rows are tagged `source: "kicktipp-backfill"`. Returns a small summary.
    """
    scraped = client.fetch_all_odds()
    HISTORY_PATH.parent.mkdir(exist_ok=True)

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

    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    for s in scraped:
        if s["odds_home"] is None and s["odds_draw"] is None and s["odds_away"] is None:
            continue
        k = (s["spieltag_index"], s["home_team"], s["away_team"])
        if k in existing:
            continue  # don't clobber a (forward-captured) row
        existing[k] = {"captured_at": now, **s, "source": "kicktipp-backfill"}
        order.append(k)
        added += 1

    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        for k in order:
            f.write(json.dumps(existing[k], ensure_ascii=False) + "\n")

    return {"scraped": len(scraped), "added": added, "total": len(order)}


def main() -> None:
    import argparse
    import os

    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="Bookmaker-odds history utilities.")
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill real ODDSET odds for all Spieltage from Kicktipp.")
    args = parser.parse_args()
    if not args.backfill:
        parser.error("nothing to do — pass --backfill")

    load_dotenv()
    client = KicktippClient(
        os.environ["KICKTIPP_EMAIL"],
        os.environ["KICKTIPP_PASSWORD"],
        os.environ["KICKTIPP_COMMUNITY"],
    )
    client.login()
    summary = backfill_odds(client)
    print(f"Backfill: scraped {summary['scraped']} matches, added {summary['added']} new "
          f"row(s), {summary['total']} total → {HISTORY_PATH.name}")


if __name__ == "__main__":
    main()

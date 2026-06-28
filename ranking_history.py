"""Reconstruct the community standings — per Spieltag *and* per single match.

Kicktipp never persists historical standings, but each per-Spieltag Tippübersicht
page carries every player's cumulative Gesamtpunkte plus the points they earned in
each individual match.  From that we rebuild two views and write them to data/:

  * ranking_history.jsonl — one row per (Spieltag × player): the standing after
    that Spieltag.  Used for the personal section's "current rank".
  * ranking_steps.jsonl   — one row per (step × player), where a *step* is the
    state after a single match (plus a step 0 for the pre-tournament bonus
    questions).  This is what lets the dashboard scrub the table forward
    match-by-match instead of only once per Spieltag.

Both are derived from a single scrape pass and the file is rewritten each run.

    uv run python ranking_history.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from kicktipp import KicktippClient, SpieltagDetail

DATA_DIR = Path(__file__).parent / "data"
HISTORY_PATH = DATA_DIR / "ranking_history.jsonl"
STEPS_PATH = DATA_DIR / "ranking_steps.jsonl"
COMMUNITY_TIPS_PATH = DATA_DIR / "community_tips.jsonl"


def _ranked(totals: dict[str, int]) -> dict[str, int]:
    """Standard competition ranking (1,2,2,4) by points desc, as Kicktipp does."""
    ranks = {}
    for player, pts in totals.items():
        ranks[player] = 1 + sum(1 for o in totals.values() if o > pts)
    return ranks


def build_history_rows(details: list[SpieltagDetail]) -> list[dict]:
    rows = []
    for d in details:
        for p in d.players:
            rows.append({
                "spieltag_index": d.spieltag_index,
                "spieltag_label": d.spieltag_label,
                "rank": p.rank,
                "player": p.player,
                "points": p.total,
                "is_self": p.is_self,
            })
    return rows


def build_step_rows(details: list[SpieltagDetail]) -> list[dict]:
    """Expand the per-match points into a cumulative, ranked timeline.

    Gesamtpunkte = bonus (credited once, before Spieltag 1) + Σ match points, so
    the bonus is recovered from the first Spieltag and used as everyone's
    starting total.  Each subsequent match advances one player-set of points.
    """
    details = sorted(details, key=lambda d: d.spieltag_index)
    if not details:
        return []

    first = details[0]
    bonus = {p.player: p.total - sum(p.per_match) for p in first.players}
    is_self = {p.player: p.is_self for d in details for p in d.players}
    running = dict(bonus)

    rows: list[dict] = []

    def emit(ordinal, st_idx, st_label, match_index, match):
        totals = dict(running)
        ranks = _ranked(totals)
        for player, pts in totals.items():
            rows.append({
                "ordinal": ordinal,
                "spieltag_index": st_idx,
                "spieltag_label": st_label,
                "match_index": match_index,
                "home": match["home"] if match else None,
                "away": match["away"] if match else None,
                "result": (f"{match['home_goals']}:{match['away_goals']}"
                           if match and match["home_goals"] is not None else None),
                "player": player,
                "points": pts,
                "bonus": bonus.get(player, 0),
                "rank": ranks[player],
                "is_self": is_self.get(player, False),
            })

    # Step 0: pre-tournament standings from the bonus questions.
    ordinal = 0
    emit(ordinal, 0, "Bonusfragen", -1, None)

    for d in details:
        for mi, match in enumerate(d.matches):
            if match["home_goals"] is None:        # not played yet → no step
                continue
            for p in d.players:
                if mi < len(p.per_match):
                    running[p.player] = running.get(p.player, 0) + p.per_match[mi]
            ordinal += 1
            emit(ordinal, d.spieltag_index, d.spieltag_label, mi, match)

    return rows


def build_community_tips(details: list[SpieltagDetail]) -> list[dict]:
    """Every player's tip for every finished match, with the Kicktipp points.

    Powers the community-wide "verrückte Tipps" view (all 12 players, not just
    the bot).  Matches without a result and players who didn't tip are skipped.
    """
    rows = []
    for d in details:
        for mi, match in enumerate(d.matches):
            if match["home_goals"] is None:
                continue
            for p in d.players:
                tip = p.per_match_tips[mi] if mi < len(p.per_match_tips) else None
                if tip is None:
                    continue
                rows.append({
                    "spieltag_index": d.spieltag_index,
                    "spieltag_label": d.spieltag_label,
                    "home": match["home"],
                    "away": match["away"],
                    "home_goals": match["home_goals"],
                    "away_goals": match["away_goals"],
                    "player": p.player,
                    "is_self": p.is_self,
                    "home_tip": tip[0],
                    "away_tip": tip[1],
                    "points": p.per_match[mi] if mi < len(p.per_match) else 0,
                })
    return rows


def build_ranking_history(client: KicktippClient) -> tuple[int, int, int]:
    details = client.fetch_spieltag_details()
    DATA_DIR.mkdir(exist_ok=True)

    def _write(path, rows):
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    history = build_history_rows(details)
    steps = build_step_rows(details)
    community = build_community_tips(details)
    _write(HISTORY_PATH, history)
    _write(STEPS_PATH, steps)
    _write(COMMUNITY_TIPS_PATH, community)

    return len(history), len(steps), len(community)


def main() -> None:
    load_dotenv()
    email = os.environ.get("KICKTIPP_EMAIL")
    password = os.environ.get("KICKTIPP_PASSWORD")
    community = os.environ.get("KICKTIPP_COMMUNITY")
    missing = [k for k, v in (
        ("KICKTIPP_EMAIL", email),
        ("KICKTIPP_PASSWORD", password),
        ("KICKTIPP_COMMUNITY", community),
    ) if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)} (see .env.example)")

    client = KicktippClient(email, password, community)
    client.login()
    n_hist, n_steps, n_comm = build_ranking_history(client)
    n_ordinals = len({json.loads(l)["ordinal"]
                      for l in STEPS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()})
    print(f"Wrote {n_hist} Spieltag rows → {HISTORY_PATH.name}")
    print(f"Wrote {n_steps} step rows across {n_ordinals} match-steps → {STEPS_PATH.name}")
    print(f"Wrote {n_comm} community tips → {COMMUNITY_TIPS_PATH.name}")


if __name__ == "__main__":
    main()

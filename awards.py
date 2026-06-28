"""Community-wide season awards ("Trophäenschrank") for the dashboard.

Every player in the Tippkreis can earn medals based on their full-season record.
All inputs already exist as jsonl — no new scraping. We deliberately *reuse* the
craziness classification from ``dashboard.py`` (``_score_crazy_row``) so a
"Wahnsinns-Treffer" means exactly the same thing here as in the crazy-tips
section, rather than inventing a second, drifting definition.

The scoring path (``tracking._points``, 4/3/2/0) is never touched here; the
``points`` already stored per community tip are used as-is. See ADR 0008.

Design choices (solo-owner defaults, see tasks/todo-auszeichnungen.md):
  * rate-based awards require a minimum participation N = ceil(0.5 * max tips),
    so a player with a handful of tips can't win "Effizienz-Bestie";
  * ties name every winner ("A & B"); the runner-up is the next distinct value
    group's alphabetically-first player;
  * the whole season is considered (no Spieltag slider in v1);
  * exactly one tongue-in-cheek negative award (🤡 Schuss in den Ofen).
"""

from __future__ import annotations

import math
from collections import defaultdict

# Reuse the dashboard's readers + craziness classifier. dashboard.py has no
# import-time side effects (the server only starts in main()), and build_payload
# imports build_awards lazily, so there is no import cycle.
from dashboard import (
    COMMUNITY_TIPS_PATH,
    RANKING_PATH,
    _load_odds,
    _read_jsonl,
    _score_crazy_row,
    _sign,
)

# Craziness threshold (0..2 scale in _score_crazy_row) above which an exact hit
# counts as a genuine "Wahnsinns-Treffer" / a miss as a real "Rohrkrepierer".
CRAZY_THRESHOLD = 1.0


def _per_player_stats() -> tuple[dict, str | None]:
    """Aggregate per-player season stats from community_tips (+ odds for craziness).

    Returns (stats_by_player, self_player). Each stats entry holds plain counts:
    tips, exact, zero, draws_hit, points, crazy_exact, bold_miss — plus the
    per-Spieltag points needed for the Spieltagskönig tally.
    """
    rows = _read_jsonl(COMMUNITY_TIPS_PATH)
    odds_map = _load_odds()

    stats: dict[str, dict] = defaultdict(lambda: {
        "tips": 0, "exact": 0, "zero": 0, "draws_hit": 0, "points": 0,
        "crazy_exact": 0, "bold_miss": 0, "is_self": False,
        "by_spieltag": defaultdict(int),
    })
    self_player: str | None = None

    by_match: dict[tuple, list[dict]] = defaultdict(list)
    for t in rows:
        by_match[(t["spieltag_index"], t["home"], t["away"])].append(t)

    for (st_idx, home, away), tips in by_match.items():
        n = len(tips)
        h, a = tips[0]["home_goals"], tips[0]["away_goals"]
        res_sign = _sign(h - a)
        n_exact = sum(1 for t in tips if t["home_tip"] == h and t["away_tip"] == a)
        n_tend = sum(1 for t in tips if _sign(t["home_tip"] - t["away_tip"]) == res_sign)
        odds_entry = odds_map.get((st_idx, home, away))

        for t in tips:
            p = t["player"]
            s = stats[p]
            s["tips"] += 1
            s["points"] += t.get("points") or 0
            s["by_spieltag"][st_idx] += t.get("points") or 0
            if t.get("is_self"):
                s["is_self"] = True
                self_player = p
            ht, at = t["home_tip"], t["away_tip"]
            if ht == h and at == a:
                s["exact"] += 1
            if (t.get("points") or 0) == 0:
                s["zero"] += 1
            if ht == at and h == a:  # tipped a draw and it was a draw
                s["draws_hit"] += 1

            scored = _score_crazy_row(t, n, n_exact, n_tend, odds_entry)
            if scored and scored["craziness"] >= CRAZY_THRESHOLD:
                if scored["status"] == "exact":
                    s["crazy_exact"] += 1
                elif scored["status"] == "miss":
                    s["bold_miss"] += 1

    return stats, self_player


def _spieltag_wins(stats: dict) -> dict[str, int]:
    """Count Spieltag wins (top points on a Spieltag; shared on a tie)."""
    spieltage: dict[int, dict[str, int]] = defaultdict(dict)
    for player, s in stats.items():
        for st_idx, pts in s["by_spieltag"].items():
            spieltage[st_idx][player] = pts
    wins: dict[str, int] = defaultdict(int)
    for st_idx, by_player in spieltage.items():
        if not by_player:
            continue
        best = max(by_player.values())
        for player, pts in by_player.items():
            if pts == best:
                wins[player] += 1
    return wins


def _rank1_counts() -> dict[str, int]:
    """How many Spieltag-standings each player topped (ranking_history rank==1)."""
    counts: dict[str, int] = defaultdict(int)
    for r in _read_jsonl(RANKING_PATH):
        if r.get("rank") == 1:
            counts[r["player"]] += 1
    return counts


def _top(scores: dict[str, float], stats: dict, *, higher: bool = True,
         eligible: set[str] | None = None) -> tuple[list[str], float, dict | None] | None:
    """Pick winner(s) + runner-up from a player→score map.

    Returns (winners, best_value, runner_up) where winners is every player tied
    for best (alphabetical) and runner_up is {"players", "value"} for the next
    distinct value group — or None. Returns None when nothing is eligible.
    Float scores are rounded to 3 dp before comparison so ties are stable.
    """
    items = [(p, round(float(v), 3)) for p, v in scores.items()
             if (eligible is None or p in eligible)]
    if not items:
        return None
    items.sort(key=lambda x: (-x[1] if higher else x[1], x[0]))
    best = items[0][1]
    winners = sorted(p for p, v in items if v == best)
    runner_up = None
    rest = [(p, v) for p, v in items if v != best]
    if rest:
        ru_val = rest[0][1]
        ru_players = sorted(p for p, v in rest if v == ru_val)
        runner_up = {"players": ru_players, "value": ru_val}
    return winners, best, runner_up


def _card(award: dict, picked, stats: dict, fmt) -> dict | None:
    """Turn a _top() result into a frontend award card via a value formatter."""
    if picked is None:
        return None
    winners, best, runner_up = picked
    is_self = any(stats.get(w, {}).get("is_self") for w in winners)
    card = {
        "id": award["id"], "emoji": award["emoji"], "title": award["title"],
        "desc": award["desc"],
        "winner": " & ".join(winners), "value": fmt(best),
        "is_self": is_self,
        "runner_up": None,
    }
    if runner_up:
        card["runner_up"] = {
            "player": " & ".join(runner_up["players"]),
            "value": fmt(runner_up["value"]),
        }
    return card


def build_awards() -> list[dict]:
    """Compute the full medal grid. One card per award, winner(s) + runner-up."""
    stats, _self = _per_player_stats()
    if not stats:
        return []

    max_tips = max(s["tips"] for s in stats.values())
    min_n = math.ceil(0.5 * max_tips)
    eligible_n = {p for p, s in stats.items() if s["tips"] >= min_n}

    def col(key):
        return {p: s[key] for p, s in stats.items()}

    cards: list[dict] = []

    def add(award, picked, fmt):
        c = _card(award, picked, stats, fmt)
        if c:
            cards.append(c)

    # 🃏 most genuine Wahnsinns-Treffer (exact hits on unlikely outcomes)
    add({"id": "crazy_bird", "emoji": "🃏", "title": "Verrückter Vogel",
         "desc": "Meiste Wahnsinns-Treffer (exakt auf krasse Außenseiter)"},
        _top(col("crazy_exact"), stats),
        lambda v: f"{int(v)} Treffer")

    # 🎯 most exact scores
    add({"id": "sniper", "emoji": "🎯", "title": "Scharfschütze",
         "desc": "Meiste exakte Ergebnisse (4 Punkte)"},
        _top(col("exact"), stats),
        lambda v: f"{int(v)}× exakt")

    # 🔫 most tips submitted (participation)
    add({"id": "rapid_fire", "emoji": "🔫", "title": "Dauerfeuer",
         "desc": "Meiste abgegebene Tipps"},
        _top(col("tips"), stats),
        lambda v: f"{int(v)} Tipps")

    # 👑 most Spieltag wins
    add({"id": "matchday_king", "emoji": "👑", "title": "Spieltagskönig",
         "desc": "Meiste Spieltagssiege (bester Spieltag-Punktwert)"},
        _top(_spieltag_wins(stats), stats),
        lambda v: f"{int(v)} Spieltage")

    # 🥇 most Spieltage on rank 1
    rank1 = _rank1_counts()
    if rank1:
        add({"id": "throne", "emoji": "🥇", "title": "Dauergast an der Spitze",
             "desc": "Meiste Spieltage auf Tabellenplatz 1"},
            _top(rank1, stats),
            lambda v: f"{int(v)}× Platz 1")

    # 💪 fewest zero-point tips (min participation)
    add({"id": "ironclad", "emoji": "💪", "title": "Eisern",
         "desc": f"Wenigste Nuller-Tipps (≥ {min_n} Tipps)"},
        _top(col("zero"), stats, higher=False, eligible=eligible_n),
        lambda v: f"nur {int(v)} Nuller")

    # ⚡ highest points-per-tip average (min participation)
    avg = {p: (s["points"] / s["tips"]) for p, s in stats.items() if s["tips"]}
    add({"id": "efficiency", "emoji": "⚡", "title": "Effizienz-Bestie",
         "desc": f"Höchster Punkteschnitt pro Tipp (≥ {min_n} Tipps)"},
        _top(avg, stats, eligible=eligible_n),
        lambda v: f"Ø {v:.2f}")

    # 🤝 most correctly-tipped draws
    add({"id": "draw_whisperer", "emoji": "🤝", "title": "Remis-Riecher",
         "desc": "Meiste korrekt getippte Unentschieden"},
        _top(col("draws_hit"), stats),
        lambda v: f"{int(v)} Remis")

    # 🤡 most bold misses (backed a clear favorite that lost) — the fun negative
    add({"id": "into_the_oven", "emoji": "🤡", "title": "Schuss in den Ofen",
         "desc": "Meiste klare Favoriten getippt, die dann verloren"},
        _top(col("bold_miss"), stats),
        lambda v: f"{int(v)} Rohrkrepierer")

    return cards


if __name__ == "__main__":
    import json
    for c in build_awards():
        ru = f"  (RU: {c['runner_up']['player']} {c['runner_up']['value']})" if c["runner_up"] else ""
        star = " ⭐BOT" if c["is_self"] else ""
        print(f"{c['emoji']} {c['title']:24s} {c['winner']:18s} {c['value']:16s}{ru}{star}")

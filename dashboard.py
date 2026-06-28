"""Local dashboard for the kicktipp bot's results.

A zero-dependency (stdlib only) web server that visualises:

  * the community's position-over-time (bump chart with a Spieltag slider),
    reconstructed from data/ranking_history.jsonl,
  * "crazy" tips — exact hits on lopsided scores and total tendency misses,
    colour-coded, from data/tips_history.jsonl, and
  * a personal section listing every bot tip, whether it came true, and the
    Claude reasoning behind the llm picks (parsed from the launchd log).

    uv run python dashboard.py            # → http://localhost:8765

Re-runs ranking_history.py lazily on /api/refresh so the standings can be
refreshed without restarting the server.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from logparse import parse_log

ROOT = Path(__file__).parent
TIPS_PATH = ROOT / "data" / "tips_history.jsonl"
RANKING_PATH = ROOT / "data" / "ranking_history.jsonl"
STEPS_PATH = ROOT / "data" / "ranking_steps.jsonl"
COMMUNITY_TIPS_PATH = ROOT / "data" / "community_tips.jsonl"
ODDS_PATH = ROOT / "data" / "odds_history.jsonl"
WEB_DIR = ROOT / "web"
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _enrich_tip(t: dict) -> dict:
    """Add came-true status + a 'craziness' score used for highlighting.

    Status is derived from tip-vs-result (scoring-independent), so it stays
    correct regardless of the community's point scheme:
      "exact"    — tip == result
      "diff"     — right tendency, right goal-difference, non-draw  (→ 3 pts)
      "tendency" — right tendency, but diff wrong or both sides drew (→ 2 pts)
      "miss"     — wrong tendency                                    (→ 0 pts)
      "open"     — no result yet
    """
    h_tip, a_tip = t["home_tip"], t["away_tip"]
    h_res, a_res = t.get("home_result"), t.get("away_result")
    pts = t.get("points")

    t = dict(t)
    if h_res is None or a_res is None:
        t["status"] = "open"
        t["craziness"] = 0
        return t

    gd_tip = h_tip - a_tip
    gd_res = h_res - a_res
    total_res = h_res + a_res
    tend_tip = _sign(gd_tip)
    tend_res = _sign(gd_res)

    if h_tip == h_res and a_tip == a_res:
        t["status"] = "exact"
        # Nailing a lopsided, high-scoring line exactly is the wildest outcome.
        t["craziness"] = total_res + 2 * abs(gd_res)
    elif tend_tip != tend_res:
        t["status"] = "miss"
        # How far off, weighted up when the tendency was backwards.
        error = abs(h_tip - h_res) + abs(a_tip - a_res)
        backwards = tend_tip != 0 and tend_res != 0  # both non-draw, opposite signs
        t["craziness"] = error + (3 if backwards else 0)
        t["backwards"] = backwards
    elif gd_tip == gd_res and gd_res != 0:
        t["status"] = "diff"
        t["craziness"] = 0
    else:
        # Right tendency but wrong difference — includes non-exact draws (diff==0).
        t["status"] = "tendency"
        t["craziness"] = 0
    return t


def _wucht(t: dict) -> int:
    """How lopsided/high-scoring the actual result was (tiebreaker only)."""
    return (t["home_goals"] + t["away_goals"]) + 2 * abs(t["home_goals"] - t["away_goals"])


def _load_odds() -> dict[tuple, dict]:
    """Load odds_history.jsonl → dict keyed by (spieltag_index, home_team, away_team).

    When multiple snapshots exist for the same game the last one wins (forward-only
    updates, latest snapshot is most accurate pre-kickoff odds).
    """
    odds: dict[tuple, dict] = {}
    for row in _read_jsonl(ODDS_PATH):
        key = (row["spieltag_index"], row["home_team"], row["away_team"])
        odds[key] = row
    return odds


def _implied_probs(
    odds_home: float, odds_draw: float, odds_away: float
) -> tuple[float, float, float]:
    """Return overround-normalised implied probabilities (home, draw, away)."""
    inv_h, inv_d, inv_a = 1 / odds_home, 1 / odds_draw, 1 / odds_away
    s = inv_h + inv_d + inv_a
    return inv_h / s, inv_d / s, inv_a / s


def _tendency_prob(probs: tuple[float, float, float], tendency_sign: int) -> float:
    """Probability for the given tendency sign (+1=home win, 0=draw, -1=away win)."""
    p_home, p_draw, p_away = probs
    if tendency_sign > 0:
        return p_home
    elif tendency_sign == 0:
        return p_draw
    else:
        return p_away


def _score_crazy_row(
    t: dict,
    n: int,
    n_exact: int,
    n_tend: int,
    odds_entry: dict | None,
) -> dict | None:
    """Score one community-tip row for craziness.

    Returns an enriched dict with ``status``, ``craziness``, ``odds_based`` (and
    optionally ``outcome_odds``, ``p``) — or ``None`` when the row is neither an
    exact hit nor a tendency miss.

    Both Wahnsinns-Treffer and Komplett-daneben scores are on a ~0..2 scale so
    the two columns are sortable together and comparable with the odds-based path.

    Wahnsinns-Treffer:
        exact_rarity  = (n - n_exact) / n
        tend_unlikely = 1 - p(result_tendency)   [odds] or (n - n_tend) / n  [field]
        craziness     = tend_unlikely + exact_rarity

    Komplett daneben:
        error_norm = min(|tip - result|_sum, 6) / 6
        boldness   = p(tipped_tendency)           [odds] or (n - n_tend) / n  [field]
        craziness  = boldness + error_norm
    """
    h, a = t["home_goals"], t["away_goals"]
    ht, at = t["home_tip"], t["away_tip"]
    res_sign = _sign(h - a)
    tip_sign = _sign(ht - at)

    # Parse odds only when all three values are present and strictly positive.
    probs: tuple[float, float, float] | None = None
    if odds_entry:
        oh = odds_entry.get("odds_home")
        od = odds_entry.get("odds_draw")
        oa = odds_entry.get("odds_away")
        if oh and od and oa and oh > 0 and od > 0 and oa > 0:
            probs = _implied_probs(oh, od, oa)

    exact_rarity = (n - n_exact) / n
    stats = {"n_players": n, "n_exact": n_exact, "n_tend": n_tend, "odds_based": probs is not None}

    if ht == h and at == a:
        # ── Wahnsinns-Treffer ──────────────────────────────────────────────
        if probs is not None:
            tend_unlikely = 1.0 - _tendency_prob(probs, res_sign)
            if res_sign > 0:
                outcome_odds = odds_entry["odds_home"]  # type: ignore[index]
            elif res_sign == 0:
                outcome_odds = odds_entry["odds_draw"]  # type: ignore[index]
            else:
                outcome_odds = odds_entry["odds_away"]  # type: ignore[index]
        else:
            tend_unlikely = (n - n_tend) / n
            outcome_odds = None

        craziness = tend_unlikely + exact_rarity
        row = {**t, "status": "exact", "craziness": craziness, **stats}
        if probs is not None:
            row["outcome_odds"] = round(outcome_odds, 2)
            row["p"] = round(_tendency_prob(probs, res_sign), 3)
        return row

    elif tip_sign != res_sign:
        # ── Komplett daneben ───────────────────────────────────────────────
        error = abs(ht - h) + abs(at - a)
        error_norm = min(error, 6) / 6

        if probs is not None:
            boldness = _tendency_prob(probs, tip_sign)
            if tip_sign > 0:
                outcome_odds = odds_entry["odds_home"]  # type: ignore[index]
            elif tip_sign == 0:
                outcome_odds = odds_entry["odds_draw"]  # type: ignore[index]
            else:
                outcome_odds = odds_entry["odds_away"]  # type: ignore[index]
        else:
            boldness = (n - n_tend) / n
            outcome_odds = None

        craziness = boldness + error_norm
        row = {**t, "status": "miss", "craziness": craziness, **stats}
        if probs is not None:
            row["outcome_odds"] = round(outcome_odds, 2)
            row["p"] = round(_tendency_prob(probs, tip_sign), 3)
        return row

    return None


def build_crazy() -> dict:
    """Community-wide crazy tips — hybrid: Buchmacher-Quoten wo vorhanden, sonst Tippkreis.

    Joined über (spieltag_index, home, away) = (spieltag_index, home_team, away_team).
    Beide Pfade liefern Craziness ~0..2 → gemeinsam sortierbar.
    """
    rows = _read_jsonl(COMMUNITY_TIPS_PATH)
    odds_map = _load_odds()

    by_match: dict[tuple, list[dict]] = {}
    for t in rows:
        by_match.setdefault((t["spieltag_index"], t["home"], t["away"]), []).append(t)

    exact, miss = [], []
    for (st_idx, home, away), tips in by_match.items():
        n = len(tips)
        h, a = tips[0]["home_goals"], tips[0]["away_goals"]
        res_sign = _sign(h - a)
        n_exact = sum(1 for t in tips if t["home_tip"] == h and t["away_tip"] == a)
        n_tend = sum(1 for t in tips if _sign(t["home_tip"] - t["away_tip"]) == res_sign)

        # Join with odds (key: spieltag_index, home_team, away_team == home, away in community_tips)
        odds_entry = odds_map.get((st_idx, home, away))

        for t in tips:
            scored = _score_crazy_row(t, n, n_exact, n_tend, odds_entry)
            if scored is None:
                continue
            if scored["status"] == "exact":
                exact.append(scored)
            else:
                miss.append(scored)

    exact.sort(key=lambda r: (-r["craziness"], -_wucht(r), r["n_exact"]))
    miss.sort(key=lambda r: (-r["craziness"], -_wucht(r)))

    def _distinct(rows: list[dict]) -> list[dict]:
        # one card per match (the craziest tip) so a shock game doesn't flood the section
        seen: set[tuple] = set()
        out: list[dict] = []
        for r in rows:
            key = (r["spieltag_index"], r["home"], r["away"])
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out[:8]

    return {"exact": _distinct(exact), "miss": _distinct(miss)}


def build_timeline() -> list[dict]:
    """Group the per-(step × player) rows into one entry per match-step."""
    by_ord: dict[int, list[dict]] = {}
    for r in _read_jsonl(STEPS_PATH):
        by_ord.setdefault(r["ordinal"], []).append(r)
    timeline = []
    for ordv in sorted(by_ord):
        rows = by_ord[ordv]
        meta = rows[0]
        timeline.append({
            "ordinal": ordv,
            "spieltag_index": meta["spieltag_index"],
            "spieltag_label": meta["spieltag_label"],
            "match_index": meta["match_index"],
            "home": meta["home"], "away": meta["away"], "result": meta["result"],
            "standings": sorted(
                ({"player": r["player"], "rank": r["rank"], "points": r["points"],
                  "bonus": r.get("bonus", 0), "is_self": r["is_self"]} for r in rows),
                key=lambda x: x["rank"]),
        })
    return timeline


def build_payload() -> dict:
    # Lazy import breaks the awards <-> dashboard import cycle (awards reuses our
    # craziness helpers; we only need build_awards at request time).
    from awards import build_awards

    tips = [_enrich_tip(t) for t in _read_jsonl(TIPS_PATH)]
    ranking = _read_jsonl(RANKING_PATH)
    timeline = build_timeline()
    log = parse_log()

    # Attach reasoning to llm tips by (home|away).
    rb = log["reasoning_by_match"]
    for t in tips:
        if t["strategy"] == "llm":
            r = rb.get(f"{t['home_team']}|{t['away_team']}")
            if r:
                t["reasoning"] = r["text"]
                t["reasoning_run"] = r["run"]

    # Per-strategy summary (matches the bot's own log line).
    summary: dict[str, dict] = {}
    for t in tips:
        if t.get("points") is None:
            continue
        s = summary.setdefault(t["strategy"], {"matches": 0, "points": 0})
        s["matches"] += 1
        s["points"] += t["points"]
    for s in summary.values():
        s["avg"] = round(s["points"] / s["matches"], 2) if s["matches"] else 0

    return {
        "tips": tips,
        "ranking_history": ranking,
        "timeline": timeline,
        "crazy": build_crazy(),
        "awards": build_awards(),
        "standings_timeline": log["standings_timeline"],
        "summary": summary,
    }


def _refresh_ranking() -> dict:
    """Live re-scrape of the standings history. Best-effort; returns a status."""
    try:
        from dotenv import load_dotenv
        from kicktipp import KicktippClient
        from ranking_history import build_ranking_history

        load_dotenv()
        client = KicktippClient(
            os.environ["KICKTIPP_EMAIL"],
            os.environ["KICKTIPP_PASSWORD"],
            os.environ["KICKTIPP_COMMUNITY"],
        )
        client.login()
        n = build_ranking_history(client)
        return {"ok": True, "rows": n}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return {"ok": False, "error": str(exc)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/", "/index.html"):
            html = (WEB_DIR / "dashboard.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path.startswith("/api/data"):
            self._send_json(build_payload())
        elif self.path.startswith("/api/refresh"):
            self._send_json(_refresh_ranking())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # quieten the per-request stderr noise
        pass


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"kicktipp dashboard → {url}  (Ctrl+C to stop)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()

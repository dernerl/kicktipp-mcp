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
WEB_DIR = ROOT / "web"
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _enrich_tip(t: dict) -> dict:
    """Add came-true status + a 'craziness' score used for highlighting."""
    h_tip, a_tip = t["home_tip"], t["away_tip"]
    h_res, a_res = t.get("home_result"), t.get("away_result")
    pts = t.get("points")

    t = dict(t)
    if pts is None or h_res is None:
        t["status"] = "open"
        t["craziness"] = 0
        return t

    gd_res = h_res - a_res
    total_res = h_res + a_res
    if pts == 3:
        t["status"] = "exact"
        # Nailing a lopsided, high-scoring line exactly is the wildest outcome.
        t["craziness"] = total_res + 2 * abs(gd_res)
    elif pts == 2:
        t["status"] = "diff"
        t["craziness"] = 0
    elif pts == 1:
        t["status"] = "tendency"
        t["craziness"] = 0
    else:
        t["status"] = "miss"
        # How far off, weighted up when the tendency was backwards.
        error = abs(h_tip - h_res) + abs(a_tip - a_res)
        backwards = _sign(h_tip - a_tip) == -_sign(gd_res) and gd_res != 0 and (h_tip - a_tip) != 0
        t["craziness"] = error + (3 if backwards else 0)
        t["backwards"] = backwards
    return t


def _wucht(t: dict) -> int:
    """How lopsided/high-scoring the actual result was (tiebreaker only)."""
    return (t["home_goals"] + t["away_goals"]) + 2 * abs(t["home_goals"] - t["away_goals"])


def build_crazy() -> dict:
    """Community-wide crazy tips, judged *against the field* (the crowd = the odds).

    For each match we count how many of the players nailed the exact score and how
    many at least got the tendency.  An exact hit that almost nobody else managed —
    especially on a result the field largely got wrong — is the craziest.  Misses
    are weighted by how badly wrong the tip was on a result that shocked the field.
    """
    rows = _read_jsonl(COMMUNITY_TIPS_PATH)
    by_match: dict[tuple, list[dict]] = {}
    for t in rows:
        by_match.setdefault((t["spieltag_index"], t["home"], t["away"]), []).append(t)

    exact, miss = [], []
    for tips in by_match.values():
        n = len(tips)
        h, a = tips[0]["home_goals"], tips[0]["away_goals"]
        res_sign = _sign(h - a)
        n_exact = sum(1 for t in tips if t["home_tip"] == h and t["away_tip"] == a)
        n_tend = sum(1 for t in tips if _sign(t["home_tip"] - t["away_tip"]) == res_sign)
        for t in tips:
            ht, at = t["home_tip"], t["away_tip"]
            stats = {"n_players": n, "n_exact": n_exact, "n_tend": n_tend}
            if ht == h and at == a:
                # rarity of the exact call + how much the result bucked the field
                craz = (n - n_exact) + (n - n_tend)
                exact.append({**t, "status": "exact", "craziness": craz, **stats})
            elif _sign(ht - at) != res_sign:
                error = abs(ht - h) + abs(at - a)
                backwards = _sign(ht - at) != 0 and res_sign != 0
                # big, wrong, on a result that shocked the field
                craz = error + (3 if backwards else 0) + (n - n_tend)
                miss.append({**t, "status": "miss", "craziness": craz, **stats})

    exact.sort(key=lambda r: (-r["craziness"], -_wucht(r), r["n_exact"]))
    miss.sort(key=lambda r: (-r["craziness"], -_wucht(r)))

    def _distinct(rows):
        # one card per match (the craziest tip) so a shock game doesn't flood
        seen, out = set(), []
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

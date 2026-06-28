"""Extract the bits of the launchd log the dashboard needs.

The bot's log (~/Library/Logs/kicktipp-ai.log) is the only place two things live:

  * the *reasoning* Claude produced for each llm pick (only the parsed scores get
    persisted to tips_history.jsonl — the "why" is log-only), and
  * the bot's own rank in the community over time ("Standing: rank 8/12, 111 pts").

This module turns that free-form text into structured data keyed by match, so the
personal section can show a "Warum?" panel and a rank trajectory.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_LOG = Path.home() / "Library" / "Logs" / "kicktipp-ai.log"

_RUN_RE = re.compile(r"^=== kicktipp-ai run (.+?) ===")
_REASON_START = "--- Claude reasoning ---"
_REASON_END = "--- end Claude reasoning ---"
_STANDING_RE = re.compile(r"Standing: rank (\d+)/(\d+), (\d+) pts")
# e.g. "  [Sat 27 Jun 02:00] Uruguay 0 : 2 Spanien"
_MATCH_RE = re.compile(r"^\s*\[[^\]]+\]\s*(.+?)\s+(\d+)\s*:\s*(\d+)\s+(.+?)\s*$")


def _match_key(home: str, away: str) -> str:
    return f"{home.strip()}|{away.strip()}"


def parse_log(path: Path | str = DEFAULT_LOG) -> dict:
    """Return {'reasoning_by_match': {key: {...}}, 'standings_timeline': [...]}.

    reasoning_by_match maps "home|away" → {text, run}; the most recent run wins.
    standings_timeline is chronological {timestamp, rank, field, points}.
    """
    p = Path(path)
    if not p.exists():
        return {"reasoning_by_match": {}, "standings_timeline": []}

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

    reasoning_by_match: dict[str, dict] = {}
    standings: list[dict] = []

    run_ts = ""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        m = _RUN_RE.match(line)
        if m:
            run_ts = m.group(1).strip()
            i += 1
            continue

        s = _STANDING_RE.search(line)
        if s:
            standings.append({
                "timestamp": run_ts,
                "rank": int(s.group(1)),
                "field": int(s.group(2)),
                "points": int(s.group(3)),
            })
            i += 1
            continue

        if line.strip() == _REASON_START:
            # Collect the reasoning text until the end marker …
            j = i + 1
            buf: list[str] = []
            while j < n and lines[j].strip() != _REASON_END:
                buf.append(lines[j])
                j += 1
            text = "\n".join(buf).strip()
            # … then the match lines submitted right after it belong to this block.
            k = j + 1
            while k < n:
                mm = _MATCH_RE.match(lines[k])
                if mm:
                    key = _match_key(mm.group(1), mm.group(4))
                    reasoning_by_match[key] = {"text": text, "run": run_ts}
                    k += 1
                elif lines[k].strip() == "" or lines[k].lstrip().startswith("Submitted"):
                    k += 1
                else:
                    break
            i = k
            continue

        i += 1

    return {"reasoning_by_match": reasoning_by_match, "standings_timeline": standings}


if __name__ == "__main__":
    import json
    data = parse_log()
    print(f"reasoning entries: {len(data['reasoning_by_match'])}")
    print(f"standings points : {len(data['standings_timeline'])}")
    print(json.dumps(data["standings_timeline"], indent=2, ensure_ascii=False))

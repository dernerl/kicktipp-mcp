# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kicktipp football-tipping bot with two entry points plus a results dashboard:
- `mcp_server.py` — FastMCP server (tools: `list_open_matches`, `list_submitted_tips`, `submit_tips`, `get_ranking`).
- `main.py` — CLI bot run on a schedule via launchd (`run.sh`); strategies in `strategies.py` (`random`, `llm`).
- `dashboard.py` — local results dashboard (see below).
- `kicktipp.py` — the HTTP client + all HTML parsing; everything else builds on it.

## Gotchas (Claude will get these wrong otherwise)

- **Non-standard scoring (4/3/2/0).** This community scores **4 = exact, 3 = correct
  goal difference (non-draw), 2 = correct tendency (incl. a non-exact draw), 0 = wrong** —
  NOT the standard Kicktipp 3/2/1. `tracking._points` implements this scheme
  (verified 1:1 against the live cell points in `community_tips.jsonl`). Tip-outcome
  classification (`dashboard._enrich_tip` `status`, and *Verrückte Tipps*) is done by
  tip-vs-result, so it's correct regardless of the point values. See ADR 0005.
- **Bookmaker odds only exist pre-kickoff.** Kicktipp shows 1/X/2 odds only on the
  Tippabgabe page for upcoming matches and never retroactively. `odds_history.py`
  snapshots them forward-only (upsert per match); past-match odds can't be backfilled.
- **`data/` is gitignored and regenerable** — never commit it. The dashboard's inputs
  are rebuilt by `ranking_history.py` (writes `ranking_history.jsonl`,
  `ranking_steps.jsonl`, `community_tips.jsonl`); `tips_history.jsonl`/`odds_history.jsonl`
  grow on each bot run.
- **Historical standings/tips are reconstructed**, not stored: scraped from each
  per-Spieltag `tippuebersicht` page (table `id="ranking"`, per-match `<sub class="p">`
  point cells). The Gesamtübersicht's `spieltagIndex` param is ignored by Kicktipp.

## Commands

```bash
uv run python main.py --strategy random --dry-run    # bot, prints tips, submits nothing
uv run python ranking_history.py                     # rebuild dashboard data (logs in once)
uv run python dashboard.py                            # serve dashboard at http://localhost:8765
uv run python -m py_compile <files>                  # quick sanity check (no test suite)
```

Credentials live in `.env` (`KICKTIPP_EMAIL`/`PASSWORD`/`COMMUNITY`), gitignored.

## Conventions

- **No new dependencies.** Stdlib + the existing four (`requests`, `beautifulsoup4`,
  `python-dotenv`, `mcp`). The dashboard server is stdlib `http.server`; its frontend
  is one vanilla-JS/SVG file (`web/dashboard.html`), no build step.
- **Don't touch the tipping/scoring path casually** (`strategies.py` selection,
  `tracking._points`) — changing scoring rewrites historical comparisons.
- **Record non-trivial decisions as ADRs** (Nygard format) in `docs/adr/`.
- There is no automated test suite; verify by running the commands above (dry-run for
  the bot, headless Chrome or a reload for the dashboard).

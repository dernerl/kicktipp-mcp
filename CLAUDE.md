# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kicktipp MCP server + reusable client, kept aligned with upstream
[Cloudy261/kicktipp-mcp](https://github.com/Cloudy261/kicktipp-mcp) for future PRs:

- `kicktipp.py` — the HTTP client + all HTML parsing (matches, tips, ranking,
  past results, odds); everything else builds on it.
- `mcp_server.py` — FastMCP server (tools: `list_open_matches`,
  `list_submitted_tips`, `submit_tips`, `get_ranking`).
- `strategies.py` — tipping strategies (`random`, `llm`).

The automated bot (cron), score/odds tracking, and the results dashboard
(local + hosted on Vercel) live in a separate repo,
[dernerl/kicktipp-dashboard](https://github.com/dernerl/kicktipp-dashboard) —
kept out of this fork so it stays a clean, upstream-alignable diff. See
`dernerl/kicktipp-dashboard`'s `docs/adr/0009-github-actions-cron-und-vercel-hosting.md`
for why. `kicktipp.py` and `strategies.py` are vendored (copied) into that
repo — port fixes made here back there manually; there's no automated sync.

## Gotchas (Claude will get these wrong otherwise)

- **This fork has community-specific history that hasn't been upstreamed.**
  Not everything here matches `Cloudy261/kicktipp-mcp` 1:1 — check
  `git log origin/main..HEAD` before assuming a change is generic enough for
  an upstream PR; some past commits mixed generic fixes with
  community-specific behaviour (this is exactly why the bot/dashboard were
  split out into their own repo).
- **Non-standard scoring exists downstream, not here.** The `kicktipp-dashboard`
  repo's Tippkreis uses 4/3/2/0 scoring, not the standard Kicktipp 3/2/1 — that
  logic lives entirely in `tracking.py` over there, not in this repo.

## Commands

```bash
uv run python main.py --strategy random --dry-run    # if present locally; see kicktipp-dashboard for the maintained bot
uv run python -m py_compile *.py                     # quick sanity check (no test suite)
```

Credentials live in `.env` (`KICKTIPP_EMAIL`/`PASSWORD`/`COMMUNITY`), gitignored.

## Conventions

- **No new dependencies.** Stdlib + `requests`, `beautifulsoup4`, `python-dotenv`, `mcp`.
- **Record non-trivial decisions as ADRs** (Nygard format) — this repo doesn't
  currently have its own `docs/adr/`; historical decisions about the bot,
  scoring, and dashboard live in `dernerl/kicktipp-dashboard`'s `docs/adr/`.
- There is no automated test suite; verify with `py_compile` and by exercising
  the MCP tools via Claude Desktop.

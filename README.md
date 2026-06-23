# kicktipp-ai

Automated [Kicktipp](https://www.kicktipp.de/) football tipping. Ships in two flavours:

- **MCP server** — exposes Kicktipp tools to Claude Desktop (or any MCP client) so you can ask Claude to look at open matches and submit predictions.
- **CLI bot** — a standalone script that fills in tips on a schedule using a built-in strategy.

> ⚠️ Use responsibly and at your own risk. Automating logins to a third-party site may be against Kicktipp's terms of service. This is a personal hobby project.

## Features

The MCP server (`mcp_server.py`) provides three tools:

- `list_open_matches` — matches that still need a tip (not yet kicked off, not already tipped)
- `list_submitted_tips` — tips you've already submitted
- `submit_tips` — post predicted home/away scores

The CLI bot (`main.py`) supports two strategies:

- `random` — weighted Poisson scoreline sampling
- `llm` — shells out to the Claude Code CLI (`claude -p`) to predict scores with web search; automatically fetches all completed match results from Kicktipp and injects team form (goals, W/D/L, points) into the prompt as tournament context

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or plain `pip`
- A Kicktipp account and a community you're a member of
- For the `llm` strategy: the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) on your PATH

## Setup

1. **Install dependencies**

   ```bash
   uv sync          # or: pip install -e .
   ```

2. **Configure credentials**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` with your Kicktipp email, password, and community slug.
   The community slug is the path segment in your community URL — for
   `https://www.kicktipp.de/my-community/` it's `my-community`.

   `.env` is git-ignored; never commit it.

## Usage

### CLI bot

```bash
# Dry run — print tips without submitting
uv run python main.py --strategy random --dry-run

# Submit tips for matches starting within the next 48 hours
uv run python main.py --strategy random --max-hours-ahead 48

# Use the LLM strategy (requires the claude CLI)
uv run python main.py --strategy llm
```

Run `uv run python main.py --help` for all options (`--community`, `--debug-html`, …).

### Scheduled runs (macOS launchd)

`com.kicktipp-ai.bot.plist` runs the bot every 6 hours via launchd.

1. Edit the plist and set the correct project path in `ProgramArguments` (the `cd …` line).
2. Copy it into place and load it:

   ```bash
   cp com.kicktipp-ai.bot.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.kicktipp-ai.bot.plist
   ```

Logs are written to `~/Library/Logs/kicktipp-ai.log` (persistent across reboots).
Each run starts with a timestamped header:

```
=== kicktipp-ai run 2026-06-16 22:00:01 ===
Open matches: 8, tippable now: 4
  [Wed 17 Jun 00:00] Irak 1 : 1 Norwegen
  ...
Submitted 4 tips.
```

Follow the log live:

```bash
tail -f ~/Library/Logs/kicktipp-ai.log
```

### Performance tracking

Every submitted tip is appended to `data/tips_history.jsonl` with a `strategy`
label (`random` or `llm`). On each run, `update_scores()` (`tracking.py`)
fetches the by-then-completed match results from Kicktipp and fills in the
real result + points for any tip whose match has since finished, using the
standard Kicktipp scoring (3 pts exact score, 2 pts correct goal difference,
1 pt correct tendency, 0 pts wrong tendency). The log then prints a running
average per strategy, e.g.:

```
Scored 6 newly completed match(es).
  [random] 7 pts / 8 matches (avg 0.88)
  [llm] 13 pts / 13 matches (avg 1.00)
```

That's how `random` (the Poisson baseline) and `llm` (Claude with web search)
get compared over time. `random` only has a handful of entries from manual
testing before `llm` became the default strategy in `run.sh`.

When using the `llm` strategy, the full reasoning Claude produced (odds,
injury news, form) is printed to the log right before the final JSON tips —
only the parsed scores get persisted to `tips_history.jsonl`, so the log is
the only place to audit *why* a pick was made.

### MCP server (Claude Desktop)

1. Edit `claude_desktop_config.example.json` and replace the placeholder path
   with the absolute path to `run-mcp.sh`.
2. Merge its contents into your Claude Desktop config at
   `~/Library/Application Support/Claude/claude_desktop_config.json`.
3. Restart Claude Desktop.

You can then ask Claude to list open matches and submit tips for you.

## Project layout

| File | Purpose |
|------|---------|
| `kicktipp.py` | Kicktipp HTTP client + HTML parsing (matches, tips, ranking, past results) |
| `mcp_server.py` | FastMCP server exposing the tools |
| `main.py` | CLI entry point for the bot |
| `strategies.py` | Tipping strategies (random / llm) |
| `tracking.py` | Tip history + score tracking (`data/tips_history.jsonl`) |
| `run-mcp.sh` | Launcher Claude Desktop uses for the MCP server |
| `run.sh` | Launcher the launchd job uses for the CLI bot |

## License

MIT — see [LICENSE](LICENSE).

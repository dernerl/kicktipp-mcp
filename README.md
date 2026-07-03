# kicktipp-mcp

An MCP server exposing [Kicktipp](https://www.kicktipp.de/) football-tipping
tools to Claude Desktop (or any MCP client), plus the underlying HTTP
client/parser and tipping strategies it's built on.

> ⚠️ Use responsibly and at your own risk. Automating logins to a third-party
> site may be against Kicktipp's terms of service. This is a personal hobby
> project, forked from [Cloudy261/kicktipp-mcp](https://github.com/Cloudy261/kicktipp-mcp).

> **Looking for the automated bot / score tracking / results dashboard?**
> That lives in a separate repo,
> [dernerl/kicktipp-dashboard](https://github.com/dernerl/kicktipp-dashboard),
> which vendors `kicktipp.py`/`strategies.py` from here and builds the
> scheduled bot + dashboard on top. Kept separate so this fork stays a clean,
> upstream-alignable diff.

## Features

The MCP server (`mcp_server.py`) provides four tools:

- `list_open_matches` — matches that still need a tip (not yet kicked off,
  not already tipped), including bookmaker odds (1/X/2) when Kicktipp shows them
- `list_submitted_tips` — tips you've already submitted
- `submit_tips` — post predicted home/away scores
- `get_ranking` — current community standings

`strategies.py` provides two tipping strategies usable by any client script:

- `random` — weighted Poisson scoreline sampling
- `llm` — shells out to the Claude Code CLI (`claude -p`) to predict scores
  with web search

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

### MCP server (Claude Desktop)

1. Edit `claude_desktop_config.example.json` and replace the placeholder path
   with the absolute path to `run-mcp.sh`.
2. Merge its contents into your Claude Desktop config at
   `~/Library/Application Support/Claude/claude_desktop_config.json`.
3. Restart Claude Desktop.

You can then ask Claude to list open matches, check the ranking, and submit
tips for you.

## Project layout

| File | Purpose |
|------|---------|
| `kicktipp.py` | Kicktipp HTTP client + HTML parsing (matches, tips, ranking, past results, odds) |
| `mcp_server.py` | FastMCP server exposing the tools |
| `strategies.py` | Tipping strategies (random / llm) |
| `run-mcp.sh` | Launcher Claude Desktop uses for the MCP server |

## License

MIT — see [LICENSE](LICENSE).

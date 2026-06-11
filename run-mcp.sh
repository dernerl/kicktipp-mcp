#!/bin/bash
# Wrapper Claude Desktop uses to launch the MCP server.
# Edit the python invocation if you don't use uv.
set -euo pipefail

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
    exec uv run python mcp_server.py
else
    exec python3 mcp_server.py
fi

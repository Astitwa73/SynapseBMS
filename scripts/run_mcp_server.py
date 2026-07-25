"""Start the MCP server over stdio.

Expects the building API to already be running:

    python scripts/run_server.py          # terminal 1
    python scripts/run_mcp_server.py      # terminal 2, or launched by an MCP client

Set BMS_API_URL to point at a backend on another host or port.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.mcp_server.server import main  # noqa: E402

if __name__ == "__main__":
    main()

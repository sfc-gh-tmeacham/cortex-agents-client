"""Cleanup script: drop leaked disposable agents from test_agents.py.

Those tests create agents named ``cac_live_crud_<uuid8>`` and drop them in a
fixture ``finally`` block. A hard kill (SIGKILL, or a crashed interpreter) can
still leak one. Their names are not predictable, so they cannot be listed in
teardown.sql -- this sweeps them by prefix instead.

Usage::

    SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \\
      uv run python tests/live/seed/cleanup_leaked_agents.py

Optionally set LIVE_AGENT_MINIMAL to derive the database and schema; otherwise
the cac_live defaults are used.
"""

from __future__ import annotations

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from cortex_agents_client import CortexAgentsClient

PREFIX = "cac_live_crud_"
DEFAULT_DB = "cac_live_db"
DEFAULT_SCHEMA = "cac_live_schema"


def main() -> None:
    url = os.environ.get("SNOWFLAKE_ACCOUNT_URL")
    pat = os.environ.get("SNOWFLAKE_PAT")
    if not url or not pat:
        print("ERROR: set SNOWFLAKE_ACCOUNT_URL and SNOWFLAKE_PAT", file=sys.stderr)
        sys.exit(1)

    agent_path = os.environ.get("LIVE_AGENT_MINIMAL", "")
    parts = agent_path.split(".")
    db = parts[0] if len(parts) >= 3 else DEFAULT_DB
    schema = parts[1] if len(parts) >= 3 else DEFAULT_SCHEMA

    client = CortexAgentsClient(url, pat)
    agents = client.agents.list(database=db, schema=schema, like=f"{PREFIX}%")
    if not agents:
        print(f"No leaked agents found matching '{PREFIX}%' in {db}.{schema}.")
        return

    print(f"Found {len(agents)} leaked agent(s) in {db}.{schema}. Dropping...")
    for a in agents:
        try:
            client.agents.delete(a.name, database=db, schema=schema, if_exists=True)
            print(f"  Dropped {a.name}")
        except Exception as exc:
            print(f"  FAILED to drop {a.name}: {exc}")

    print("Done.")


if __name__ == "__main__":
    main()

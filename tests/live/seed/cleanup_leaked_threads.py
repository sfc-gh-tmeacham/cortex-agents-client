"""Deletes all threads tagged origin_application='cac_live'.

Run this after an interrupted test suite to remove leaked threads.

Usage::

    SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
      uv run python tests/live/seed/cleanup_leaked_threads.py
"""

from __future__ import annotations

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from cortex_agents_client import CortexAgentsClient

ORIGIN_APP = "cac_live"


def main() -> None:
    url = os.environ.get("SNOWFLAKE_ACCOUNT_URL")
    pat = os.environ.get("SNOWFLAKE_PAT")
    if not url or not pat:
        print("ERROR: set SNOWFLAKE_ACCOUNT_URL and SNOWFLAKE_PAT", file=sys.stderr)
        sys.exit(1)

    client = CortexAgentsClient(url, pat)
    threads = client.threads.list(origin_application=ORIGIN_APP)
    if not threads:
        print(f"No leaked threads found with origin_application='{ORIGIN_APP}'.")
        return

    print(f"Found {len(threads)} leaked thread(s). Deleting...")
    for t in threads:
        try:
            client.threads.delete(t.thread_id)
            print(f"  Deleted {t.thread_id}")
        except Exception as exc:
            print(f"  FAILED to delete {t.thread_id}: {exc}")

    print("Done.")


if __name__ == "__main__":
    main()

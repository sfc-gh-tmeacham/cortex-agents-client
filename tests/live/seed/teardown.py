"""Standalone teardown script — drops all cac_live test objects.

Runs the same DROP statements that the pytest session fixture executes.
Use this when a test session was interrupted and objects need manual cleanup.

Usage:
    SNOWFLAKE_ACCOUNT_URL="https://..." SNOWFLAKE_PAT="v2:..." \
        uv run python tests/live/seed/teardown.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

import httpx

TEARDOWN_SQL = pathlib.Path(__file__).parent / "teardown.sql"


def run_teardown(account_url: str, pat: str) -> None:
    statements = [
        line.strip().rstrip(";")
        for line in TEARDOWN_SQL.read_text().splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {pat}",
        "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
    }

    with httpx.Client(timeout=60.0) as client:
        for stmt in statements:
            resp = client.post(
                f"{account_url}/api/v2/statements",
                headers=headers,
                json={"statement": stmt, "timeout": 30},
            )
            if resp.status_code in (200, 202):
                print(f"  OK   {stmt[:80]}")
            else:
                print(f"  WARN {stmt[:80]} → {resp.status_code}: {resp.text[:120]}")
            time.sleep(0.2)  # avoid rate limiting


def main() -> None:
    url = os.environ.get("SNOWFLAKE_ACCOUNT_URL")
    pat = os.environ.get("SNOWFLAKE_PAT")
    if not url or not pat:
        print("ERROR: set SNOWFLAKE_ACCOUNT_URL and SNOWFLAKE_PAT", file=sys.stderr)
        sys.exit(1)

    print("Dropping cac_live test objects...")
    run_teardown(url, pat)
    print("Done.")


if __name__ == "__main__":
    main()

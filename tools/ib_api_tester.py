"""
IB API CLI Tester — agent diagnostic tool
==========================================
This file exists for ONE purpose: let the agent verify IB API data
directly in the terminal BEFORE touching any frontend or UI code.

HOW TO USE:
  Always run in PowerShell from project root:
  cd F:\ib-trading-platform
  python3.11 tools/ib_api_tester.py

THIS FILE IS A LIVING TOOL — ALWAYS MODIFY IT:
  Do NOT treat this as a fixed utility.
  For each task or bug, rewrite the script body to test exactly what you need.
  See AGENTS.md → IB API Verification Protocol for the full workflow.

EXAMPLES OF WHAT TO PUT IN THE SCRIPT BODY:
  - Fetch historical bars (same symbol/TF/params as the UI uses)
  - Subscribe to live tick data and print incoming values
  - Resolve and print contract details
  - Query open orders or positions
  - Pull account summary / PnL values
  - Test any IB API call the app relies on

The output here is ground truth. If data looks correct here
but broken in UI → it is a frontend bug. Fix frontend.
If data is wrong here → fix the backend first, never touch frontend.

IMPORTANT: Cross-reference results with IB Paper Trading Notes in AGENTS.md.
Missing or limited tick/real-time data on paper account is NOT a bug.
"""

import asyncio
from ib_insync import IB, util

HOST = "127.0.0.1"
PORT = 7497
CLIENT_ID = 99  # dedicated tester client ID — never conflicts with app (uses 1)


async def main():
    ib = IB()
    print(f"🔌 Connecting to IB on {HOST}:{PORT} (clientId={CLIENT_ID})...")
    await ib.connectAsync(HOST, PORT, clientId=CLIENT_ID)
    print(f"✅ Connected. Server time: {ib.reqCurrentTime()}")

    # -------------------------------------------------------
    # AGENT: Replace everything below with your specific test.
    # This is just a connection check as the default baseline.
    # -------------------------------------------------------

    print("\n📋 No test defined yet.")
    print("Modify this script body to test the exact API call you need.")

    # -------------------------------------------------------

    ib.disconnect()
    print("\n🔌 Disconnected.")


if __name__ == "__main__":
    util.patchAsyncio()
    asyncio.run(main())

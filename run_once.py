#!/usr/bin/env python3
# run_once.py
# Runs a single analyze() cycle from btc_scan.py and sends Telegram message.

import sys
import os

# ensure repo root on path
repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

try:
    from btc_scan import analyze, send_telegram_message_obj
except Exception as e:
    print("Import error:", e)
    raise

def main():
    try:
        result = analyze()
        if result is None:
            print("analyze() returned None — nothing to send.")
            return 1
        # send via the btc_scan send function (which reads env vars)
        send_telegram_message_obj(result)
        print("run_once completed OK")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("run_once failed:", e)
        return 2

if __name__ == "__main__":
    exit(main())

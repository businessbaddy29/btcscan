#!/usr/bin/env python3
# run_once_debug.py  (replace run_once.py content with this)

import sys, os, traceback, json, requests

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

# Read env for quick debug
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_debug_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("DEBUG: TELEGRAM token/chat not set, cannot send debug msg.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        print("DEBUG: Telegram send status:", resp.status_code, resp.text)
    except Exception as e:
        print("DEBUG: Telegram send failed:", e)

# Attempt import
try:
    from btc_scan import analyze, send_telegram
    print("DEBUG: Imported analyze() and send_telegram from btc_scan.py")
except Exception as e:
    print("ERROR: Importing from btc_scan failed:", e)
    traceback.print_exc()
    # Try to notify via telegram (best-effort)
    send_debug_telegram(f"btc_scan import failed: {e}")
    sys.exit(2)

def main():
    # Print some env/debug info
    print("DEBUG: TELEGRAM_BOT_TOKEN present?", bool(TELEGRAM_TOKEN))
    print("DEBUG: TELEGRAM_CHAT_ID present?", bool(TELEGRAM_CHAT_ID))
    print("DEBUG: pwd:", os.getcwd())
    print("DEBUG: python:", sys.executable)
    try:
        # quick test: tell Telegram that the runner started (so we know secrets work)
        send_debug_telegram("⚙️ GitHub Actions: run_once_debug started (debug msg).")
    except Exception as e:
        print("DEBUG: send_debug_telegram failed:", e)

    try:
        result = analyze()
        # show full repr of result
        print("DEBUG: analyze() returned:", repr(result))
        if result is None:
            print("ERROR: analyze() returned None. Sending debug Telegram.")
            send_debug_telegram("⚠️ analyze() returned None — check logs.")
            return 1
        # if analyze returns dict-like, send via send_telegram if available
        try:
            send_telegram(result)
            print("DEBUG: Called send_telegram(result) - done")
        except Exception as e:
            print("ERROR: send_telegram failed:", e)
            traceback.print_exc()
            # fallback: send plain debug message via HTTP
            send_debug_telegram(f"send_telegram exception: {e}")
            return 2
        return 0
    except Exception as e:
        print("EXCEPTION during analyze():", e)
        traceback.print_exc()
        send_debug_telegram(f"Exception in analyze(): {e}\nSee action logs.")
        return 3

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

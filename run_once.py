#!/usr/bin/env python3
# run_once.py
# Single-shot runner: imports analyze() from btc_scan and sends Telegram via env vars (robust)

import os, sys, traceback, requests, json

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

# read env secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_http(message_text):
    """Send plain text to Telegram using HTTP API (fallback sender used by run_once)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment.")
        return False, "no-token"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message_text}
    try:
        r = requests.post(url, json=payload, timeout=15)
        return (r.status_code == 200), r.text
    except Exception as e:
        return False, str(e)

# Try to import analyze
try:
    from btc_scan import analyze
    print("INFO: Imported analyze() from btc_scan.py")
except Exception as e:
    print("ERROR: could not import analyze() from btc_scan.py:", e)
    traceback.print_exc()
    # try to notify via Telegram that import failed (best-effort)
    ok, info = send_telegram_http(f"btc_scan import failed: {e}")
    print("Tried to notify via Telegram:", ok, info)
    sys.exit(2)

def main():
    try:
        # run analyze()
        result = analyze()
        print("INFO: analyze() returned:", repr(result))
        if not result:
            msg = "⚠️ analyze() returned None or empty — nothing to send."
            print(msg)
            send_telegram_http(f"BTC scanner: {msg}")
            return 1

        # build a short friendly message
        try:
            # If result is dict-like, format it; else stringify
            if isinstance(result, dict):
                price = result.get("price")
                score = result.get("score")
                verdict = result.get("verdict")
                signals = result.get("signals")
                msg = f"📊 BTC Update\n\n{{'price': {price}, 'score': {score}, 'verdict': '{verdict}', 'signals': {signals}}}"
            else:
                msg = f"📊 BTC Update\n\n{result}"
        except Exception as e:
            msg = f"📊 BTC Update\n\n{repr(result)}"

        ok, info = send_telegram_http(msg)
        print("INFO: Telegram send ok?", ok, "info:", info)
        if not ok:
            # if send failed, log full response
            print("ERROR: Telegram send failed:", info)
            return 3
        return 0

    except Exception as e:
        print("EXCEPTION in run_once:", e)
        traceback.print_exc()
        # try notify
        try:
            send_telegram_http(f"Exception in run_once: {e}\nSee action logs.")
        except Exception:
            pass
        return 4

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

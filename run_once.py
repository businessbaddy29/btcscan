#!/usr/bin/env python3
# run_once.py (robust; analyze() fallback -> CoinGecko)

import os, sys, traceback, requests, time, json

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_http(message_text):
    """Send plain text to Telegram using HTTP API (robust fallback)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return False, "no-token"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message_text}
    try:
        r = requests.post(url, json=payload, timeout=15)
        return (r.status_code == 200), r.text
    except Exception as e:
        return False, str(e)

# Try import analyze()
try:
    from btc_scan import analyze
    print("INFO: Imported analyze() from btc_scan.py")
except Exception as e:
    print("ERROR: could not import analyze() from btc_scan.py:", e)
    traceback.print_exc()
    send_telegram_http(f"btc_scan import failed: {e}")
    sys.exit(2)

def fetch_price_coingecko():
    """Simple fallback: get BTC price (USD) from CoinGecko."""
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids":"bitcoin","vs_currencies":"usd"}, timeout=10)
        r.raise_for_status()
        j = r.json()
        price = j.get("bitcoin", {}).get("usd")
        return price
    except Exception as e:
        print("CoinGecko fetch failed:", e)
        return None

def format_result_msg(result):
    try:
        if isinstance(result, dict):
            price = result.get("price")
            score = result.get("score")
            verdict = result.get("verdict")
            signals = result.get("signals")
            return f"📊 BTC Update\n\n{{'price': {price}, 'score': {score}, 'verdict': '{verdict}', 'signals': {signals}}}"
        else:
            return f"📊 BTC Update\n\n{repr(result)}"
    except Exception:
        return f"📊 BTC Update\n\n{repr(result)}"

def main():
    print("DEBUG: Starting run_once at", time.strftime("%Y-%m-%d %H:%M:%S"))
    # quick debug: confirm secrets presence
    print("DEBUG: TELEGRAM_TOKEN present?", bool(TELEGRAM_TOKEN))
    print("DEBUG: TELEGRAM_CHAT_ID present?", bool(TELEGRAM_CHAT_ID))

    try:
        result = analyze()
        print("DEBUG: analyze() returned:", repr(result))
    except Exception as e:
        print("ERROR: Exception when running analyze():", e)
        traceback.print_exc()
        send_telegram_http(f"Exception in analyze(): {e}\nSee Action logs.")
        return 3

    if not result:
        # fallback path: analyze returned None or empty
        print("WARN: analyze() returned None or empty -> using fallback price source.")
        price = fetch_price_coingecko()
        if price is not None:
            msg = f"📊 BTC Fallback Update\n\n{{'price': {price}, 'note': 'fallback: analyze() returned None'}}"
            ok, info = send_telegram_http(msg)
            print("INFO: Telegram fallback send ok?", ok, "info:", info)
            return 0 if ok else 4
        else:
            send_telegram_http("⚠️ BTC fallback failed: analyze() returned None and CoinGecko failed.")
            return 5

    # If we have a valid result object -> format and send
    msg = format_result_msg(result)
    ok, info = send_telegram_http(msg)
    print("INFO: Telegram send ok?", ok, "info:", info)
    if ok:
        return 0
    else:
        # try fallback message with price
        price = fetch_price_coingecko()
        if price is not None:
            fb = f"📊 BTC Fallback Update (after send error)\n\n{{'price': {price}, 'note': 'original send failed'}}"
            ok2, info2 = send_telegram_http(fb)
            print("INFO: fallback send ok?", ok2, "info:", info2)
            return 0 if ok2 else 6
        return 7

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

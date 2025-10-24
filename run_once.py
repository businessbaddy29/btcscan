#!/usr/bin/env python3
# run_once.py - pretty Telegram formatting (HTML), fallback-friendly

import os, sys, traceback, requests, time

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_html(html_text):
    """Send message using Telegram sendMessage with HTML parse_mode."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return False, "no-token"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
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
    send_telegram_html(f"<b>btc_scan import failed</b>\n<code>{e}</code>")
    sys.exit(2)

def coingecko_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids":"bitcoin","vs_currencies":"usd"}, timeout=10)
        r.raise_for_status()
        j = r.json()
        return float(j.get("bitcoin", {}).get("usd"))
    except Exception as e:
        print("CoinGecko fetch failed:", e)
        return None

def verdict_emoji(verdict_str):
    v = (verdict_str or "").upper()
    if "BUY" in v:
        return "🟢"
    if "SELL" in v:
        return "🔴"
    return "🟡"

def build_html_message(result, fallback=False):
    """
    Builds a nice HTML message. Uses bold labels and <pre> for monospace numeric block.
    """
    if not result or not isinstance(result, dict):
        # fallback simple message
        price = coingecko_price()
        if price is None:
            return "<b>📊 BTC Update</b>\n<pre>No price available</pre>"
        return f"<b>📊 BTC Fallback Update</b>\n<pre>price: {price:.2f} USD</pre>"

    price = result.get("price")
    score = result.get("score")
    verdict = result.get("verdict", "NEUTRAL / WAIT")
    signals = result.get("signals", {})

    emoji = verdict_emoji(verdict)

    # Format signals lines
    sig_lines = []
    order = ["trend","volume","rsi","funding","fear_greed","volatility"]
    for k in order:
        if k in signals:
            val = signals[k]
            try:
                val = float(val)
                s = f"{val:.3f}"
            except Exception:
                s = str(val)
            sig_lines.append(f"<b>{k.capitalize():10s}</b>: <code>{s}</code>")

    # Construct message
    header = "📊 <b>BTC Update</b>"
    if fallback:
        header = "📊 <b>BTC Fallback Update</b>"

    price_line = f"<b>Price:</b> <code>{price:.2f} USD</code>" if price is not None else "<b>Price:</b> <code>n/a</code>"
    score_line = f"<b>Score:</b> <code>{float(score):.3f}</code>" if score is not None else "<b>Score:</b> <code>n/a</code>"
    verdict_line = f"<b>Verdict:</b> {emoji} <b>{verdict}</b>"

    # join
    body = "\n".join([header, price_line, score_line, verdict_line, "", "<b>Signals</b>"] + sig_lines)
    # wrap small spacing via HTML pre-like block for signals readability
    return body

def main():
    print("DEBUG: Starting run_once at", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("DEBUG: TELEGRAM present?", bool(TELEGRAM_TOKEN), bool(TELEGRAM_CHAT_ID))

    try:
        result = analyze()
        print("DEBUG: analyze() returned:", repr(result))
    except Exception as e:
        print("ERROR: Exception in analyze()", e)
        traceback.print_exc()
        send_telegram_html(f"<b>Exception in analyze()</b>\n<code>{e}</code>")
        return 3

    if not result:
        # fallback path
        price_fb = coingecko_price()
        if price_fb is not None:
            msg = build_html_message({"price": price_fb, "score": 0.5, "verdict": "NEUTRAL / WAIT (fallback price)", "signals": {"trend":0.5,"volume":0.5,"rsi":0.5,"funding":0.5,"fear_greed":0.5,"volatility":0.5}}, fallback=True)
            ok, info = send_telegram_html(msg)
            print("INFO: Telegram fallback send ok?", ok, "info:", info)
            return 0 if ok else 4
        else:
            send_telegram_html("<b>⚠️ BTC fallback failed</b>\n<code>analyze returned None and CoinGecko failed</code>")
            return 5

    # Build and send nicely formatted message
    msg = build_html_message(result, fallback=False)
    ok, info = send_telegram_html(msg)
    print("INFO: Telegram send ok?", ok, "info:", info)
    if not ok:
        # try fallback price-only message
        price_fb = coingecko_price()
        if price_fb is not None:
            fbmsg = build_html_message({"price": price_fb, "score": 0.5, "verdict": "NEUTRAL / WAIT (fallback price)", "signals": {}}, fallback=True)
            ok2, info2 = send_telegram_html(fbmsg)
            print("INFO: fallback-only send ok?", ok2, "info:", info2)
            return 0 if ok2 else 6
        return 7

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

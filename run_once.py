#!/usr/bin/env python3
# run_once.py - robust single-shot runner with pretty Telegram HTML messages

import os
import sys
import traceback
import time
import requests

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

# environment secrets (do NOT hardcode)
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

# Try to import analyze from btc_scan
try:
    from btc_scan import analyze
    print("INFO: Imported analyze() from btc_scan.py")
except Exception as e:
    print("ERROR: could not import analyze() from btc_scan.py:", e)
    traceback.print_exc()
    # best-effort notify
    try:
        send_telegram_html(f"<b>btc_scan import failed</b>\n<code>{e}</code>")
    except Exception:
        pass
    sys.exit(2)

# Helper: coinGecko price fallback
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

# The pretty HTML builder with Hindi summary
def build_html_message(result, fallback=False):
    """
    Builds a nice HTML message. Uses bold labels and <code> for numbers.
    Also appends a short Hindi summary based on the score.
    """
    if not result or not isinstance(result, dict):
        price = None
        if isinstance(result, (int, float)):
            price = result
        if price is not None:
            return f"<b>📊 BTC Fallback Update</b>\n<pre>price: {price:.2f} USD</pre>\n\n<i>💬 डेटा सीमित है — यह fallback सूचना है।</i>"
        return "<b>📊 BTC Update</b>\n<pre>No price available</pre>\n\n<i>💬 डेटा उपलब्ध नहीं है।</i>"

    # safe number conversion
    def safe_num(x):
        try:
            return float(x)
        except Exception:
            return None

    price = safe_num(result.get("price"))
    score = safe_num(result.get("score"))
    verdict = result.get("verdict", "NEUTRAL / WAIT")
    signals = result.get("signals", {})

    # verdict emoji
    def verdict_emoji(vstr):
        v = (vstr or "").upper()
        if "BUY" in v:
            return "🟢"
        if "SELL" in v:
            return "🔴"
        return "🟡"

    emoji = verdict_emoji(verdict)

    header = "📊 <b>BTC Update</b>"
    if fallback:
        header = "📊 <b>BTC Fallback Update</b>"

    price_line = f"<b>Price:</b> <code>{price:.2f} USD</code>" if isinstance(price, float) else "<b>Price:</b> <code>n/a</code>"
    score_line = f"<b>Score:</b> <code>{score:.3f}</code>" if isinstance(score, float) else "<b>Score:</b> <code>n/a</code>"
    verdict_line = f"<b>Verdict:</b> {emoji} <b>{verdict}</b>"

    # signals in fixed order
    order = ["trend","volume","rsi","funding","fear_greed","volatility"]
    sig_lines = []
    for k in order:
        if k in signals:
            v = signals[k]
            try:
                vnum = float(v)
                sig_lines.append(f"<b>{k.capitalize():10s}</b>: <code>{vnum:.3f}</code>")
            except Exception:
                sig_lines.append(f"<b>{k.capitalize():10s}</b>: <code>{v}</code>")

    parts = [header, price_line, score_line, verdict_line, "", "<b>Signals</b>"] + sig_lines

    # Summary (Hindi) based on score
    summary = ""
    if isinstance(score, float):
        if score >= 0.6:
            summary = "📈 मार्केट मज़बूत है — खरीदारी का माहौल है।"
        elif score <= 0.4:
            summary = "📉 मार्केट कमजोर है — बिकवाली का दबाव है।"
        else:
            summary = "💬 मार्केट स्थिर है — अभी इंतज़ार करना बेहतर है।"
    else:
        summary = "💬 डेटा अधूरा है, कृपया थोड़ी देर बाद पुनः जाँच करें।"

    parts.append("")
    parts.append(f"<i>{summary}</i>")

    return "\n".join(parts)

def main():
    print("DEBUG: Starting run_once at", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("DEBUG: TELEGRAM present?", bool(TELEGRAM_TOKEN), bool(TELEGRAM_CHAT_ID))

    try:
        result = analyze()
        print("DEBUG: analyze() returned:", repr(result))
    except Exception as e:
        print("ERROR: Exception when running analyze():", e)
        traceback.print_exc()
        try:
            send_telegram_html(f"<b>Exception in analyze()</b>\n<code>{e}</code>")
        except Exception:
            pass
        return 3

    if not result:
        # fallback path: try CoinGecko price
        print("WARN: analyze() returned None or empty -> using fallback price.")
        price_fb = coingecko_price()
        if price_fb is not None:
            msg = build_html_message({"price": price_fb, "score": 0.5, "verdict": "NEUTRAL / WAIT (fallback price)",
                                      "signals": {"trend":0.5,"volume":0.5,"rsi":0.5,"funding":0.5,"fear_greed":0.5,"volatility":0.5}}, fallback=True)
            ok, info = send_telegram_html(msg)
            print("INFO: Telegram fallback send ok?", ok, "info:", info)
            return 0 if ok else 4
        else:
            send_telegram_html("<b>⚠️ BTC fallback failed</b>\n<code>analyze returned None and CoinGecko failed</code>")
            return 5

    # normal path: we have result dict
    msg = build_html_message(result, fallback=False)
    ok, info = send_telegram_html(msg)
    print("INFO: Telegram send ok?", ok, "info:", info)
    if ok:
        return 0
    else:
        # try fallback price if send failed
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

#!/usr/bin/env python3
# run_once.py - robust single-shot runner with pretty Telegram HTML messages
# Updated: support ALLOWED_CHAT_IDS (single secret, comma-separated) + backwards compatibility

import os
import sys
import traceback
import time
import requests

repo_root = os.path.dirname(__file__)
sys.path.insert(0, repo_root)

# environment secrets (do NOT hardcode)
# Prefer BOT_TOKEN and ALLOWED_CHAT_IDS; fallback to older names for compatibility
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS = os.environ.get("ALLOWED_CHAT_IDS")  # preferred single secret
GROUP_ID = os.environ.get("GROUP_ID") or os.environ.get("TELEGRAM_CHAT_ID")  # fallback
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # optional fallback
OWNER_ID = os.environ.get("OWNER_ID")      # optional

def send_telegram_html_for_chat(chat_id, html_text):
    """Send message to a specific chat_id using Telegram sendMessage with HTML parse_mode."""
    if not BOT_TOKEN or not chat_id:
        # don't print token; only indicate presence/absence
        print("ERROR: BOT_TOKEN or chat_id not set.")
        return False, "no-token-or-chat"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        # try to return parsed json when possible
        try:
            j = r.json()
            ok = j.get("ok", False)
            return ok, j
        except Exception:
            return (r.status_code == 200), r.text
    except Exception as e:
        return False, str(e)

# ---- New: parse ALLOWED_CHAT_IDS and unified send_to_targets ----
def parse_allowed_chat_ids():
    """
    Return list of chat ids (strings).
    Prefer ALLOWED_CHAT_IDS (comma-separated). Else fallback to GROUP_ID/CHANNEL_ID.
    """
    targets = []
    if ALLOWED_CHAT_IDS:
        for part in ALLOWED_CHAT_IDS.split(','):
            p = part.strip()
            if p:
                targets.append(p)
        return targets
    # fallback single values (old setup)
    if GROUP_ID:
        targets.append(GROUP_ID)
    if CHANNEL_ID and CHANNEL_ID != GROUP_ID:
        targets.append(CHANNEL_ID)
    return targets

def send_to_targets(html_text):
    """Send the html_text to configured targets from parse_allowed_chat_ids()."""
    targets = parse_allowed_chat_ids()
    if not targets:
        print("WARN: No targets configured in ALLOWED_CHAT_IDS or GROUP_ID/CHANNEL_ID.")
        return False, "no-targets"

    all_ok = True
    last_resp = None
    for t in targets:
        ok, resp = send_telegram_html_for_chat(t, html_text)
        print(f"INFO: send to {t} ok? {ok}")
        if not ok:
            all_ok = False
            last_resp = resp
    return all_ok, last_resp
# ---- end new block ----

# Try to import analyze from btc_scan
try:
    from btc_scan import analyze
    print("INFO: Imported analyze() from btc_scan.py")
except Exception as e:
    print("ERROR: could not import analyze() from btc_scan.py:", e)
    traceback.print_exc()
    # best-effort notify (use whatever token/chat is configured)
    try:
        send_to_targets(f"<b>btc_scan import failed</b>\n<code>{e}</code>")
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
    # avoid printing token values; only indicate presence
    print("DEBUG: BOT_TOKEN present?", bool(BOT_TOKEN), "ALLOWED_CHAT_IDS present?", bool(ALLOWED_CHAT_IDS), "GROUP_ID present?", bool(GROUP_ID), "CHANNEL_ID present?", bool(CHANNEL_ID))

    try:
        result = analyze()
        print("DEBUG: analyze() returned:", repr(result))
    except Exception as e:
        print("ERROR: Exception when running analyze():", e)
        traceback.print_exc()
        try:
            send_to_targets(f"<b>Exception in analyze()</b>\n<code>{e}</code>")
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
            ok, info = send_to_targets(msg)
            print("INFO: Telegram fallback send ok?", ok, "info:", info)
            return 0 if ok else 4
        else:
            send_to_targets("<b>⚠️ BTC fallback failed</b>\n<code>analyze returned None and CoinGecko failed</code>")
            return 5

    # normal path: we have result dict
    msg = build_html_message(result, fallback=False)
    ok, info = send_to_targets(msg)
    print("INFO: Telegram send ok?", ok, "info:", info)
    if ok:
        return 0
    else:
        # try fallback price if send failed
        price_fb = coingecko_price()
        if price_fb is not None:
            fbmsg = build_html_message({"price": price_fb, "score": 0.5, "verdict": "NEUTRAL / WAIT (fallback price)", "signals": {}}, fallback=True)
            ok2, info2 = send_to_targets(fbmsg)
            print("INFO: fallback-only send ok?", ok2, "info:", info2)
            return 0 if ok2 else 6
        return 7

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

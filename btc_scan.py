#!/usr/bin/env python3
"""
btc_scan.py
BTC scanner with robust network handling, CoinGecko fallback, and Telegram alerts.
Paste this file (replace the old one). Uses environment variables:
  TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID or TELEGRAM_CHATID
Configure BTC_POLL_SECS and BTC_LOCKFILE via env if you want to override defaults.
"""

import time
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import signal
import logging

# -------- Settings --------
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LIMIT = 100  # Number of klines to fetch
RSI_PERIOD = 14

# Signal thresholds
THRESHOLDS = {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "volume_multiplier": 1.5,
    "funding_high": 0.0005,
    "fear_greed_greedy": 75,
    "fear_greed_fearful": 25
}

# Weights for weighted score
WEIGHTS = {
    "trend": 1,
    "volume": 1,
    "rsi": 1,
    "funding": 0.5,
    "fear_greed": 0.5,
    "volatility": 0.5
}

# ---------- Logging ----------
LOG_PATH = os.path.join(os.path.dirname(__file__), "btc_scan.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# -------- Helpers --------
def safe_fetch(url, params=None, timeout=15, max_retries=3):
    """GET request with simple exponential backoff. Returns parsed JSON or raises."""
    backoff = 1.0
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.warning("Request failed (%s) attempt %d/%d: %s", url, attempt, max_retries, e)
            last_exc = e
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise last_exc

def fetch_coingecko_klines(symbol=SYMBOL, interval=INTERVAL, limit=LIMIT):
    """
    Fallback: use CoinGecko hourly market_chart to build a DataFrame similar to Binance klines.
    This is approximate (CoinGecko returns price points; we resample to hourly OHLC).
    """
    try:
        cg_id = "bitcoin"
        vs = "usd"
        # days param: pick enough days to cover 'limit' hours.
        days = max(1, int((limit * 1.0) / 24) + 1)
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
        params = {"vs_currency": vs, "days": days, "interval": "hourly"}
        j = safe_fetch(url, params=params, timeout=15, max_retries=2)
        prices = j.get("prices", [])
        volumes = j.get("total_volumes", [])
        if not prices:
            return None
        dfp = pd.DataFrame(prices, columns=["ts", "price"])
        dfp["ts"] = pd.to_datetime(dfp["ts"], unit="ms")
        dfp.set_index("ts", inplace=True)
        # hourly OHLC
        df_ohlc = dfp["price"].resample("1H").ohlc()
        vol_df = pd.DataFrame(volumes, columns=["ts", "volume"])
        vol_df["ts"] = pd.to_datetime(vol_df["ts"], unit="ms")
        vol_df.set_index("ts", inplace=True)
        vol_hour = vol_df["volume"].resample("1H").sum()
        df_ohlc["volume"] = vol_hour
        df_ohlc = df_ohlc.dropna()
        if len(df_ohlc) < 10:
            return None
        if len(df_ohlc) > limit:
            df_ohlc = df_ohlc.iloc[-limit:]
        df_ohlc = df_ohlc.reset_index().rename(columns={"ts": "close_time"})
        df_ohlc["open_time"] = df_ohlc["close_time"] - pd.Timedelta(hours=1)
        # Ensure numeric columns
        for c in ["open", "high", "low", "close", "volume"]:
            df_ohlc[c] = df_ohlc[c].astype(float)
        # Return DataFrame with columns similar to Binance processing expectations
        return df_ohlc[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    except Exception as e:
        logging.exception("CoinGecko fallback failed: %s", e)
        return None

def fetch_binance_klines(symbol=SYMBOL, interval=INTERVAL, limit=LIMIT):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        data = safe_fetch(url, params=params, timeout=15, max_retries=3)
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time","qav","num_trades","taker_base_vol","taker_quote_vol","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit='ms')
        df["close_time"] = pd.to_datetime(df["close_time"], unit='ms')
        numeric_cols = ["open","high","low","close","volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        return df
    except requests.exceptions.HTTPError as he:
        status = None
        try:
            status = he.response.status_code
        except Exception:
            pass
        logging.warning("Binance HTTPError: %s", status)
        if status in (451, 403, 429):
            logging.info("Trying CoinGecko fallback due to HTTP %s", status)
            df_f = fetch_coingecko_klines(symbol, interval, limit)
            if df_f is not None:
                return df_f
        raise
    except Exception as e:
        logging.warning("Binance fetch failed (%s) â€” attempting fallback", e)
        df_f = fetch_coingecko_klines(symbol, interval, limit)
        if df_f is not None:
            return df_f
        raise

def sma(series, window):
    return series.rolling(window=window).mean()

def compute_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_binance_funding_rate(symbol=SYMBOL):
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": 1}
    try:
        arr = safe_fetch(url, params=params, timeout=10, max_retries=2)
        if isinstance(arr, list) and len(arr) > 0:
            fr = float(arr[-1]["fundingRate"])
            timestamp = int(arr[-1]["fundingTime"])
            return fr, datetime.utcfromtimestamp(timestamp/1000.0)
    except Exception as e:
        logging.warning("Funding fetch failed: %s", e)
    return None, None

def fetch_fear_and_greed():
    url = "https://api.alternative.me/fng/"
    try:
        j = safe_fetch(url, timeout=10, max_retries=2)
        if "data" in j and len(j["data"])>0:
            latest = j["data"][0]
            value = int(latest["value"])
            classification = latest["value_classification"]
            timestamp = int(latest["timestamp"])
            return value, classification, datetime.utcfromtimestamp(timestamp)
    except Exception as e:
        logging.warning("Fear & Greed fetch failed: %s", e)
    return None, None, None

# -------- Main logic --------
def analyze():
    logging.info("Fetching klines from Binance/CoinGecko...")
    try:
        df = fetch_binance_klines()
    except Exception as e:
        logging.exception("Failed to fetch klines: %s", e)
        return None

    if df is None or df.empty:
        logging.error("No kline data available.")
        return None

    # unify: if close_time is index or column, ensure column exists
    if "close_time" not in df.columns and df.index.name is not None:
        df = df.reset_index().rename(columns={df.index.name: "close_time"})
    df.set_index("close_time", inplace=True)
    df.sort_index(inplace=True)

    # Ensure required numeric columns exist (CoinGecko fallback returns open/high/low/close/volume)
    for col in ["open","high","low","close","volume"]:
        if col not in df.columns:
            logging.error("Missing required column in kline df: %s", col)
            return None

    df["MA50"] = sma(df["close"], 50)
    df["MA200"] = sma(df["close"], 200)
    df["RSI14"] = compute_rsi(df["close"], RSI_PERIOD)
    df["vol_7avg"] = df["volume"].rolling(7).mean()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(latest["close"])
    ma50 = float(latest["MA50"]) if not pd.isna(latest["MA50"]) else float("nan")
    ma200 = float(latest["MA200"]) if not pd.isna(latest["MA200"]) else float("nan")
    rsi = float(latest["RSI14"]) if not pd.isna(latest["RSI14"]) else float("nan")
    vol = float(latest["volume"])
    vol7 = float(df["vol_7avg"].iloc[-1]) if not pd.isna(df["vol_7avg"].iloc[-1]) else 0.0
    volatility_14 = float(df["close"].pct_change().rolling(14).std().iloc[-1])

    logging.info("Time (UTC): %s", df.index[-1])
    logging.info("Price: %.2f USDT", price)
    logging.info("MA50: %.2f, MA200: %.2f", ma50 if not math.isnan(ma50) else float("nan"), ma200 if not math.isnan(ma200) else float("nan"))
    logging.info("RSI(14): %.2f", rsi if not math.isnan(rsi) else float("nan"))
    logging.info("Volume (24h): %f, 7-day avg: %f", vol, vol7)
    logging.info("14-day vol (std): %f", volatility_14)

    try:
        funding, fund_time = fetch_binance_funding_rate()
        logging.info("Latest funding rate (Binance futures): %s at %s UTC", funding, fund_time)
    except Exception as e:
        logging.warning("Funding rate fetch failed: %s", e)
        funding = None

    try:
        fg_value, fg_class, fg_time = fetch_fear_and_greed()
        logging.info("Fear & Greed: %s (%s) at %s", fg_value, fg_class, fg_time)
    except Exception as e:
        logging.warning("Fear & Greed fetch failed: %s", e)
        fg_value = None

    signals = {}

    # Trend signal
    if math.isnan(ma50) or math.isnan(ma200):
        trend_signal = 0.5
    else:
        if price > ma50 and price > ma200:
            trend_signal = 1.0
        elif price < ma50 and price < ma200:
            trend_signal = 0.0
        else:
            trend_signal = 0.5
    signals["trend"] = trend_signal

    # Volume signal
    if vol7 == 0 or np.isnan(vol7):
        volume_signal = 0.5
    else:
        mult = vol / vol7
        if mult >= THRESHOLDS["volume_multiplier"]:
            volume_signal = 1.0
        elif mult < 0.8:
            volume_signal = 0.0
        else:
            volume_signal = 0.5
    signals["volume"] = volume_signal

    # RSI signal
    if np.isnan(rsi):
        rsi_signal = 0.5
    else:
        if rsi >= THRESHOLDS["rsi_overbought"]:
            rsi_signal = 0.0
        elif rsi <= THRESHOLDS["rsi_oversold"]:
            rsi_signal = 1.0
        else:
            rsi_signal = 1 - ((rsi - THRESHOLDS["rsi_oversold"]) / (THRESHOLDS["rsi_overbought"] - THRESHOLDS["rsi_oversold"]))
            rsi_signal = max(0.0, min(1.0, rsi_signal))
    signals["rsi"] = rsi_signal

    # Funding signal
    if funding is None:
        funding_signal = 0.5
    else:
        if funding >= THRESHOLDS["funding_high"]:
            funding_signal = 0.0
        elif funding <= -THRESHOLDS["funding_high"]:
            funding_signal = 1.0
        else:
            funding_signal = 0.5 - (funding / (2*THRESHOLDS["funding_high"]))
            funding_signal = max(0.0, min(1.0, funding_signal))
    signals["funding"] = funding_signal

    # Fear & Greed signal
    if fg_value is None:
        fg_signal = 0.5
    else:
        if fg_value >= THRESHOLDS["fear_greed_greedy"]:
            fg_signal = 0.0
        elif fg_value <= THRESHOLDS["fear_greed_fearful"]:
            fg_signal = 1.0
        else:
            fg_signal = 1 - ((fg_value - THRESHOLDS["fear_greed_fearful"]) / (THRESHOLDS["fear_greed_greedy"] - THRESHOLDS["fear_greed_fearful"]))
            fg_signal = max(0.0, min(1.0, fg_signal))
    signals["fear_greed"] = fg_signal

    # Volatility signal
    vol_norm = min(0.1, volatility_14) / 0.1
    volatility_signal = 1 - vol_norm
    signals["volatility"] = volatility_signal

    # Weighted score
    total_weight = sum(WEIGHTS.values())
    score = 0.0
    for k,w in WEIGHTS.items():
        score += signals.get(k, 0.5) * w
    score = score / total_weight

    # Verdict
    if score >= 0.6:
        verdict = "BUY (probabilistic)"
    elif score <= 0.4:
        verdict = "SELL (probabilistic)"
    else:
        verdict = "NEUTRAL / WAIT"

    logging.info("--- SIGNALS ---")
    for k,v in signals.items():
        logging.info("%s: %.3f", k, v)
    logging.info("Weighted score: %.3f  => %s", score, verdict)

    # Build result object (use numpy floats if needed to preserve original output style)
    result = {
        "price": np.float64(price),
        "score": np.float64(score),
        "verdict": verdict,
        "signals": {k: (np.float64(v) if isinstance(v, float) else v) for k,v in signals.items()}
    }
    return result

# -------- Telegram alert (uses env vars) --------
def send_telegram_message_obj(result):
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHATID")
    if not token or not chat_id:
        logging.warning("Telegram token or chat_id not set; skipping send.")
        return
    msg = "ðŸ“Š BTC Update\n\n" + str(result)
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": msg}, timeout=15)
        logging.info("Telegram Response: %s", r.text)
    except Exception as e:
        logging.exception("Failed to send Telegram message: %s", e)

# ---------- RUNNER (final version) ----------
LOCKFILE = os.environ.get("BTC_LOCKFILE", "/tmp/btc_scan.lock")
POLL_SECS = int(os.environ.get("BTC_POLL_SECS", "3600"))   # default 1 hour
_running = True

def _signal_handler(signum, frame):
    global _running
    logging.info("Received signal %s, stopping...", signum)
    _running = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

def acquire_lock():
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r") as f:
                pid = int(f.read().strip() or 0)
            try:
                os.kill(pid, 0)
                logging.info("Lockfile exists and pid %s alive â€” exiting.", pid)
                return False
            except OSError:
                logging.info("Stale lockfile found, removing.")
                os.remove(LOCKFILE)
        except Exception:
            try:
                os.remove(LOCKFILE)
            except Exception:
                pass
    with open(LOCKFILE, "w") as f:
        f.write(str(os.getpid()))
    logging.info("Acquired lockfile %s with pid %s", LOCKFILE, os.getpid())
    return True

def release_lock():
    try:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)
            logging.info("Released lockfile.")
    except Exception as e:
        logging.exception("Failed to remove lockfile: %s", e)

def run(poll_interval=POLL_SECS):
    if not acquire_lock():
        return
    try:
        logging.info("Starting main run loop with poll_interval=%s", poll_interval)
        while _running:
            try:
                result = analyze()
                if result is not None:
                    send_telegram_message_obj(result)
                else:
                    logging.warning("analyze() returned None â€” skipping telegram send.")
            except Exception:
                logging.exception("Unexpected error in analyze/send cycle")
            # sleep but allow early exit
            slept = 0
            while _running and slept < poll_interval:
                time.sleep(1)
                slept += 1
    finally:
        release_lock()
        logging.info("Exited main run loop.")

if __name__ == "__main__":
    run()

import os
import time
from urllib.parse import quote
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS
from google import genai
import requests

app = Flask(__name__)
CORS(app)

APP_STARTED_AT = time.time()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
UPSTOX_ACCESS_TOKEN = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()

UPSTOX_MARKETS = {
    "nifty": {
        "name": "NIFTY 50",
        "instrument_key": "NSE_INDEX|Nifty 50",
    },
    "banknifty": {
        "name": "Bank Nifty",
        "instrument_key": "NSE_INDEX|Nifty Bank",
    },
}

UPSTOX_TIMEFRAMES = {
    "5m": ("minutes", 5),
    "15m": ("minutes", 15),
    "1h": ("hours", 1),
    "1d": ("days", 1),
}
DEMO_MARKETS = {
    "nifty": {
        "name": "NIFTY 50",
        "price": 24680.55,
        "open": 24592.20,
        "high": 24718.90,
        "low": 24540.10,
        "previous_close": 24528.50,
        "volume_ratio": 1.18,
        "rsi_14": 58.4,
        "ema_9": 24654.20,
        "ema_21": 24618.80,
        "ema_50": 24580.10,
        "vwap": 24620.40,
        "macd_histogram": 12.6,
        "atr_14": 118.0,
        "support": 24580.0,
        "resistance": 24760.0,
        "trend_5m": "bullish",
        "trend_15m": "bullish",
        "trend_1h": "neutral",
    },
    "banknifty": {
        "name": "Bank Nifty",
        "price": 55112.40,
        "open": 54940.50,
        "high": 55220.80,
        "low": 54888.10,
        "previous_close": 54886.30,
        "volume_ratio": 1.10,
        "rsi_14": 54.8,
        "ema_9": 55072.30,
        "ema_21": 55020.80,
        "ema_50": 54940.40,
        "vwap": 55035.60,
        "macd_histogram": 18.2,
        "atr_14": 248.0,
        "support": 54920.0,
        "resistance": 55250.0,
        "trend_5m": "bullish",
        "trend_15m": "neutral",
        "trend_1h": "bullish",
    },
}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


@app.get("/")
def home():
    return jsonify(
        {
            "service": "Indian Market AI Dashboard API",
            "status": "running",
            "uptime_seconds": round(time.time() - APP_STARTED_AT, 1),
            "message": "Research and paper-trading API only. No broker or real-money trading.",
        }
    )


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "indian-market-api",
            "time_utc": now_utc(),
        }
    )


def status_from_bool(value, bullish_text, bearish_text, neutral_text):
    if value > 0:
        return {
            "state": "bullish",
            "score": 1,
            "reason": bullish_text,
        }

    if value < 0:
        return {
            "state": "bearish",
            "score": -1,
            "reason": bearish_text,
        }

    return {
        "state": "neutral",
        "score": 0,
        "reason": neutral_text,
    }


def calculate_confirmation_engine(market):
    price = market["price"]
    open_price = market["open"]
    previous_close = market["previous_close"]
    rsi = market["rsi_14"]
    ema_9 = market["ema_9"]
    ema_21 = market["ema_21"]
    ema_50 = market["ema_50"]
    vwap = market["vwap"]
    macd_histogram = market["macd_histogram"]
    volume_ratio = market["volume_ratio"]
    atr = market["atr_14"]
    support = market["support"]
    resistance = market["resistance"]

    confirmations = []

    ema_signal = 0
    if price > ema_9 > ema_21 > ema_50:
        ema_signal = 1
    elif price < ema_9 < ema_21 < ema_50:
        ema_signal = -1

    confirmations.append(
        {
            "name": "EMA alignment",
            "weight": 2,
            **status_from_bool(
                ema_signal,
                "Price and EMA 9/21/50 are aligned bullish.",
                "Price and EMA 9/21/50 are aligned bearish.",
                "EMA alignment is mixed.",
            ),
        }
    )

    vwap_signal = 1 if price > vwap else -1 if price < vwap else 0
    confirmations.append(
        {
            "name": "VWAP position",
            "weight": 2,
            **status_from_bool(
                vwap_signal,
                "Price is trading above VWAP.",
                "Price is trading below VWAP.",
                "Price is at VWAP.",
            ),
        }
    )

    rsi_signal = 1 if rsi >= 55 else -1 if rsi <= 45 else 0
    confirmations.append(
        {
            "name": "RSI momentum",
            "weight": 1,
            **status_from_bool(
                rsi_signal,
                f"RSI {rsi:.1f} supports bullish momentum.",
                f"RSI {rsi:.1f} supports bearish momentum.",
                f"RSI {rsi:.1f} is neutral.",
            ),
        }
    )

    macd_signal = 1 if macd_histogram > 0 else -1 if macd_histogram < 0 else 0
    confirmations.append(
        {
            "name": "MACD momentum",
            "weight": 1,
            **status_from_bool(
                macd_signal,
                "MACD histogram is positive.",
                "MACD histogram is negative.",
                "MACD histogram is flat.",
            ),
        }
    )

    volume_signal = 1 if volume_ratio >= 1.05 else 0
    confirmations.append(
        {
            "name": "Volume participation",
            "weight": 1,
            **status_from_bool(
                volume_signal,
                f"Volume is {volume_ratio:.2f}x its reference average.",
                "Volume filter does not support a bearish setup by itself.",
                f"Volume is only {volume_ratio:.2f}x its reference average.",
            ),
        }
    )

    timeframe_values = {
        "bullish": 1,
        "bearish": -1,
        "neutral": 0,
    }

    timeframe_score = (
        timeframe_values[market["trend_5m"]]
        + timeframe_values[market["trend_15m"]]
        + timeframe_values[market["trend_1h"]]
    )

    confirmations.append(
        {
            "name": "Multi-timeframe trend",
            "weight": 2,
            **status_from_bool(
                1 if timeframe_score >= 2 else -1 if timeframe_score <= -2 else 0,
                "5m, 15m, and 1h trend alignment is bullish.",
                "5m, 15m, and 1h trend alignment is bearish.",
                "Timeframes are not fully aligned.",
            ),
        }
    )

    level_signal = 0
    midpoint = (support + resistance) / 2

    if price > midpoint and price < resistance:
        level_signal = 1
    elif price < midpoint and price > support:
        level_signal = -1

    confirmations.append(
        {
            "name": "Support and resistance context",
            "weight": 1,
            **status_from_bool(
                level_signal,
                "Price is in the upper half of its current research range.",
                "Price is in the lower half of its current research range.",
                "Price is at an important range midpoint or boundary.",
            ),
        }
    )

    weighted_score = sum(item["score"] * item["weight"] for item in confirmations)
    max_score = sum(item["weight"] for item in confirmations)
    bullish_count = sum(1 for item in confirmations if item["state"] == "bullish")
    bearish_count = sum(1 for item in confirmations if item["state"] == "bearish")

    change = price - previous_close
    change_percent = (change / previous_close) * 100

    decision = "WAIT"
    decision_reason = "Confirmations are mixed. Wait for a clearer aligned setup."

    if weighted_score >= 7 and bullish_count >= 5 and price < resistance:
        decision = "BUY SETUP"
        decision_reason = "Strong bullish confluence with a defined risk plan."
    elif weighted_score <= -7 and bearish_count >= 5 and price > support:
        decision = "SELL SETUP"
        decision_reason = "Strong bearish confluence with a defined risk plan."
    elif weighted_score >= 4:
        decision = "WAIT FOR BUY CONFIRMATION"
        decision_reason = "Bullish factors exist, but wait for stronger alignment or a clean breakout."
    elif weighted_score <= -4:
        decision = "WAIT FOR SELL CONFIRMATION"
        decision_reason = "Bearish factors exist, but wait for stronger alignment or a clean breakdown."

    risk_buffer = atr * 0.35

    if decision in {"BUY SETUP", "WAIT FOR BUY CONFIRMATION"}:
        entry_zone = {
            "from": round(max(price, vwap), 2),
            "to": round(max(price, vwap) + atr * 0.15, 2),
            "condition": "Use only after a confirmed bullish candle close or a successful retest.",
        }
        stop_loss = round(min(support, vwap) - risk_buffer, 2)
        risk = max(entry_zone["from"] - stop_loss, atr * 0.25)
        target_1 = round(entry_zone["from"] + risk, 2)
        target_2 = round(entry_zone["from"] + risk * 2, 2)
        exit_rule = "Exit if stop-loss is hit, price loses VWAP and EMA 21, or an opposite confirmed signal appears."
    elif decision in {"SELL SETUP", "WAIT FOR SELL CONFIRMATION"}:
        entry_zone = {
            "from": round(min(price, vwap) - atr * 0.15, 2),
            "to": round(min(price, vwap), 2),
            "condition": "Use only after a confirmed bearish candle close or a failed retest.",
        }
        stop_loss = round(max(resistance, vwap) + risk_buffer, 2)
        risk = max(stop_loss - entry_zone["to"], atr * 0.25)
        target_1 = round(entry_zone["to"] - risk, 2)
        target_2 = round(entry_zone["to"] - risk * 2, 2)
        exit_rule = "Exit if stop-loss is hit, price regains VWAP and EMA 21, or an opposite confirmed signal appears."
    else:
        entry_zone = {
            "from": None,
            "to": None,
            "condition": "No entry. Wait until multiple confirmations align.",
        }
        stop_loss = None
        target_1 = None
        target_2 = None
        exit_rule = "No position. Reassess after the next confirmed technical refresh."

    return {
        "market": market["name"],
        "updated_at": now_utc(),
        "price": price,
        "open": open_price,
        "high": market["high"],
        "low": market["low"],
        "previous_close": previous_close,
        "change": round(change, 2),
        "change_percent": round(change_percent, 2),
        "indicators": {
            "rsi_14": rsi,
            "ema_9": ema_9,
            "ema_21": ema_21,
            "ema_50": ema_50,
            "vwap": vwap,
            "macd_histogram": macd_histogram,
            "volume_ratio": volume_ratio,
            "atr_14": atr,
        },
        "levels": {
            "support": support,
            "resistance": resistance,
        },
        "timeframes": {
            "5m": market["trend_5m"],
            "15m": market["trend_15m"],
            "1h": market["trend_1h"],
        },
        "confirmations": confirmations,
        "decision": {
            "label": decision,
            "weighted_score": weighted_score,
            "max_score": max_score,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "reason": decision_reason,
        },
        "trade_plan": {
            "entry_zone": entry_zone,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "exit_rule": exit_rule,
        },
        "disclaimer": "Research and paper-trading only. This is not financial advice and does not place orders.",
    }
    

@app.get("/api/market/<market_key>")
def market_analysis(market_key):
    market_key = market_key.lower().strip()

    if market_key not in DEMO_MARKETS:
        return jsonify(
            {
                "ok": False,
                "error": "Unknown market. Use: nifty or banknifty.",
            }
        ), 404

    analysis = calculate_confirmation_engine(DEMO_MARKETS[market_key])

    return jsonify(
        {
            "ok": True,
            "data": analysis,
        }
    )


@app.get("/api/markets")
def all_markets_analysis():
    return jsonify(
        {
            "ok": True,
            "updated_at": now_utc(),
            "markets": {
                market_key: calculate_confirmation_engine(market)
                for market_key, market in DEMO_MARKETS.items()
            },
        }
    )
@app.get("/api/live/status")
def live_status():
    return jsonify(
        {
            "ok": True,
            "provider": "upstox",
            "token_configured": bool(UPSTOX_ACCESS_TOKEN),
            "mode": "intraday-candle-polling",
            "markets": list(UPSTOX_MARKETS.keys()),
            "supported_timeframes": list(UPSTOX_TIMEFRAMES.keys()),
            "note": (
                "Read-only market-data endpoint. This service does not place, "
                "modify, or cancel orders."
            ),
            "updated_at": now_utc(),
        }
    )


@app.get("/api/live/candles/<market_key>")
def live_candles(market_key):
    market_key = market_key.lower().strip()
    timeframe = request.args.get("timeframe", "5m").lower().strip()

    if market_key not in UPSTOX_MARKETS:
        return jsonify(
            {
                "ok": False,
                "error": "Unknown market. Use: nifty or banknifty.",
            }
        ), 404

    if timeframe not in UPSTOX_TIMEFRAMES:
        return jsonify(
            {
                "ok": False,
                "error": "Unsupported timeframe. Use: 5m, 15m, 1h, or 1d.",
            }
        ), 400

    if not UPSTOX_ACCESS_TOKEN:
        return jsonify(
            {
                "ok": False,
                "error": "Upstox access token is not configured on the server.",
            }
        ), 503

    market = UPSTOX_MARKETS[market_key]
    unit, interval = UPSTOX_TIMEFRAMES[timeframe]
    encoded_instrument_key = quote(market["instrument_key"], safe="")
    upstream_url = (
        "https://api.upstox.com/v3/historical-candle/intraday/"
        f"{encoded_instrument_key}/{unit}/{interval}"
    )

    try:
        upstream_response = requests.get(
            upstream_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
            },
            timeout=15,
        )

        if not upstream_response.ok:
            app.logger.warning(
                "Upstox candle request failed: status=%s",
                upstream_response.status_code,
            )

            return jsonify(
                {
                    "ok": False,
                    "provider": "upstox",
                    "error": "Upstox candle data is temporarily unavailable.",
                }
            ), 502

        upstream_data = upstream_response.json()
        raw_candles = upstream_data.get("data", {}).get("candles", [])

        candles = [
            {
                "time": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
            for row in reversed(raw_candles)
            if isinstance(row, list) and len(row) >= 6
        ]

        if not candles:
            return jsonify(
                {
                    "ok": False,
                    "provider": "upstox",
                    "error": "No candle data is available for this instrument and timeframe.",
                }
            ), 502

        latest = candles[-1]

        return jsonify(
            {
                "ok": True,
                "provider": "upstox",
                "mode": "intraday-candle-polling",
                "market": market["name"],
                "market_key": market_key,
                "instrument_key": market["instrument_key"],
                "timeframe": timeframe,
                "updated_at": now_utc(),
                "latest": latest,
                "candles": candles,
                "disclaimer": (
                    "Read-only market data for research and paper trading only. "
                    "No order placement is available."
                ),
            }
        )

    except requests.RequestException:
        app.logger.exception("Upstox candle request failed")

        return jsonify(
            {
                "ok": False,
                "provider": "upstox",
                "error": "Could not reach Upstox candle data right now.",
            }
        ), 502

@app.post("/api/gemini/review")
def gemini_chart_review():
    payload = request.get_json(silent=True) or {}

    market_key = str(payload.get("market", "")).lower().strip()
    timeframe = str(payload.get("timeframe", "5m")).lower().strip()

    if market_key not in DEMO_MARKETS:
        return jsonify(
            {
                "ok": False,
                "error": "Unknown market. Use: nifty or banknifty.",
            }
        ), 400

    allowed_timeframes = {"5m", "15m", "1h", "1d"}

    if timeframe not in allowed_timeframes:
        return jsonify(
            {
                "ok": False,
                "error": "Unsupported timeframe. Use: 5m, 15m, 1h, or 1d.",
            }
        ), 400

    if not GEMINI_API_KEY:
        return jsonify(
            {
                "ok": False,
                "error": "Gemini is not configured on the server.",
            }
        ), 503

    analysis = calculate_confirmation_engine(DEMO_MARKETS[market_key])

    prompt = f"""
You are a cautious Indian index-market research assistant. This is strictly for educational research
and paper trading only; do not give financial advice, guarantee an outcome, or tell the user to place
a real trade.

Review the following technical-engine snapshot for {analysis["market"]} on the {timeframe} timeframe.

Current price: {analysis["price"]}
Open / high / low: {analysis["open"]} / {analysis["high"]} / {analysis["low"]}
Decision: {analysis["decision"]["label"]}
Decision reason: {analysis["decision"]["reason"]}
Weighted score: {analysis["decision"]["weighted_score"]} of {analysis["decision"]["max_score"]}
RSI 14: {analysis["indicators"]["rsi_14"]}
EMA 9 / EMA 21 / EMA 50: {analysis["indicators"]["ema_9"]} / {analysis["indicators"]["ema_21"]} / {analysis["indicators"]["ema_50"]}
VWAP: {analysis["indicators"]["vwap"]}
MACD histogram: {analysis["indicators"]["macd_histogram"]}
Volume ratio: {analysis["indicators"]["volume_ratio"]}
Support / resistance: {analysis["levels"]["support"]} / {analysis["levels"]["resistance"]}
Entry zone: {analysis["trade_plan"]["entry_zone"]["from"]} to {analysis["trade_plan"]["entry_zone"]["to"]}
Entry condition: {analysis["trade_plan"]["entry_zone"]["condition"]}
Stop loss: {analysis["trade_plan"]["stop_loss"]}
Target 1 / Target 2: {analysis["trade_plan"]["target_1"]} / {analysis["trade_plan"]["target_2"]}
Exit rule: {analysis["trade_plan"]["exit_rule"]}

Write a concise Hinglish review with exactly these five headings:
1. Bias
2. Confirmation
3. Levels
4. Invalidation
5. Risk note

Rules:
- Mention that this is a demo-data research snapshot if relevant.
- Do not invent live news, live prices, option-chain data, candle patterns, or unprovided indicators.
- Do not suggest real-money trading or use imperative execution language.
- Keep the reply below 220 words.
"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        review_text = (response.text or "").strip()

        if not review_text:
            return jsonify(
                {
                    "ok": False,
                    "error": "Gemini returned an empty review. Please try again.",
                }
            ), 502

        return jsonify(
            {
                "ok": True,
                "market": analysis["market"],
                "timeframe": timeframe,
                "generated_at": now_utc(),
                "valid_for_seconds": 300,
                "review": review_text,
                "disclaimer": "Research and paper-trading only. Not financial advice and not a live-market recommendation.",
            }
        )

    except Exception:
        app.logger.exception("Gemini review request failed")

        return jsonify(
            {
                "ok": False,
                "error": "Gemini review is temporarily unavailable. Please try again later.",
            }
        ), 502
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

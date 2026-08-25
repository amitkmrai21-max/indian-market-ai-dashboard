import time
from datetime import datetime, timezone

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

APP_STARTED_AT = time.time()

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

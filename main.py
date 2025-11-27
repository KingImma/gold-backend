# backend/main.py
import threading
import time
from typing import Optional, List, Dict

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from broker_adapter import TwelveDataAdapter
from realtime_feed import RealtimeFeed, PriceMonitor
from historical_storage import HistoricalDataStore
import config


app = FastAPI(title="Gold Trading Bot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

broker: Optional[TwelveDataAdapter] = None
storage: Optional[HistoricalDataStore] = None
feed: Optional[RealtimeFeed] = None
monitor: Optional[PriceMonitor] = None


class TickerResponse(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float
    timestamp: int
    stats: Optional[Dict] = None


class Candle(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _db_update_loop():
    global broker, storage
    while True:
        try:
            if broker is not None and storage is not None:
                for symbol in config.SYMBOLS:
                    storage.update_from_broker(
                        broker, symbol, config.DEFAULT_INTERVAL, limit=10
                    )
        except Exception as e:
            print(f"⚠ DB update error: {e}")
        time.sleep(300)


@app.on_event("startup")
def startup():
    global broker, storage, feed, monitor

    print("=" * 60)
    print("Gold Trading Bot - API Server")
    print("=" * 60)

    print("\n[1/4] Connecting to broker API...")
    broker = TwelveDataAdapter(config.TWELVE_DATA_API_KEY)
    if not broker.connect():
        raise RuntimeError("Failed to connect to Twelve Data API")

    print("\n[2/4] Initializing database...")
    storage = HistoricalDataStore(config.DATABASE_PATH)

    print("\n[3/4] Initial historical sync...")
    for symbol in config.SYMBOLS:
        storage.update_from_broker(
            broker, symbol, config.DEFAULT_INTERVAL, config.HISTORICAL_LIMIT
        )

    print("\n[4/4] Starting realtime feed...")
    feed = RealtimeFeed(broker, config.SYMBOLS, interval=config.REALTIME_INTERVAL)
    monitor = PriceMonitor(feed)
    feed.start()

    t = threading.Thread(target=_db_update_loop, daemon=True)
    t.start()

    print("\n✓ Startup complete. API ready.")


@app.get("/api/ticker", response_model=TickerResponse)
def get_ticker():
    global monitor
    if monitor is None:
        raise RuntimeError("Monitor not initialized")

    last = monitor.get_last_ticker()
    if not last:
        raise RuntimeError("No ticker data yet")

    stats = monitor.get_stats()
    return TickerResponse(
        symbol=last["symbol"],
        price=last["price"],
        change=last.get("change", 0.0),
        change_percent=last.get("change_percent", 0.0),
        timestamp=last["timestamp"],
        stats=stats,
    )


@app.get("/api/ohlcv", response_model=List[Candle])
def get_ohlcv(limit: int = 200):
    global storage
    if storage is None:
        raise RuntimeError("Storage not initialized")

    symbol = config.SYMBOLS[0]
    interval = config.DEFAULT_INTERVAL
    df = storage.fetch_ohlcv(symbol, interval)
    if df is None or df.empty:
        return []

    df = df.tail(limit)
    candles: List[Candle] = []
    for ts, row in df.iterrows():
        candles.append(
            Candle(
                timestamp=int(ts.timestamp() * 1000),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return candles


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

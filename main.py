# backend/main.py
import threading
import time
from typing import Optional, List, Dict

import pandas as pd
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import  asynccontextmanager
from dotenv import load_dotenv

from broker_adapter import TwelveDataAdapter
from realtime_feed import RealtimeFeed, PriceMonitor
from historical_storage import HistoricalDataStore
import config

load_dotenv()
SYMBOLS = os.getenv("SYMBOLS")
TWELVEDATAKEY = os.getenv("TWELVE_DATA_API_KEY")
DB_URL = os.getenv("DATABASE_PATH")
HISTORICAL_LIM = os.getenv("HISTORICAL_LIMIT")
REALTIME_INT = os.getenv("REALTIME_INTERVAL")
DEFAULT_INT = os.getenv("DEFAULT_INTERVAL")
ALPHAKEY = os.getenv("ALPHA_VANTAGE_API_KEY")

@asynccontextmanager
async def startup(app: FastAPI):
    global broker, storage, feed, monitor

    print("=" * 60)
    print("Gold Trading Bot - API Server")
    print("=" * 60)

    print("\n[1/4] Connecting to broker API...")
    broker = TwelveDataAdapter(TWELVEDATAKEY)
    if not broker.connect():
        raise RuntimeError("Failed to connect to Twelve Data API")

    print("\n[2/4] Initializing database...")
    storage = HistoricalDataStore(DB_URL)

    print("\n[3/4] Initial historical sync...")
    for symbol in config.SYMBOLS:
        storage.update_from_broker(
            broker, symbol, DEFAULT_INT, HISTORICAL_LIM
        )

    print("\n[4/4] Starting realtime feed...")
    feed = RealtimeFeed(broker, SYMBOLS, interval=REALTIME_INT)
    monitor = PriceMonitor(feed)
    feed.start()

    t = threading.Thread(target=_db_update_loop, daemon=True)
    t.start()

    print("\n✓ Startup complete. API ready.")

    yield 

    print("Shutting down realtime feed...")
    feed.stop()


app = FastAPI(title="Gold Trading Bot API", version="1.0.0", lifespan=startup)

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
                for symbol in SYMBOLS:
                    storage.update_from_broker(
                        broker, symbol, DEFAULT_INT, limit=10
                    )
        except Exception as e:
            print(f"⚠ DB update error: {e}")
        time.sleep(300)



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

    symbol = SYMBOLS[0]
    interval = DEFAULT_INT
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

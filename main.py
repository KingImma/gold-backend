# backend/main.py
import threading
import time
from typing import Optional, List, Dict

import pandas as pd
import os
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from firebase_admin import auth

from broker_adapter import TwelveDataAdapter
from realtime_feed import RealtimeFeed, PriceMonitor
from historical_storage import HistoricalDataStore
from strategy import EmaCross, RsiStrategy 
from auth import verify_firebase_token
import config

load_dotenv()

# Configuration
SYMBOLS = config.SYMBOLS
TWELVEDATAKEY = os.getenv("TWELVE_DATA_API_KEY", config.TWELVE_DATA_API_KEY)
DB_URL = os.getenv("DATABASE_PATH", config.DATABASE_PATH)
HISTORICAL_LIM = config.HISTORICAL_LIMIT
REALTIME_INT = config.REALTIME_INTERVAL
DEFAULT_INT = config.DEFAULT_INTERVAL


@asynccontextmanager
async def startup(app: FastAPI):
    global broker, storage, feed, monitor, strategy, rsi_strategy, last_bar_ts_map, last_signals

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
    for symbol in SYMBOLS:
        storage.update_from_broker(
            broker, symbol, DEFAULT_INT, HISTORICAL_LIM
        )

    print("\n[4/4] Starting realtime feed...")
    feed = RealtimeFeed(broker, SYMBOLS, interval=REALTIME_INT)
    monitor = PriceMonitor(feed)
    feed.start()

    # Initialize strategies
    strategy = EmaCross(symbol=SYMBOLS[0], fast=20, slow=50)
    rsi_strategy = RsiStrategy(symbol=SYMBOLS[0])
    last_bar_ts_map = {}
    last_signals = []

    # Start background monitoring thread
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

# Global state variables
broker: Optional[TwelveDataAdapter] = None
storage: Optional[HistoricalDataStore] = None
feed: Optional[RealtimeFeed] = None
monitor: Optional[PriceMonitor] = None
strategy: Optional[EmaCross] = None
rsi_strategy: Optional[RsiStrategy] = None
last_bar_ts_map: Dict[str, int] = {}
last_signals: List[Dict] = []


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

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


def _db_update_loop():
    """Background thread that updates database and evaluates strategies"""
    global broker, storage, strategy, rsi_strategy, last_bar_ts_map, last_signals
    
    while True:
        try:
            if broker is not None and storage is not None:
                for symbol in SYMBOLS:
                    stored = storage.update_from_broker(
                        broker, symbol, DEFAULT_INT, limit=10
                    )
                    # Evaluate strategies on new bars
                    if stored and strategy is not None and rsi_strategy is not None:
                        df = storage.fetch_ohlcv(symbol, DEFAULT_INT)
                        if df is not None and not df.empty:
                            last_ts = int(df.index[-1].timestamp() * 1000)
                            if last_bar_ts_map.get(symbol) != last_ts:
                                last_bar_ts_map[symbol] = last_ts

                                print(f"\n📊 Evaluating new candle at {last_ts}")
                                print(f"   Close: ${df['close'].iloc[-1]:.2f}")
                                
                                ema_sigs = strategy.on_bar(df.tail(200))
                                rsi_sigs = rsi_strategy.on_bar(df.tail(200))

                                if not ema_sigs and not rsi_sigs:
                                    print(f"   ℹ️ No signals - conditions not met")
                                
                                all_signals = ema_sigs + rsi_sigs
                                
                                if all_signals:
                                    print(f"\n🚨 SIGNALS DETECTED at {last_ts}:")
                                    for s in all_signals:
                                        print(f"  → {s.side.value} {s.symbol} (confidence: {getattr(s, 'confidence', 1.0)})")
                                
                                last_signals = [
                                    {
                                        "symbol": s.symbol,
                                        "side": s.side.value,
                                        "confidence": getattr(s, "confidence", 1.0),
                                        "ts": last_ts,
                                    }
                                    for s in all_signals
                                ]
        except Exception as e:
            print(f"⚠ DB update error: {e}")
        time.sleep(300)  # Check every 5 minutes


@app.get("/api/ticker", response_model=TickerResponse)
def get_ticker():
    """Get the latest real-time ticker data"""
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
    """Get historical OHLCV candlestick data"""
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

@app.post("/api/signup")
def signup(user: SignupRequest):
    try:
        firebase_user = auth.create_user(
            email= user.email,
            password= user.password,
            display_name = user.display_name
        )
        custom_token = auth.create_custom_token(firebase_user.uid)
        return{
            "uid": firebase_user.uid,
            "email": firebase_user.email,
            "token": custom_token.decode("utf-8"),
            "message": "User created successfully"
        }
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="Email already exists")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/profile")
async def profile(user=Depends(verify_firebase_token)):
    return{
        "uid": user["uid"],
        "email": user.get("email"),
        "provider": user.get("firebase", {}).get("sign_in_provider")
    }

@app.get("/api/signals")
def get_signals():
    """Get the latest trading signals from all strategies"""
    global last_signals
    return last_signals or []


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

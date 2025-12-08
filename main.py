# backend/main.py
# backend/main.py
import threading
import time
from typing import Optional, List, Dict

import pandas as pd
import os
import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from firebase_admin import auth

from broker_adapter import TwelveDataAdapter
from models import Order, OrderType, Side
from execution import PaperBroker , ExecutionBroker  # contains ExecutionBroker class
from realtime_feed import RealtimeFeed, PriceMonitor
from historical_storage import HistoricalDataStore
from strategy import EmaCross, RsiStrategy 
from auth import verify_firebase_token
import config

load_dotenv()

# Configuration
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
FIREBASE_LOGIN_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
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
    # Initialize paper broker
    paper_broker = PaperBroker(cash=100000.0, fee_rate=0.001, slippage_pct=0.0005)

    # Initialize live broker adapter
    adapter = TwelveDataAdapter(TWELVEDATAKEY)

    # Initialize execution broker (paper + live)
    broker = ExecutionBroker(paper_broker=paper_broker, adapter=adapter)
    if not broker.connected:
        print("⚠ Warning: Falling back to paper trading only")

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
broker: Optional[ExecutionBroker] = None
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

class AuthRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class TokenLogin(BaseModel):
    id_token: str

class OrderRequest(BaseModel):
    symbol: str
    side: str
    qty: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


def _db_update_loop():
    """Background thread: updates database, evaluates strategies, and executes trades with risk management"""
    global broker, storage, strategy, rsi_strategy, last_bar_ts_map, last_signals
    
    # Default trade settings
    DEFAULT_TRADE_QTY = 1.0
    DEFAULT_STOP_LOSS_PCT = 0.01  # 1% stop loss
    DEFAULT_TAKE_PROFIT_PCT = 0.02  # 2% take profit

    # Initialize risk manager (customize as needed)
    risk_manager = RiskManager(max_position_size=5.0, max_exposure_pct=0.05)

    while True:
        try:
            if broker is not None and storage is not None:
                for symbol in SYMBOLS:
                    stored = storage.update_from_broker(
                        broker, symbol, DEFAULT_INT, limit=10
                    )
                    if not stored:
                        continue

                    df = storage.fetch_ohlcv(symbol, DEFAULT_INT)
                    if df is None or df.empty:
                        continue

                    last_ts = int(df.index[-1].timestamp() * 1000)
                    if last_bar_ts_map.get(symbol) == last_ts:
                        continue
                    last_bar_ts_map[symbol] = last_ts

                    print(f"\n📊 Evaluating new candle for {symbol} at {last_ts}")
                    print(f"   Close: ${df['close'].iloc[-1]:.2f}")

                    # Get signals
                    ema_sigs = strategy.on_bar(df.tail(200)) if strategy else []
                    rsi_sigs = rsi_strategy.on_bar(df.tail(200)) if rsi_strategy else []
                    all_signals = ema_sigs + rsi_sigs

                    if not all_signals:
                        print("   ℹ️ No signals - conditions not met")
                        continue

                    for sig in all_signals:
                        side = sig.side
                        price = df['close'].iloc[-1]
                        qty = getattr(sig, "qty", DEFAULT_TRADE_QTY)

                        # Risk check: allow trade only if RiskManager permits
                        if not risk_manager.can_enter_trade(symbol, side, qty, price):
                            print(f"  ⚠ Trade skipped due to risk limits: {side.value} {symbol} | Qty: {qty}")
                            continue

                        # Calculate stop loss / take profit
                        if side == Side.BUY:
                            stop_loss = price * (1 - DEFAULT_STOP_LOSS_PCT)
                            take_profit = price * (1 + DEFAULT_TAKE_PROFIT_PCT)
                        else:
                            stop_loss = price * (1 + DEFAULT_STOP_LOSS_PCT)
                            take_profit = price * (1 - DEFAULT_TAKE_PROFIT_PCT)

                        order = Order(
                            symbol=sig.symbol,
                            side=side,
                            qty=qty,
                            price=None,  # market order
                            order_type=OrderType.MARKET,
                            ts=int(time.time() * 1000)
                        )

                        trade = broker.submit_order(
                            order,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )

                        # Update trailing stops if enabled
                        if risk_manager.trailing_stop_enabled:
                            broker.update_trailing_stops({symbol: price}, risk_manager)

                        print(f"  🚀 Executed {side.value} order: {trade.symbol} | Qty: {trade.qty} | Price: {trade.price:.2f} | SL: {stop_loss:.2f} | TP: {take_profit:.2f}")

                    # Save last signals for API
                    last_signals[:] = [
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
def signup(user: AuthRequest):
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
    

@app.post("/api/login1")
def login(user: AuthRequest):
        payload = {
            "email": user.email,
            "password": user.password,
            "display_name": user.display_name,
            "returnSecureToken": True
        }

        response = requests.post(FIREBASE_LOGIN_URL, json=payload)
        if response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        result = response.json()
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"]["message"])
        return {
            "id_token": result["idToken"],
            "refresh_token": result["refreshToken"],
            "expires_in": result["expiresIn"],
            "email": result.get("email"),
            "display_name": result.get("dislpay_name"),
            "local_id": result.get("localId")
        }

@app.post("/api/login2")
def login_user(data: TokenLogin):
    try:
        decoded = auth.verify_id_token(data.id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired Firebase Token")
    
    return {
        "uid": decoded["uid"],
        "email": decoded.get("email"),
        "name": decoded.get("name"),
        "provider": decoded.get("firebase", {}).get("sign_in_provider")
    }

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

@app.post("/api/order")
def place_order(req: OrderRequest):
    global broker
    if broker is None:
        raise RuntimeError("Broker not initialized")

    side = Side.BUY if req.side.upper() == "BUY" else Side.SELL
    order = Order(
        symbol=req.symbol,
        side=side,
        qty=req.qty,
        price=None,  # use current market price
        order_type=OrderType.MARKET,
        ts=int(time.time() * 1000)
    )

    trade = broker.submit_order(order, stop_loss=req.stop_loss, take_profit=req.take_profit)
    return {
        "symbol": trade.symbol,
        "side": trade.side.value,
        "qty": trade.qty,
        "price": trade.price,
        "fee": trade.fee,
        "timestamp": trade.ts
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

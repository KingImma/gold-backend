## backend/main.py
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
from execution import PaperBroker, ExecutionBroker
from historical_storage import HistoricalDataStore
from strategy import EmaCross, RsiStrategy 
from risk import RiskManager
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

# Global state variables
market_broker: Optional[TwelveDataAdapter] = None
execution_broker: Optional[ExecutionBroker] = None
storage: Optional[HistoricalDataStore] = None
strategy: Optional[EmaCross] = None
rsi_strategy: Optional[RsiStrategy] = None
last_bar_ts_map: Dict[str, int] = {}
last_signals: List[Dict] = []
risk_manager: Optional[RiskManager] = None

# =========================
# FastAPI app with startup
# =========================
@asynccontextmanager
async def startup(app: FastAPI):
    global market_broker, execution_broker, storage, strategy, rsi_strategy, risk_manager

    print("=" * 60)
    print("Gold Trading Bot - API Server")
    print("=" * 60)

    # 1️⃣ Market Broker (Price fetching)
    print("\n[1/4] Connecting to market broker API...")
    market_broker = TwelveDataAdapter(TWELVEDATAKEY)
    if not market_broker.connect():
        raise RuntimeError("Failed to connect to Twelve Data API")

    # 2️⃣ Execution Broker
    print("\n[2/4] Initializing execution broker...")
    paper_broker = PaperBroker(cash=100000.0, fee_rate=0.001)

# Use your TwelveDataAdapter as the broker adapter
    adapter = TwelveDataAdapter(TWELVEDATAKEY)

# Now initialize ExecutionBroker properly
    execution_broker = ExecutionBroker(paper_broker=PaperBroker, adapter=adapter)
    
    # 3️⃣ Risk Manager
    print("\n[3/4] Initializing risk manager...")
    risk_manager = RiskManager()  # configure limits if needed here

    # 4️⃣ Database
    print("\n[4/4] Initializing database...")
    storage = HistoricalDataStore(DB_URL)
    for symbol in SYMBOLS:
        storage.update_from_broker(market_broker, symbol, DEFAULT_INT, HISTORICAL_LIM)

    # Initialize strategies
    strategy = EmaCross(symbol=SYMBOLS[0], fast=20, slow=50)
    rsi_strategy = RsiStrategy(symbol=SYMBOLS[0])

    # Start background update loop
    t = threading.Thread(target=_db_update_loop, daemon=True)
    t.start()

    print("\n✓ Startup complete. API ready.")
    yield
    print("Shutting down...")

# =========================
# FastAPI App
# =========================
app = FastAPI(title="Gold Trading Bot API", version="1.0.0", lifespan=startup)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Background loop
# =========================
def _db_update_loop():
    """Background thread: update DB, evaluate signals, place trades"""
    global market_broker, execution_broker, storage, strategy, rsi_strategy, last_bar_ts_map, last_signals, risk_manager
    
    while True:
        try:
            for symbol in SYMBOLS:
                # 1️⃣ Update historical bars
                storage.update_from_broker(market_broker, symbol, DEFAULT_INT, limit=10)
                
                df = storage.fetch_ohlcv(symbol, DEFAULT_INT)
                if df is None or df.empty:
                    continue
                
                last_ts = int(df.index[-1].timestamp() * 1000)
                if last_bar_ts_map.get(symbol) == last_ts:
                    continue
                
                last_bar_ts_map[symbol] = last_ts
                print(f"\n📊 New candle at {last_ts} | Close: ${df['close'].iloc[-1]:.2f}")
                
                # 2️⃣ Evaluate strategies
                ema_signals = strategy.on_bar(df.tail(200))
                rsi_signals = rsi_strategy.on_bar(df.tail(200))
                all_signals = ema_signals + rsi_signals
                
                if all_signals:
                    print(f"🚨 Signals detected for {symbol}:")
                    for s in all_signals:
                        print(f"  → {s.side.value} {s.symbol} (confidence={getattr(s,'confidence',1.0)})")
                    
                    # 3️⃣ Place trades if allowed by risk manager
                    for signal in all_signals:
                        if not risk_manager.is_trade_allowed(symbol, signal.side):
                            print(f"⚠ Trade blocked by risk manager: {signal.side.value} {symbol}")
                            continue
                        
                        # Use last close price for market execution
                        last_price = df['close'].iloc[-1]
                        trade = execution_broker.submit_order(
                            order_signal=signal,
                            stop_loss=None,  # optionally configure
                            take_profit=None
                        )
                        print(f"✅ Trade executed: {trade.side.value} {trade.symbol} qty={trade.qty} at ${trade.price}")
                
                last_signals = [
                    {
                        "symbol": s.symbol,
                        "side": s.side.value,
                        "confidence": getattr(s, "confidence", 1.0),
                        "ts": last_ts
                    } for s in all_signals
                ]

        except Exception as e:
            print(f"⚠ DB update error: {e}")
        
        time.sleep(300)  # 5 min interval

# =========================
# FastAPI Endpoints
# =========================
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

@app.get("/api/ticker", response_model=TickerResponse)
def get_ticker():
    last = market_broker.fetch_ticker(SYMBOLS[0])
    return TickerResponse(
        symbol=last["symbol"],
        price=last["price"],
        change=last.get("change", 0.0),
        change_percent=last.get("change_percent", 0.0),
        timestamp=last["timestamp"],
        stats=execution_broker.get_stats({last["symbol"]: last["price"]}),
    )

@app.get("/api/ohlcv", response_model=List[Candle])
def get_ohlcv(limit: int = 200):
    df = storage.fetch_ohlcv(SYMBOLS[0], DEFAULT_INT)
    if df is None or df.empty:
        return []
    
    df = df.tail(limit)
    return [
        Candle(
            timestamp=int(ts.timestamp() * 1000),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"])
        )
        for ts, row in df.iterrows()
    ]

@app.get("/api/signals")
def get_signals():
    return last_signals or []

# =========================
# Auth endpoints unchanged
# =========================
@app.post("/api/signup")
def signup(user: AuthRequest):
    try:
        firebase_user = auth.create_user(
            email=user.email,
            password=user.password,
            display_name=user.display_name
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
        raise HTTPException(status_code=401, detail="Invalid email or password")
    result = response.json()
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"]["message"])
    return {
        "id_token": result["idToken"],
        "refresh_token": result["refreshToken"],
        "expires_in": result["expiresIn"],
        "email": result.get("email"),
        "display_name": result.get("display_name"),
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

# =========================
# Run app
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

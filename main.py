## backend/main.py
## backend/main.py
import threading
import time
from typing import Optional, List, Dict
from urllib.parse import urlencode

import pandas as pd
import os
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from firebase_admin import auth

from broker_adapter import TwelveDataAdapter, SaxoAdapter
from execution import ExecutionBroker, PaperBroker
from historical_storage import HistoricalDataStore
from models import Order, OrderType
from strategy import EmaCross, RsiStrategy
from risk import RiskManager
from auth import verify_firebase_token
import config
from strategy_engine import StrategyEngine

load_dotenv()

# =========================
# Configuration
# =========================
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
FIREBASE_LOGIN_URL = (
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    f"?key={FIREBASE_API_KEY}"
)
SYMBOLS = config.SYMBOLS
TWELVEDATAKEY = os.getenv("TWELVE_DATA_API_KEY", config.TWELVE_DATA_API_KEY)

DB_URL = os.getenv("DATABASE_PATH", config.DATABASE_PATH)
HISTORICAL_LIM = config.HISTORICAL_LIMIT
REALTIME_INT = config.REALTIME_INTERVAL
DEFAULT_INT = config.DEFAULT_INTERVAL

# =========================
# Saxo config (simulation env)
# =========================
SAXO_APP_KEY = os.getenv("SAXO_API_KEY", getattr(config, "SAXO_API_KEY", ""))
SAXO_APP_SECRET = os.getenv("SAXO_APP_SECRET", getattr(config, "SAXO_APP_SECRET", ""))
SAXO_REDIRECT_URI = os.getenv(
    "SAXO_REDIRECT_URL",
    getattr(config, "SAXO_REDIRECT_URL", "http://localhost:8000/saxo/callback"),
)

SAXO_AUTH_BASE = "https://sim.logonvalidation.net"
SAXO_TOKEN_URL = f"{SAXO_AUTH_BASE}/token"
SAXO_AUTH_URL = f"{SAXO_AUTH_BASE}/authorize"
SAXO_OPENAPI_BASE = "https://gateway.saxobank.com/sim/openapi"

# From /port/v1/clients/me
SAXO_CLIENT_KEY = "KGxsYNCkMnbb4CB-025rKQ=="
SAXO_DEFAULT_ACCOUNT_KEY = "KGxsYNCkMnbb4CB-025rKQ=="
SAXO_CLIENT_ID = "21625769"

# Gold instrument is XAUUSD with UIC 8176 (in your SIM universe).
# AssetType here assumes CFD on gold; change to "FxSpot" if your 8176 instrument is spot.[web:171][web:105]
SAXO_UIC_MAP: Dict[str, int] = {
    "XAUUSD": 8176,
}
SAXO_ASSET_TYPE_MAP: Dict[str, str] = {
    "XAUUSD": "CfdOnCommodity",  # or "FxSpot" if 8176 is spot XAUUSD in your account
}

# For dev: in-memory Saxo tokens
saxo_tokens: Dict[str, str] = {}

# =========================
# Global state
# =========================
market_broker: Optional[TwelveDataAdapter] = None
execution_broker: Optional[ExecutionBroker] = None
storage: Optional[HistoricalDataStore] = None
strategy_engine: Optional[StrategyEngine] = None
last_bar_ts_map: Dict[str, int] = {}
last_signals: List[Dict] = []
risk_manager: Optional[RiskManager] = None

# =========================
# FastAPI startup
# =========================
@asynccontextmanager
async def startup(app: FastAPI):
    global market_broker, execution_broker, storage, strategy_engine, risk_manager

    print("=" * 60)
    print("Gold Trading Bot - API Server (Saxo SIM Trading)")
    print("=" * 60)

    # 1️⃣ Market Broker
    print("\n[1/4] Connecting to market data broker...")
    market_broker = TwelveDataAdapter(TWELVEDATAKEY)
    if not market_broker.connect():
        raise RuntimeError("Failed to connect to Twelve Data API")

    # 2️⃣ Execution Broker (Saxo)
    print("\n[2/4] Connecting to Saxo trading...")

    access_token = saxo_tokens.get("access_token")
    if not access_token:
        print("✗ No Saxo access token in memory. Call /saxo/login and /saxo/callback first.")

    saxo_adapter = SaxoAdapter(
        access_token=access_token or "",
        account_key=SAXO_DEFAULT_ACCOUNT_KEY,
        uic_map=SAXO_UIC_MAP,
        asset_type_map=SAXO_ASSET_TYPE_MAP,
    )

    if access_token:
        if not saxo_adapter.connect():
            raise RuntimeError("Failed to connect to Saxo OpenAPI")

    # Paper broker for PnL tracking
    paper_broker = PaperBroker()
    execution_broker = ExecutionBroker(paper_broker=paper_broker, adapter=saxo_adapter)

    # 3️⃣ Risk manager
    print("\n[3/4] Initializing risk manager...")
    risk_manager = RiskManager()

    # 4️⃣ Database
    print("\n[4/4] Initializing historical database...")
    storage = HistoricalDataStore(DB_URL)
    for symbol in SYMBOLS:
        storage.update_from_broker(market_broker, symbol, DEFAULT_INT, HISTORICAL_LIM)

    # Strategy engine
    global strategy_engine
    strategy_engine = StrategyEngine(
        symbol=SYMBOLS[0],
        storage=storage,
        execution_broker=execution_broker,
        risk_manager=risk_manager,
        interval=DEFAULT_INT,
        min_confidence=0.6,
    )

    t = threading.Thread(target=_db_update_loop, daemon=True)
    t.start()

    print("\n✓ Startup complete. API ready.")
    yield
    print("Shutting down...")


app = FastAPI(title="Gold Trading Bot API", version="1.0.0", lifespan=startup)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Background update loop
# =========================
def _db_update_loop():
    global execution_broker, storage, strategy_engine, last_bar_ts_map, last_signals, risk_manager

    while True:
        try:
            if (
                execution_broker is not None
                and storage is not None
                and strategy_engine is not None
            ):
                for symbol in SYMBOLS:
                    stored = storage.update_from_broker(
                        market_broker, symbol, DEFAULT_INT, limit=10
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
                    print(
                        f"\n📊 New candle at {last_ts} | Close: ${df['close'].iloc[-1]:.2f}"
                    )

                    trade = strategy_engine.generate_and_execute()

                    if trade:
                        last_signals = [
                            {
                                "symbol": trade.symbol,
                                "side": trade.side.value,
                                "confidence": 1.0,
                                "ts": last_ts,
                            }
                        ]
                    else:
                        last_signals = []

        except Exception as e:
            print(f"⚠ DB update loop error: {e}")

        time.sleep(300)

# =========================
# Models
# =========================
class TickerResponse(BaseModel):
    symbol: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
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

# =========================
# Saxo OAuth endpoints
# =========================
@app.get("/saxo/login")
def saxo_login():
    params = {
        "response_type": "code",
        "client_id": SAXO_APP_KEY,
        "redirect_uri": SAXO_REDIRECT_URI,
        "state": "xyz123",
    }
    url = f"{SAXO_AUTH_URL}?{urlencode(params)}"
    return {"auth_url": url}


@app.get("/saxo/callback")
def saxo_callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        return {"status": "error", "error": error}

    if not code:
        return {"status": "error", "error": "Missing authorization code"}

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SAXO_REDIRECT_URI,
        "client_id": SAXO_APP_KEY,
        "client_secret": SAXO_APP_SECRET,
    }

    r = requests.post(SAXO_TOKEN_URL, data=data)
    if r.status_code != 200:
        return {
            "status": "error",
            "error": "Token request failed",
            "details": r.text,
        }

    token_data = r.json()
    saxo_tokens["access_token"] = token_data.get("access_token")
    saxo_tokens["refresh_token"] = token_data.get("refresh_token")
    saxo_tokens["expires_in"] = token_data.get("expires_in")

    return {
        "status": "ok",
        "message": "Saxo tokens received. Store them securely for use by SaxoAdapter.",
        "token_data": token_data,
    }

# =========================
# Trading data endpoints
# =========================
@app.get("/api/ticker", response_model=TickerResponse)
def get_ticker():
    last = market_broker.fetch_ticker(SYMBOLS[0])
    return TickerResponse(
        symbol=last["symbol"],
        price=last["price"],
        change=last.get("change", 0.0),
        change_percent=last.get("change_percent", 0.0),
        timestamp=last["timestamp"],
        stats=execution_broker.paper.get_stats({last["symbol"]: last["price"]}),
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
            volume=float(row["volume"]),
        )
        for ts, row in df.iterrows()
    ]


@app.get("/api/signals")
def get_signals():
    return last_signals or []

# =========================
# Auth endpoints (Firebase)
# =========================
@app.post("/api/signup")
def signup(user: AuthRequest):
    try:
        firebase_user = auth.create_user(
            email=user.email, password=user.password, display_name=user.display_name
        )
        custom_token = auth.create_custom_token(firebase_user.uid)
        return {
            "uid": firebase_user.uid,
            "email": firebase_user.email,
            "token": custom_token.decode("utf-8"),
            "message": "User created successfully",
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
        "returnSecureToken": True,
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
        "local_id": result.get("localId"),
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
        "provider": decoded.get("firebase", {}).get("sign_in_provider"),
    }


@app.get("/api/profile")
async def profile(user=Depends(verify_firebase_token)):
    return {
        "uid": user["uid"],
        "email": user.get("email"),
        "provider": user.get("firebase", {}).get("sign_in_provider"),
    }

# =========================
# Run app
# =========================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

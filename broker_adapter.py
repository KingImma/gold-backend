import fxcmpy
import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import time


# =========================
# FXCM Adapter (LIVE TRADING)
# =========================

class FxcmAdapter(BrokerAdapter):
    """
    FXCM REST API adapter using fxcmpy.

    - symbol example for gold: 'XAU/USD'
    """

    def __init__(self, access_token: str, log_level: str = "error", server: str = "demo"):
        """
        server: 'demo' or 'real'
        """
        super().__init__()
        self.access_token = access_token
        self.log_level = log_level
        self.server = server
        self.con: Optional[fxcmpy.fxcmpy] = None  # connection object

    def connect(self) -> bool:
        try:
            self.con = fxcmpy.fxcmpy(
                access_token=self.access_token,
                log_level=self.log_level,
                server=self.server,  # 'demo' or 'real'
            )
            # simple sanity check: request account info
            accounts = self.con.get_accounts()
            if accounts is not None and len(accounts) > 0:
                self.connected = True
                print("✓ Connected to FXCM via fxcmpy")
                return True
            print("✗ FXCM connection failed: no accounts returned")
            return False
        except Exception as e:
            print(f"✗ FXCM connection error: {e}")
            return False

    def fetch_ticker(self, symbol: str = "XAU/USD") -> Dict:
        """
        Emulate a ticker via last bid/ask price from get_last_price.
        """
        if self.con is None:
            raise Exception("FXCM not connected")
        p = self.con.get_last_price(symbol)
        # fxcmpy get_last_price returns an object with bid/ask fields. [web:23][web:31]
        price = float(p.ask)
        return {
            "symbol": symbol.replace("/", ""),
            "price": price,
            "timestamp": int(time.time() * 1000),
        }

    def fetch_ohlcv(
        self,
        symbol: str = "XAU/USD",
        interval: str = "H1",
        limit: int = 100,
    ) -> List[List]:
        """
        Map your interval string to FXCM time frame.
        Example mappings:
            '1m' -> 'm1'
            '5m' -> 'm5'
            '15m' -> 'm15'
            '1h' -> 'H1'
            '4h' -> 'H4'
            '1d' -> 'D1'
        """
        if self.con is None:
            raise Exception("FXCM not connected")

        tf_map = {
            "1m": "m1",
            "5m": "m5",
            "15m": "m15",
            "30m": "m30",
            "1h": "H1",
            "4h": "H4",
            "1d": "D1",
        }
        fxcm_tf = tf_map.get(interval, interval)  # allow raw pass-through

        # fxcmpy exposes get_candles with columns bidopen, bidhigh, bidlow, bidclose, etc. [web:23][web:31]
        df = self.con.get_candles(symbol, period=fxcm_tf, number=limit)
        df = df.sort_index()  # oldest first

        ohlcv = []
        for ts, row in df.iterrows():
            # ts is a pandas Timestamp
            timestamp = int(ts.timestamp() * 1000)
            ohlcv.append([
                timestamp,
                float(row["bidopen"]),
                float(row["bidhigh"]),
                float(row["bidlow"]),
                float(row["bidclose"]),
                float(row.get("tickqty", 0.0)),  # or 0 if not available
            ])
        return ohlcv

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ):
        """
        Place a market order using fxcmpy.open_trade.
        """
        if self.con is None:
            raise Exception("FXCM not connected")

        is_buy = True if side.upper() == "BUY" else False

        # FXCM trade sizes are in contracts; check your account’s min/step size. [web:25][web:33]
        kwargs = {
            "symbol": symbol,
            "is_buy": is_buy,
            "amount": qty,
            "time_in_force": "GTC",
            "order_type": "AtMarket",
        }

        if stop_loss is not None:
            kwargs["stop"] = stop_loss
            kwargs["is_stop_in_pips"] = False
        if take_profit is not None:
            kwargs["limit"] = take_profit
            kwargs["is_limit_in_pips"] = False

        # fxcmpy.open_trade returns an fxcmpy_order object. [web:28][web:31]
        order = self.con.open_trade(**kwargs)
        # normalize to dict
        return {
            "order_id": order.get_orderId(),
            "is_buy": is_buy,
            "symbol": symbol,
            "amount": qty,
        }

    def get_positions(self):
        if self.con is None:
            return []
        # fxcmpy.get_open_positions returns a DataFrame. [web:23][web:31]
        df = self.con.get_open_positions()
        if df is None or df.empty:
            return []
        positions = []
        for _, row in df.iterrows():
            positions.append({
                "position_id": row.get("tradeId"),
                "symbol": row.get("currency"),
                "is_buy": bool(row.get("isBuy")),
                "amount": float(row.get("amountK", 0.0)),
                "open_price": float(row.get("open", 0.0)),
                "pl": float(row.get("grossPL", 0.0)),
            })
        return positions

    def get_account_info(self):
        if self.con is None:
            return None
        df = self.con.get_accounts()  # DataFrame with account fields. [web:23]
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        return {
            "account_id": row.get("accountId"),
            "balance": float(row.get("balance", 0.0)),
            "equity": float(row.get("equity", 0.0)),
            "margin": float(row.get("usableMargin", 0.0)),
            "currency": row.get("currency"),
        }


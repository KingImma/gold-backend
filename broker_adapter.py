import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import time


# =========================
# Base Adapter
# =========================


class BrokerAdapter(ABC):
    """Base class defining the interface all brokers must implement."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict:
        pass

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> List[List]:
        pass

    # Execution interface
    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ):
        raise NotImplementedError("Live trading not supported by this adapter")

    def get_positions(self):
        return []

    def get_account_info(self):
        return None


# =========================
# Twelve Data (Market Data)
# =========================


class TwelveDataAdapter(BrokerAdapter):
    BASE_URL = "https://api.twelvedata.com"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.session = requests.Session()
        self.session.params = {"apikey": self.api_key}

    def connect(self) -> bool:
        try:
            response = self.session.get(
                f"{self.BASE_URL}/quote", params={"symbol": "XAU/USD"}
            )
            data = response.json()
            if data.get("price") or data.get("close"):
                self.connected = True
                print("✓ Connected to Twelve Data API")
                return True
            print(f"✗ TwelveData connection failed: {data}")
            return False
        except Exception as e:
            print(f"✗ Connection error: {e}")
            return False

    def fetch_ticker(self, symbol: str = "XAUUSD") -> Dict:
        response = self.session.get(
            f"{self.BASE_URL}/quote",
            params={"symbol": symbol, "apikey": self.api_key},
        )
        data = response.json()
        raw_price = data.get("price") or data.get("close")
        if raw_price is None:
            raise Exception(f"Invalid response: {data}")
        return {
            "symbol": symbol,
            "price": float(raw_price),
            "change": float(data.get("change", 0)),
            "change_percent": float(data.get("percent_change", 0)),
            "timestamp": int(time.time() * 1000),
        }

    def fetch_ohlcv(
        self, symbol: str = "XAU/USD", interval: str = "1h", limit: int = 100
    ) -> List[List]:
        response = self.session.get(
            f"{self.BASE_URL}/time_series",
            params={"symbol": symbol, "interval": interval, "outputsize": limit},
        )
        data = response.json()
        if "values" not in data:
            raise Exception(f"API Error: {data}")
        ohlcv = []
        for candle in reversed(data["values"]):
            timestamp = int(
                time.mktime(
                    time.strptime(candle["datetime"], "%Y-%m-%d %H:%M:%S")
                )
                * 1000
            )
            ohlcv.append(
                [
                    timestamp,
                    float(candle["open"]),
                    float(candle["high"]),
                    float(candle["low"]),
                    float(candle["close"]),
                    0,
                ]
            )
        return ohlcv


# =========================
# Alpha Vantage (Market Data)
# =========================


class AlphaVantageAdapter(BrokerAdapter):
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.session = requests.Session()

    def connect(self) -> bool:
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": "XAU",
            "to_currency": "USD",
            "apikey": self.api_key,
        }
        response = self.session.get(self.BASE_URL, params=params)
        data = response.json()
        if "Realtime Currency Exchange Rate" in data:
            self.connected = True
            print("✓ Connected to Alpha Vantage API")
            return True
        print(f"✗ AlphaVantage connection failed: {data}")
        return False

    def fetch_ticker(self, symbol: str = "XAUUSD") -> Dict:
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": "XAU",
            "to_currency": "USD",
            "apikey": self.api_key,
        }
        response = self.session.get(self.BASE_URL, params=params)
        data = response.json()
        rate = data.get("Realtime Currency Exchange Rate")
        if not rate:
            raise Exception(f"API Error: {data}")
        return {
            "symbol": symbol,
            "price": float(rate["5. Exchange Rate"]),
            "timestamp": int(time.time() * 1000),
        }

    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> List[List]:
        raise Exception("Alpha Vantage OHLCV too limited for trading")


# =========================
# Saxo Adapter (LIVE TRADING)
# =========================


class SaxoAdapter(BrokerAdapter):
    """
    Saxo Bank OpenAPI adapter.

    You need:
    - access_token: OAuth access token obtained via the /token endpoint.
    - account_key: Saxo AccountKey for the account to trade on.
    - uic_map: maps your symbol (e.g. 'XAUUSD') to Saxo Uic.
    - asset_type_map: maps symbol to Saxo AssetType (e.g. 'CfdOnCommodity' or 'FxSpot').
    """

    BASE_URL = "https://gateway.saxo.com/openapi"

    def __init__(
        self,
        access_token: str,
        account_key: str,
        uic_map: Dict[str, int],
        asset_type_map: Dict[str, str],
    ):
        super().__init__()
        self.access_token = access_token
        self.account_key = account_key
        self.uic_map = uic_map
        self.asset_type_map = asset_type_map

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        )

    # --------------------------
    # Connection / account check
    # --------------------------
    def connect(self) -> bool:
        # Simple check: get current account(s) and ensure AccountKey is valid.
        url = f"{self.BASE_URL}/port/v1/accounts/me"
        r = self.session.get(url)
        self.connected = r.status_code == 200
        if self.connected:
            print(f"✓ Connected to Saxo (AccountKey={self.account_key})")
        else:
            print(f"✗ Saxo connection failed: {r.status_code} {r.text}")
        return self.connected

    # --------------------------
    # Ticker (snapshot price)
    # --------------------------
    def fetch_ticker(self, symbol: str) -> Dict:
        """
        Uses InfoPrices to get a snapshot price for the given symbol.[web:47][web:50][web:56]
        """
        uic = self.uic_map[symbol]
        asset_type = self.asset_type_map[symbol]

        url = f"{self.BASE_URL}/trade/v1/infoprices"
        params = {"Uic": uic, "AssetType": asset_type}
        r = self.session.get(url, params=params)
        r.raise_for_status()
        data = r.json()

        price_data = data["Data"][0]
        bid = float(price_data["Quote"]["Bid"])
        ask = float(price_data["Quote"]["Ask"])
        mid = (bid + ask) / 2.0

        return {
            "symbol": symbol,
            "price": mid,
            "timestamp": int(time.time() * 1000),
        }

    # --------------------------
    # OHLCV
    # --------------------------
    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> List[List]:
        # Keep using TwelveData or another market data broker for candles.
        raise Exception("Use market data broker for candles")

    # --------------------------
    # Place order (market)
    # --------------------------
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
        Places a market order using Saxo's Trade API.[web:47][web:49][web:58]
        """
        uic = self.uic_map[symbol]
        asset_type = self.asset_type_map[symbol]
        buy_sell = "Buy" if side.upper() == "BUY" else "Sell"

        order_body = {
            "AccountKey": self.account_key,
            "Uic": uic,
            "AssetType": asset_type,
            "BuySell": buy_sell,
            "Amount": qty,
            "OrderType": "Market",
            "OrderDuration": {"DurationType": "Day"},
        }

        # Simple example of related orders for SL/TP.[web:46][web:52][web:58]
        if stop_loss or take_profit:
            order_body["OrderRelation"] = {"Orders": []}
            opp_side = "Sell" if buy_sell == "Buy" else "Buy"

            if stop_loss:
                order_body["OrderRelation"]["Orders"].append(
                    {
                        "OrderType": "Stop",
                        "StopPrice": stop_loss,
                        "BuySell": opp_side,
                        "Amount": qty,
                    }
                )

            if take_profit:
                order_body["OrderRelation"]["Orders"].append(
                    {
                        "OrderType": "Limit",
                        "Price": take_profit,
                        "BuySell": opp_side,
                        "Amount": qty,
                    }
                )

        url = f"{self.BASE_URL}/trade/v2/orders"
        r = self.session.post(url, json=order_body)
        if r.status_code not in (200, 201):
            raise Exception(f"Saxo order failed: {r.status_code} {r.text}")
        return r.json()

    # --------------------------
    # Positions
    # --------------------------
    def get_positions(self):
        url = f"{self.BASE_URL}/port/v1/positions/me"
        r = self.session.get(url)
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("Data", [])

    # --------------------------
    # Account info
    # --------------------------
    def get_account_info(self):
        url = f"{self.BASE_URL}/port/v1/accounts/{self.account_key}"
        r = self.session.get(url)
        if r.status_code != 200:
            return None
        return r.json()


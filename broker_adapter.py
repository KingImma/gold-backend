"""
Broker Adapter - Unified interface for accessing gold price data
Uses free APIs (12data.com provides free tier with 800 requests/day)
"""

import requests
from abc import ABC, abstractmethod
from typing import Dict, List
from datetime import datetime
import time


class BrokerAdapter(ABC):
    """Base class defining the interface all brokers must implement."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        """Test connection to the API"""
        pass

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict:
        """Get current price (real-time quote)"""
        pass

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> List[List]:
        """Get historical candle data (OHLCV = Open/High/Low/Close/Volume)"""
        pass


class TwelveDataAdapter(BrokerAdapter):
    """Implementation using Twelve Data API"""

    BASE_URL = "https://api.twelvedata.com"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.session = requests.Session()
        self.session.params = {"apikey": self.api_key}

    def connect(self) -> bool:
        """Test if API key works by fetching a simple quote"""
        try:
            response = self.session.get(
                f"{self.BASE_URL}/quote", params={"symbol": "XAU/USD"}
            )
            data = response.json()

            raw_price = data.get("price") or data.get("close")
            if raw_price is not None:
                self.connected = True
                print("✓ Connected to Twelve Data API")
                print(f"  Current Gold Price (close): {raw_price}")
                return True

            if "message" in data:
                print(f"✗ Connection failed: {data['message']}")
                return False

            print(f"✗ Unexpected response from Twelve Data: {data}")
            return False
        except Exception as e:
            print(f"✗ Connection error: {e}")
            return False

    def fetch_ticker(self, symbol: str = "XAUUSD") -> Dict:
        """Get current gold price in real-time"""
        try:
            print("debug: symbol", symbol)
            response = self.session.get(
                f"{self.BASE_URL}/quote", params={
                    "symbol": symbol,
                    "apikey":self.api_key
                    }
            )
            data = response.json()

            raw_price = data.get("price") or data.get("close")
            if raw_price is None:
                raise Exception(
                    f"API Error: missing price/close field in response: {data}"
                )

            return {
                "symbol": symbol,
                "price": float(raw_price),
                "change": float(data.get("change", 0)),
                "change_percent": float(data.get("percent_change", 0)),
                "timestamp": int(time.time() * 1000),
            }
        except Exception as e:
            raise Exception(f"Failed to fetch ticker: {e}")

    def fetch_ohlcv(
        self, symbol: str = "XAU/USD", interval: str = "1h", limit: int = 100
    ) -> List[List]:
        """Get historical candle data (OHLCV bars)"""
        try:
            response = self.session.get(
                f"{self.BASE_URL}/time_series",
                params={"symbol": symbol, "interval": interval, "outputsize": limit},
            )
            data = response.json()

            if "values" not in data:
                raise Exception(f"API Error: {data.get('message', 'Unknown error')}")

            ohlcv = []
            for candle in reversed(data["values"]):  # Chronological order
                timestamp = int(
                    datetime.fromisoformat(
                        candle["datetime"].replace("Z", "+00:00")
                    ).timestamp()
                    * 1000
                )
                ohlcv.append(
                    [
                        timestamp,
                        float(candle["open"]),
                        float(candle["high"]),
                        float(candle["low"]),
                        float(candle["close"]),
                        0,  # Volume not provided
                    ]
                )
            return ohlcv

        except Exception as e:
            raise Exception(f"Failed to fetch OHLCV: {e}")


class AlphaVantageAdapter(BrokerAdapter):
    """Alternative FREE API: Alpha Vantage"""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.session = requests.Session()

    def connect(self) -> bool:
        try:
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
                rate = data["Realtime Currency Exchange Rate"]
                print(f"✓ Connected to Alpha Vantage API")
                print(f"  Current Gold Price: ${rate['5. Exchange Rate']}")
                return True
            else:
                print(f"✗ Connection failed: {data}")
                return False

        except Exception as e:
            print(f"✗ Connection error: {e}")
            return False

    def fetch_ticker(self, symbol: str = "XAUUSD") -> Dict:
        try:
            params = {
                "function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": symbol,
                "to_currency": "USD",
                "apikey": self.api_key,
            }
            response = self.session.get(self.BASE_URL, params=params)
            data = response.json()

            if "Realtime Currency Exchange Rate" not in data:
                raise Exception(f"API Error: {data}")

            rate = data["Realtime Currency Exchange Rate"]
            return {
                "symbol": f"{symbol}",
                "price": float(rate["5. Exchange Rate"]),
                "timestamp": int(time.time() * 1000),
            }

        except Exception as e:
            raise Exception(f"Failed to fetch ticker: {e}")

    def fetch_ohlcv(
        self, symbol: str = "XAU", interval: str = "60min", limit: int = 100
    ) -> List[List]:
        """Limited historical data on free tier"""
        try:
            params = {
                "function": "FX_INTRADAY",
                "from_symbol": symbol,
                "to_symbol": "USD",
                "interval": interval,
                "apikey": self.api_key,
            }
            response = self.session.get(self.BASE_URL, params=params)
            data = response.json()

            time_series_key = f"Time Series FX ({interval})"
            if time_series_key not in data:
                raise Exception(f"API Error: {data}")

            ohlcv = []
            for timestamp_str, candle in list(data[time_series_key].items())[:limit]:
                timestamp = int(
                    datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").timestamp()
                    * 1000
                )
                ohlcv.append(
                    [
                        timestamp,
                        float(candle["1. open"]),
                        float(candle["2. high"]),
                        float(candle["3. low"]),
                        float(candle["4. close"]),
                        0,
                    ]
                )
            return sorted(ohlcv, key=lambda x: x[0])

        except Exception as e:
            raise Exception(f"Failed to fetch OHLCV: {e}")

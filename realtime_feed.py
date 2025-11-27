"""
Real-Time Feed Manager
Continuously fetches live gold prices and notifies listeners
"""

import time
import threading
from typing import Callable, Dict, List
from typing_extensions import Optional


class RealtimeFeed:
    """
    Manages real-time price updates by polling the broker API

    Why polling instead of WebSocket?
    - Most free APIs don't offer WebSocket connections
    - Polling is simpler and sufficient for gold trading (slower pace than crypto)
    - Easy to control request rate to stay within API limits
    """

    def __init__(self, broker, symbols: List[str], interval: float = 5.0):
        """
        Args:
            broker: BrokerAdapter instance (TwelveData or AlphaVantage)
            symbols: List of symbols to track (e.g., ['XAU/USD'])
            interval: Seconds between updates (5 seconds = 12 requests/min)
        """
        self.broker = broker
        self.symbols = symbols
        self.interval = interval
        self.callbacks: List[Callable[[Dict], None]] = []
        self.running = False
        self.thread = None
        self.last_prices: Dict[str, float] = {}

    def subscribe(self, callback: Callable[[Dict], None]):
        """
        Register a function to be called when new price data arrives

        Example:
            def on_price_update(data):
                print(f"Gold: ${data['price']:.2f}")

            feed.subscribe(on_price_update)
        """
        self.callbacks.append(callback)
        print(f"✓ Subscribed callback: {callback.__name__}")

    def start(self):
        """Start fetching prices in background thread"""
        if self.running:
            print("⚠ Feed already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        print(f"✓ Started real-time feed (polling every {self.interval}s)")

    def stop(self):
        """Stop fetching prices"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("✓ Stopped real-time feed")

    def _poll_loop(self):
        """Main loop that continuously fetches prices"""
        while self.running:
            try:
                for symbol in self.symbols:
                    ticker = self.broker.fetch_ticker(symbol)

                    # Avoid sending unchanged prices
                    price_changed = (
                        symbol not in self.last_prices
                        or self.last_prices[symbol] != ticker["price"]
                    )

                    if price_changed:
                        self.last_prices[symbol] = ticker["price"]
                        self._notify_callbacks({"type": "ticker", "data": ticker})

                time.sleep(self.interval)

            except Exception as e:
                print(f"⚠ Polling error: {e}")
                time.sleep(10)  # Back off on error

    def _notify_callbacks(self, message: Dict):
        """Send price update to all registered callbacks"""
        for callback in self.callbacks:
            try:
                callback(message)
            except Exception as e:
                print(f"⚠ Callback error in {callback.__name__}: {e}")


class PriceMonitor:
    """
    Tracks recent prices, basic stats, and user-defined alerts.
    """

    def __init__(self, feed: RealtimeFeed):
        self.feed = feed
        self.price_history: List[Dict] = []
        self.alerts: List[Dict] = []
        self.last_ticker: Optional[Dict] = None  # <<< IMPORTANT

        # Subscribe to feed updates
        self.feed.subscribe(self._on_price_update)

    def _on_price_update(self, message: Dict):
        if message.get("type") != "ticker":
            return

        ticker = message["data"]
        self.last_ticker = ticker
        self.price_history.append(ticker)

        # Keep only last 100 prices
        if len(self.price_history) > 100:
            self.price_history.pop(0)

        self._check_alerts(ticker)

    def add_alert(self, condition, action):
        self.alerts.append({"condition": condition, "action": action})

    def _check_alerts(self, ticker: Dict):
        for alert in self.alerts:
            try:
                if alert["condition"](ticker):
                    alert["action"](ticker)
            except Exception as e:
                print(f"⚠ Alert error: {e}")

    def get_stats(self) -> Dict:
        if not self.price_history:
            return {}

        prices = [t["price"] for t in self.price_history]
        return {
            "current": prices[-1],
            "min": min(prices),
            "max": max(prices),
            "avg": sum(prices) / len(prices),
            "samples": len(prices),
        }

    def get_last_ticker(self) -> Optional[Dict]:
        """Used by /api/ticker in main.py"""
        return self.last_ticker

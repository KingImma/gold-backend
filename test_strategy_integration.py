import os
import unittest
import pandas as pd

from broker_adapter import TwelveDataAdapter
from strategy import EmaCross, RsiStrategy
import config


class TestStrategiesLive(unittest.TestCase):
    def setUp(self):
        self.api_key = os.getenv("TWELVE_DATA_API_KEY", config.TWELVE_DATA_API_KEY)
        self.symbol = (config.SYMBOLS[0] if getattr(config, "SYMBOLS", None) else "XAU/USD")
        self.interval = getattr(config, "DEFAULT_INTERVAL", "1h")
        self.limit = 200
        self.broker = TwelveDataAdapter(self.api_key)
        if not self.broker.connect():
            self.skipTest("Cannot connect to Twelve Data API (check API key / network)")

    def _to_df(self, candles):
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    def test_live_signals(self):
        candles = self.broker.fetch_ohlcv(self.symbol, self.interval, self.limit)
        df = self._to_df(candles)
        if df.empty or len(df) < 60:
            self.skipTest("Not enough OHLCV data returned to evaluate strategies")

        ema = EmaCross(symbol=self.symbol, fast=20, slow=50)
        rsi = RsiStrategy(symbol=self.symbol, period=14)

        ema_signals = ema.on_bar(df)
        rsi_signals = rsi.on_bar(df)

        print("\n[Live] Symbol:", self.symbol, "Interval:", self.interval, "Bars:", len(df))
        print("[Live] Last close:", float(df['close'].iloc[-1]))
        print("[Live] EmaCross signals:", [f"{s.side.value}@{s.symbol}" for s in ema_signals])
        print("[Live] RsiStrategy signals:", [f"{s.side.value}@{s.symbol}" for s in rsi_signals])

        self.assertIsInstance(ema_signals, list)
        self.assertIsInstance(rsi_signals, list)


if __name__ == "__main__":
    unittest.main()

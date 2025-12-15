# strategy_engine.py

from typing import List, Dict, Optional
import time
import pandas as pd

from models import Signal, Order, Side, OrderType, Trade
from strategy import BaseStrategy, EmaCross, RsiStrategy, MacdStrategy, BollingerBandsStrategy
from risk import RiskManager
from execution import ExecutionBroker
from historical_storage import HistoricalDataStore


class StrategyEngine:
    """
    Runs multiple strategies, combines their signals, applies risk,
    and sends executable orders to the broker.
    """

    def __init__(
        self,
        symbol: str,
        storage: HistoricalDataStore,
        execution_broker: ExecutionBroker,
        risk_manager: RiskManager,
        interval: str,
        min_confidence: float = 0.6,
    ):
        self.symbol = symbol
        self.storage = storage
        self.execution_broker = execution_broker
        self.risk_manager = risk_manager
        self.interval = interval
        self.min_confidence = min_confidence

        # Instantiate strategies
        self.strategies: List[BaseStrategy] = [
            EmaCross(symbol=symbol, fast=20, slow=50),
            RsiStrategy(symbol=symbol, period=14, overbought=70, oversold=30),
            MacdStrategy(symbol=symbol),
            BollingerBandsStrategy(symbol=symbol),
        ]

    def _load_data(self, lookback: int = 300) -> Optional[pd.DataFrame]:
        """Fetch recent OHLCV data from storage."""
        df = self.storage.fetch_ohlcv(self.symbol, self.interval)
        if df is None or df.empty:
            return None
        return df.tail(lookback)

    def _run_strategies(self, df: pd.DataFrame) -> List[Signal]:
        """Run all strategies and collect signals."""
        all_signals: List[Signal] = []
        for strat in self.strategies:
            try:
                sigs = strat.on_bar(df)
                all_signals.extend(sigs)
            except Exception as e:
                print(f"⚠ Strategy error in {strat.__class__.__name__}: {e}")
        return all_signals

    def _combine_signals(self, signals: List[Signal]) -> Optional[Signal]:
        """
        Simple ensemble:
        - Require at least one signal.
        - Aggregate BUY vs SELL confidence.
        - Take the side with higher total confidence.
        """
        if not signals:
            return None

        buy_conf = sum(getattr(s, "confidence", 1.0) for s in signals if s.side == Side.BUY)
        sell_conf = sum(getattr(s, "confidence", 1.0) for s in signals if s.side == Side.SELL)

        if buy_conf == 0 and sell_conf == 0:
            return None

        if buy_conf > sell_conf:
            side = Side.BUY
            total_conf = buy_conf
        else:
            side = Side.SELL
            total_conf = sell_conf

        # Normalize confidence to [0,1] (optional)
        max_conf = buy_conf + sell_conf
        confidence = total_conf / max_conf if max_conf > 0 else 1.0

        if confidence < self.min_confidence:
            return None

        # Use a generic Signal object (make sure your Signal dataclass matches this)
        return Signal(symbol=self.symbol, side=side, confidence=confidence)

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Optional: ATR for volatility-based stops.
        Uses standard True Range / ATR formula.
        """
        if len(df) < period + 2:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return float(atr)

    def generate_and_execute(self) -> Optional[Trade]:
        """
        Main entry point:
        - Load recent candles
        - Run strategies
        - Combine signals
        - Apply risk rules -> Order
        - Submit order via ExecutionBroker
        """
        df = self._load_data()
        if df is None or len(df) < 50:
            print("ℹ️ Not enough data for strategies")
            return None

        # 1) Run all strategies
        raw_signals = self._run_strategies(df)
        if not raw_signals:
            print("ℹ️ No signals from any strategy")
            return None

        # 2) Combine signals into a single decision
        final_signal = self._combine_signals(raw_signals)
        if final_signal is None:
            print("ℹ️ Signals did not meet confidence threshold")
            return None

        # 3) Price & ATR for risk calculations
        current_price = float(df["close"].iloc[-1])
        atr = self._compute_atr(df, period=14)

        # 4) RiskManager -> Order
        timestamp = int(time.time() * 1000)
        order = self.risk_manager.apply(
            signal=final_signal,
            price=current_price,
            timestamp=timestamp,
            atr=atr,
            custom_stop_pct=None,      # or override
            custom_rr_ratio=None,      # or override
        )

        if order is None:
            print("ℹ️ RiskManager rejected trade")
            return None

        # 5) Execute via ExecutionBroker (paper + live adapter)
        trade = self.execution_broker.submit_order(
            order,
            stop_loss=None,   # can pass explicit SL/TP if you prefer
            take_profit=None,
        )
        print(
            f"✅ Executed {trade.side.value} {trade.symbol} @ {trade.price} "
            f"| Qty: {trade.qty:.4f} | Confidence: {getattr(final_signal, 'confidence', 1.0):.2f}"
        )
        return trade


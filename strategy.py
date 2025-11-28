# Strategy File
from abc import ABC, abstractmethod
from typing import List
import pandas as pd
from models import Signal, Side

class BaseStrategy(ABC):
    @abstractmethod
    def on_bar(self, df: pd.DataFrame) -> List[Signal]:
        ...

class EmaCross(BaseStrategy):
    def __init__(self, symbol: str, fast: int = 20, slow: int = 50):
        self.symbol = symbol
        self.fast = fast
        self.slow = slow

    def on_bar(self, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.slow + 2:
            return []
        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()
        prev_fast = float(ema_fast.iloc[-2])
        prev_slow = float(ema_slow.iloc[-2])
        cur_fast = float(ema_fast.iloc[-1])
        cur_slow = float(ema_slow.iloc[-1])
        out: List[Signal] = []

        if prev_fast <= prev_slow and cur_fast > cur_slow:
            out.append(Signal(self.symbol, Side.BUY))
        elif prev_fast >= prev_slow and cur_fast < cur_slow:
            out.append(Signal(self.symbol, Side.SELL))
        return out

class RsiStrategy(BaseStrategy):
    def __init__(self, symbol: str, period: int = 14, overbought: int = 70, oversold: int = 30):
        self.symbol = symbol
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

    def on_bar(self, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.period + 2:
            return []
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()  # Fixed: negate delta for loss

        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))

        cur_rsi = float(rsi_series.iloc[-1])
        pre_rsi = float(rsi_series.iloc[-2])

        out: List[Signal] = []

        # Buy when we were below 30 and crossed back above it
        if pre_rsi < self.oversold and cur_rsi >= self.oversold:
            out.append(Signal(symbol=self.symbol, side=Side.BUY, confidence=0.8))
        
        # Sell when we were above 70 and crossed back below it
        elif pre_rsi > self.overbought and cur_rsi <= self.overbought:
            out.append(Signal(symbol=self.symbol, side=Side.SELL, confidence=0.8))

        return out

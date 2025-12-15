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
            out.append(Signal(symbol=self.symbol, side=Side.BUY))
        elif prev_fast >= prev_slow and cur_fast < cur_slow:
            out.append(Signal(symbol=self.symbol, side=Side.SELL))
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

        if pre_rsi < self.oversold and cur_rsi >= self.oversold:
            out.append(Signal(symbol=self.symbol, side=Side.BUY, confidence=0.8))
        elif pre_rsi > self.overbought and cur_rsi <= self.overbought:
            out.append(Signal(symbol=self.symbol, side=Side.SELL, confidence=0.8))

        return out

class MacdStrategy(BaseStrategy):
    def __init__(self, symbol: str, fast: int = 12, slow: int = 26, signal: int = 9):
        self.symbol = symbol
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def on_bar(self, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.slow + self.signal + 2:
            return []

        # Calculate MACD
        ema_fast = df['close'].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=self.signal, adjust=False).mean()

        prev_macd = float(macd.iloc[-2])
        prev_signal = float(signal_line.iloc[-2])
        cur_macd = float(macd.iloc[-1])
        cur_signal = float(signal_line.iloc[-1])

        out: List[Signal] = []

        if prev_macd <= prev_signal and cur_macd > cur_signal:
            out.append(Signal(symbol=self.symbol, side=Side.BUY, confidence=0.85))
        
        elif prev_macd >= prev_signal and cur_macd < cur_signal:
            out.append(Signal(symbol=self.symbol, side=Side.SELL, confidence=0.85))
        
        return out

class BollingerBandsStrategy(BaseStrategy):
    def __init__(self, symbol: str, period: int = 20, std_dev: float = 2.0):
        self.symbol = symbol
        self.period = period
        self.std_dev = std_dev
    
    def on_bar(self, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.period + 2:
            return []
        
        # Calculate Bollinger Bands
        sma = df['close'].rolling(window=self.period).mean()
        std = df['close'].rolling(window=self.period).std()
        upper_band = sma + (std * self.std_dev)
        lower_band = sma - (std * self.std_dev)
        
        cur_price = float(df['close'].iloc[-1])
        prev_price = float(df['close'].iloc[-2])
        cur_upper = float(upper_band.iloc[-1])
        cur_lower = float(lower_band.iloc[-1])
        
        out: List[Signal] = []
        
        if prev_price <= cur_upper and cur_price > cur_upper:
            out.append(Signal(symbol=self.symbol, side=Side.BUY, confidence=0.75))
        
        elif prev_price >= cur_lower and cur_price < cur_lower:
            out.append(Signal(symbol=self.symbol, side=Side.SELL, confidence=0.75))
        
        return out
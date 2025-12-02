# test_complete_system.py
import pandas as pd
from broker_adapter import TwelveDataAdapter
from strategy import EmaCross, RsiStrategy
from backtest import run_backtest
from risk import RiskLevel
import config

def test_complete_backtest():
    print("\n" + "="*70)
    print("🚀 COMPLETE ENHANCED BACKTESTING SYSTEM")
    print("="*70)
    
    # Fetch data
    broker = TwelveDataAdapter(config.TWELVE_DATA_API_KEY)
    if not broker.connect():
        print("❌ Failed to connect")
        return
    
    print("\n📥 Fetching historical data...")
    candles = broker.fetch_ohlcv("XAU/USD", "1h", 1000)
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]]
    
    print(f"✓ Loaded {len(df)} candles")
    print(f"  Period: {df.index[0]} to {df.index[-1]}")
    
    # Test with conservative risk
    print("\n" + "="*70)
    print("TEST 1: EMA Cross Strategy - CONSERVATIVE (1% risk)")
    print("="*70)
    
    ema = EmaCross(symbol="XAU/USD", fast=20, slow=50)
    results_conservative = run_backtest(
        df=df,
        strategy=ema,
        equity=100000.0,
        risk_level=RiskLevel.CONSERVATIVE,
        min_risk_reward=2.0,
        use_trailing_stops=True,
        verbose=True
    )
    
    # Test with aggressive risk
    print("\n" + "="*70)
    print("TEST 2: RSI Strategy - AGGRESSIVE (3% risk)")
    print("="*70)
    
    rsi = RsiStrategy(symbol="XAU/USD", period=14)
    results_aggressive = run_backtest(
        df=df,
        strategy=rsi,
        equity=100000.0,
        risk_level=RiskLevel.AGGRESSIVE,
        min_risk_reward=1.5,
        use_trailing_stops=True,
        verbose=True
    )
    
    # Comparison
    print("\n" + "="*70)
    print("📊 STRATEGY COMPARISON")
    print("="*70)
    print(f"\n{'Metric':<25} {'EMA (Conservative)':<20} {'RSI (Aggressive)':<20}")
    print("-" * 70)
    print(f"{'Return %':<25} {results_conservative['return_pct']:>18.2f}% {results_aggressive['return_pct']:>18.2f}%")
    print(f"{'Max Drawdown %':<25} {results_conservative['max_drawdown_pct']:>18.2f}% {results_aggressive['max_drawdown_pct']:>18.2f}%")
    print(f"{'Win Rate %':<25} {results_conservative['win_rate']:>18.1f}% {results_aggressive['win_rate']:>18.1f}%")
    print(f"{'Profit Factor':<25} {results_conservative['profit_factor']:>18.2f}  {results_aggressive['profit_factor']:>18.2f}")
    print(f"{'Total Trades':<25} {results_conservative['total_trades']:>18}  {results_aggressive['total_trades']:>18}")
    print("="*70)
    
    print("\n✅ Complete backtesting system test finished!")

if __name__ == "__main__":
    test_complete_backtest()

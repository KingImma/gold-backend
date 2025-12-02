from typing import Dict, Any, List
import pandas as pd
from strategy import BaseStrategy
from risk import RiskManager, RiskLevel
from execution import PaperBroker
from models import Trade

def run_backtest(
    df: pd.DataFrame, 
    strategy: BaseStrategy, 
    equity: float = 100000.0,
    risk_level: RiskLevel = RiskLevel.CONSERVATIVE,
    min_risk_reward: float = 2.0,
    fee_rate: float = 0.001,
    slippage_pct: float = 0.0005,
    accounting: str = 'FIFO',
    use_trailing_stops: bool = True,
    max_drawdown_pct: float = 0.10,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Run enhanced backtest with professional risk management
    
    Implements:
    - Stop loss and take profit automation
    - Trailing stops
    - Drawdown protection
    - Risk/reward validation
    - Exposure management
    
    Args:
        df: OHLCV DataFrame with datetime index
        strategy: Strategy instance to test
        equity: Starting capital
        risk_level: CONSERVATIVE (1%), MODERATE (2%), or AGGRESSIVE (3%)
        min_risk_reward: Minimum risk/reward ratio (default 2.0)
        fee_rate: Trading fee rate (0.001 = 0.1%)
        slippage_pct: Slippage percentage (0.0005 = 0.05%)
        accounting: 'FIFO' or 'LIFO'
        use_trailing_stops: Enable trailing stops
        max_drawdown_pct: Maximum drawdown before stopping (0.10 = 10%)
        verbose: Print trade details
    
    Returns:
        Comprehensive backtest results dictionary
    """
    # Initialize broker and risk manager
    paper = PaperBroker(
        cash=equity, 
        fee_rate=fee_rate,
        slippage_pct=slippage_pct,
        accounting=accounting
    )
    
    risk = RiskManager(
        account_equity=equity,
        risk_level=risk_level,
        min_risk_reward_ratio=min_risk_reward,
        max_position_pct=0.10,
        max_total_exposure=0.30,
        max_drawdown_pct=max_drawdown_pct,
        trailing_stop_enabled=use_trailing_stops,
        min_trade_value=10.0
    )
    
    trades: List[Trade] = []
    bars_processed = 0
    signals_generated = 0
    trades_executed = 0
    trades_stopped_out = 0
    trades_take_profit = 0
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🔄 Running Backtest: {strategy.__class__.__name__}")
        print(f"{'='*60}")
        print(f"  Capital: ${equity:,.0f}")
        print(f"  Risk Level: {risk_level.value} ({risk.risk_per_trade*100:.1f}% per trade)")
        print(f"  Min R:R Ratio: 1:{min_risk_reward:.1f}")
        print(f"  Max Drawdown: {max_drawdown_pct*100:.0f}%")
        print(f"  Bars: {len(df)}")
        print(f"{'='*60}\n")
    
    # Main backtest loop
    for i in range(len(df)):
        window = df.iloc[: i + 1]
        bars_processed = i + 1
        
        # Need minimum bars for indicators
        if len(window) < 50:
            continue
        
        # Get current market data
        current_bar = window.iloc[-1]
        current_price = float(current_bar["close"])
        current_high = float(current_bar["high"])
        current_low = float(current_bar["low"])
        ts = int(window.index[-1].timestamp() * 1000)
        
        # Update trailing stops
        current_prices = {strategy.symbol: current_price}
        paper.update_trailing_stops(current_prices, risk)
        
        # Check stops for all open positions
        for symbol in list(paper.positions.keys()):
            # Check if stop/take profit hit during this bar
            stop_result = paper.check_stops(symbol, current_low)  # Check low for stops
            if stop_result == 'STOP':
                paper.close_position(symbol, current_low, ts, reason="STOP_LOSS")
                risk.close_position(symbol)
                trades_stopped_out += 1
                continue
            
            tp_result = paper.check_stops(symbol, current_high)  # Check high for take profits
            if tp_result == 'TAKE_PROFIT':
                paper.close_position(symbol, current_high, ts, reason="TAKE_PROFIT")
                risk.close_position(symbol)
                trades_take_profit += 1
                continue
        
        # Update equity for risk management
        current_equity = paper.get_equity(current_prices)
        risk.update_equity(current_equity)
        
        # Check if trading is allowed (drawdown protection)
        if not risk.is_trading_allowed:
            if verbose:
                print(f"\n⚠️ Trading halted at bar {bars_processed}: Max drawdown exceeded")
            break
        
        # Get strategy signals
        signals = strategy.on_bar(window)
        if not signals:
            continue
        
        signals_generated += len(signals)
        
        # Process each signal
        for sig in signals:
            # Calculate stop loss and take profit
            stop_loss = risk.calculate_stop_loss(current_price, sig.side, atr=None)
            take_profit = risk.calculate_take_profit(current_price, stop_loss, sig.side)
            
            # Apply risk management
            order = risk.apply(sig, current_price, ts, atr=None)
            if not order:
                continue
            
            # Execute trade
            trade = paper.submit(order, stop_loss=stop_loss, take_profit=take_profit)
            
            if trade.qty > 0.0001:
                trades.append(trade)
                trades_executed += 1
                
                if verbose:
                    risk_amount = order.qty * abs(current_price - stop_loss)
                    reward_amount = order.qty * abs(take_profit - current_price)
                    rr_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
                    
                    print(f"📊 Trade #{trades_executed} | Bar {bars_processed}")
                    print(f"   {trade.side.value} {trade.qty:.4f} @ ${trade.price:.2f}")
                    print(f"   Stop: ${stop_loss:.2f} | Target: ${take_profit:.2f}")
                    print(f"   Risk: ${risk_amount:.2f} | Reward: ${reward_amount:.2f} | R:R = 1:{rr_ratio:.2f}")
                    print(f"   Equity: ${current_equity:,.2f}\n")
    
    # Calculate final metrics
    final_prices = {strategy.symbol: current_price}
    final_equity = paper.get_equity(final_prices)
    stats = paper.get_stats(final_prices)
    risk_summary = risk.get_risk_summary()
    
    # Calculate additional metrics
    profit_factor = 0.0
    if stats['avg_loss'] != 0:
        profit_factor = abs(stats['avg_win'] * stats['winning_trades']) / abs(stats['avg_loss'] * stats['losing_trades'])
    
    sharpe_ratio = 0.0  # Simplified - would need returns series for accurate calculation
    
    results = {
        # Capital metrics
        "initial_equity": equity,
        "final_equity": final_equity,
        "total_pnl": stats["total_pnl"],
        "return_pct": stats["return_pct"],
        "max_drawdown_pct": stats["max_drawdown"],
        "peak_equity": stats["peak_equity"],
        
        # Trade metrics
        "total_trades": trades_executed,
        "signals_generated": signals_generated,
        "winning_trades": stats["winning_trades"],
        "losing_trades": stats["losing_trades"],
        "win_rate": stats["win_rate"],
        "trades_stopped_out": trades_stopped_out,
        "trades_take_profit": trades_take_profit,
        
        # Performance metrics
        "avg_win": stats["avg_win"],
        "avg_loss": stats["avg_loss"],
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe_ratio,
        
        # Cost metrics
        "total_fees": stats["total_fees"],
        "cash_remaining": paper.cash,
        "open_positions": stats["open_positions"],
        
        # Risk metrics
        "risk_level": risk_level.value,
        "risk_per_trade_pct": risk.risk_per_trade * 100,
        "min_risk_reward_ratio": min_risk_reward,
        "final_drawdown_pct": risk_summary["current_drawdown_pct"],
        
        # Execution details
        "bars_processed": bars_processed,
        "accounting_method": accounting,
        "fee_rate": fee_rate * 100,
        "slippage_pct": slippage_pct * 100,
        
        # Full trade list
        "trades": trades,
    }
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"📈 BACKTEST RESULTS")
        print(f"{'='*60}")
        print(f"  Final Equity: ${results['final_equity']:,.2f}")
        print(f"  Total P/L: ${results['total_pnl']:,.2f}")
        print(f"  Return: {results['return_pct']:.2f}%")
        print(f"  Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        print(f"\n  Total Trades: {results['total_trades']}")
        print(f"  Win Rate: {results['win_rate']:.1f}%")
        print(f"  Profit Factor: {results['profit_factor']:.2f}")
        print(f"  Avg Win: ${results['avg_win']:.2f}")
        print(f"  Avg Loss: ${results['avg_loss']:.2f}")
        print(f"\n  Stopped Out: {results['trades_stopped_out']}")
        print(f"  Take Profit Hit: {results['trades_take_profit']}")
        print(f"  Total Fees: ${results['total_fees']:.2f}")
        print(f"{'='*60}\n")
    
    return results

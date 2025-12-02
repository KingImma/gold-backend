from typing import Dict, Optional, List, Tuple
from models import Order, Trade, Position, Side, OrderType
from risk import RiskManager
import time

class PaperBroker:
    """
    Enhanced paper broker with stop loss, take profit, and trailing stop support
    
    Features:
    - Automatic stop loss and take profit execution
    - Trailing stop management
    - Realistic slippage simulation
    - FIFO/LIFO accounting with lot-level tracking
    - Comprehensive trade statistics
    """
    
    def __init__(
        self, 
        cash: float = 100000.0,
        fee_rate: float = 0.001,  # 0.1% fee per trade
        slippage_pct: float = 0.0005,  # 0.05% slippage
        accounting: str = 'FIFO'
    ):
        self.cash = cash
        self.initial_cash = cash
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.accounting = accounting
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.orders: List[Order] = []
        
        # Stop loss and take profit tracking
        self.stop_losses: Dict[str, float] = {}  # symbol -> stop price
        self.take_profits: Dict[str, float] = {}  # symbol -> take profit price
        self.trailing_stops: Dict[str, Tuple[float, Side]] = {}  # symbol -> (stop, side)
        
        # Performance tracking
        self.peak_equity = cash
        self.max_drawdown = 0.0
        self.total_fees_paid = 0.0
    
    def set_stop_loss(self, symbol: str, stop_price: float):
        """Set stop loss for a position"""
        self.stop_losses[symbol] = stop_price
    
    def set_take_profit(self, symbol: str, take_profit_price: float):
        """Set take profit for a position"""
        self.take_profits[symbol] = take_profit_price
    
    def set_trailing_stop(self, symbol: str, stop_price: float, side: Side):
        """Set trailing stop for a position"""
        self.trailing_stops[symbol] = (stop_price, side)
    
    def update_trailing_stops(self, current_prices: Dict[str, float], risk_manager: Optional[RiskManager] = None):
        """
        Update trailing stops based on current prices
        
        Args:
            current_prices: Dict of symbol -> current price
            risk_manager: Optional RiskManager for trailing stop calculation
        """
        if not risk_manager or not risk_manager.trailing_stop_enabled:
            return
        
        for symbol, (current_stop, side) in list(self.trailing_stops.items()):
            if symbol not in current_prices or symbol not in self.positions:
                continue
            
            current_price = current_prices[symbol]
            pos = self.positions[symbol]
            entry_price = pos.avg_price()
            
            # Update trailing stop
            new_stop = risk_manager.update_trailing_stop(
                entry_price=entry_price,
                current_price=current_price,
                current_stop=current_stop,
                side=side,
                trailing_pct=0.02  # 2% trailing
            )
            
            if new_stop != current_stop:
                self.trailing_stops[symbol] = (new_stop, side)
                self.stop_losses[symbol] = new_stop  # Update regular stop too
    
    def check_stops(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Check if stop loss or take profit is hit
        
        Args:
            symbol: Symbol to check
            current_price: Current market price
        
        Returns:
            'STOP' if stop loss hit, 'TAKE_PROFIT' if take profit hit, None otherwise
        """
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        
        # Check stop loss
        if symbol in self.stop_losses:
            stop = self.stop_losses[symbol]
            if pos.qty > 0 and current_price <= stop:  # Long position
                return 'STOP'
            elif pos.qty < 0 and current_price >= stop:  # Short position
                return 'STOP'
        
        # Check take profit
        if symbol in self.take_profits:
            take_profit = self.take_profits[symbol]
            if pos.qty > 0 and current_price >= take_profit:  # Long position
                return 'TAKE_PROFIT'
            elif pos.qty < 0 and current_price <= take_profit:  # Short position
                return 'TAKE_PROFIT'
        
        return None
    
    def apply_slippage(self, price: float, side: Side) -> float:
        """Apply slippage to execution price"""
        if side == Side.BUY:
            return price * (1 + self.slippage_pct)  # Pay more when buying
        else:
            return price * (1 - self.slippage_pct)  # Get less when selling
    
    def submit(self, order: Order, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Trade:
        """
        Execute an order and return trade result
        
        Args:
            order: Order to execute
            stop_loss: Optional stop loss price
            take_profit: Optional take profit price
        
        Returns:
            Trade object with execution details
        """
        self.orders.append(order)
        
        # Apply slippage to execution price
        exec_price = self.apply_slippage(order.price, order.side) if order.price else 0.0
        
        # Calculate fees
        notional_value = order.qty * exec_price
        fee = notional_value * self.fee_rate
        self.total_fees_paid += fee
        
        if order.side == Side.BUY:
            total_cost = notional_value + fee
            
            # Check cash availability
            if total_cost > self.cash:
                available_for_trade = self.cash / (1 + self.fee_rate + self.slippage_pct)
                order.qty = available_for_trade / order.price if order.price else 0
                notional_value = order.qty * exec_price
                fee = notional_value * self.fee_rate
                total_cost = notional_value + fee
            
            if order.qty <= 0 or total_cost <= 0:
                return Trade(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=0.0001,
                    price=exec_price,
                    ts=order.ts or int(time.time() * 1000),
                    fee=0.0
                )
            
            self.cash -= total_cost
            
        else:  # SELL
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                available_qty = max(0, pos.qty)
                order.qty = min(order.qty, available_qty)
            
            if order.qty <= 0:
                return Trade(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=0.0001,
                    price=exec_price,
                    ts=order.ts or int(time.time() * 1000),
                    fee=0.0
                )
            
            proceeds = order.qty * exec_price
            fee = proceeds * self.fee_rate
            self.cash += (proceeds - fee)
        
        # Create trade
        trade = Trade(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=exec_price,
            ts=order.ts or int(time.time() * 1000),
            fee=fee
        )
        
        # Update position
        self._update_position(trade)
        
        # Set stop loss and take profit if provided
        if stop_loss and order.side == Side.BUY:
            self.set_stop_loss(order.symbol, stop_loss)
            self.set_trailing_stop(order.symbol, stop_loss, Side.BUY)
        if take_profit and order.side == Side.BUY:
            self.set_take_profit(order.symbol, take_profit)
        
        self.trades.append(trade)
        return trade
    
    def close_position(self, symbol: str, current_price: float, timestamp: int, reason: str = "MANUAL") -> Optional[Trade]:
        """
        Close an entire position
        
        Args:
            symbol: Symbol to close
            current_price: Current market price
            timestamp: Current timestamp
            reason: Reason for closing (STOP, TAKE_PROFIT, MANUAL)
        
        Returns:
            Trade object if position closed, None otherwise
        """
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        if abs(pos.qty) < 1e-8:
            return None
        
        # Create closing order
        close_side = Side.SELL if pos.qty > 0 else Side.BUY
        close_order = Order(
            symbol=symbol,
            side=close_side,
            qty=abs(pos.qty),
            order_type=OrderType.MARKET,
            price=current_price,
            ts=timestamp
        )
        
        trade = self.submit(close_order)
        
        # Clean up stops
        if symbol in self.stop_losses:
            del self.stop_losses[symbol]
        if symbol in self.take_profits:
            del self.take_profits[symbol]
        if symbol in self.trailing_stops:
            del self.trailing_stops[symbol]
        
        print(f"  🔴 Position closed ({reason}): {trade.symbol} | PnL: ${pos.realized_pnl:.2f}")
        
        return trade
    
    def _update_position(self, trade: Trade):
        """Update position based on trade using lot accounting"""
        if trade.symbol not in self.positions:
            self.positions[trade.symbol] = Position(
                symbol=trade.symbol,
                qty=0.0,
                lots=[],
                realized_pnl=0.0,
                unrealized_pnl=0.0
            )
        
        pos = self.positions[trade.symbol]
        pos.apply_trade(trade, accounting=self.accounting)
        
        # Remove position if fully closed
        if abs(pos.qty) < 1e-8:
            if trade.symbol in self.positions:
                del self.positions[trade.symbol]
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol"""
        return self.positions.get(symbol)
    
    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total equity (cash + position value)"""
        position_value = 0.0
        
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos.avg_price())
            pos.update_unrealized(price)
            position_value += pos.qty * price
        
        equity = self.cash + position_value
        
        # Update peak and drawdown
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        current_drawdown = (self.peak_equity - equity) / self.peak_equity
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
        
        return equity
    
    def get_total_pnl(self) -> float:
        """Get total realized + unrealized PnL"""
        realized = sum(pos.realized_pnl for pos in self.positions.values())
        unrealized = sum(pos.unrealized_pnl for pos in self.positions.values())
        return realized + unrealized
    
    def get_stats(self, current_prices: Dict[str, float]) -> Dict:
        """Get comprehensive broker statistics"""
        equity = self.get_equity(current_prices)
        total_pnl = self.get_total_pnl()
        
        # Calculate trade statistics
        winning_trades = []
        losing_trades = []
        
        for symbol, pos in self.positions.items():
            if pos.realized_pnl > 0:
                winning_trades.extend([pos.realized_pnl])
            elif pos.realized_pnl < 0:
                losing_trades.extend([pos.realized_pnl])
        
        total_wins = len(winning_trades)
        total_losses = len(losing_trades)
        total_trades = len(self.trades)
        
        return {
            "initial_cash": self.initial_cash,
            "current_cash": self.cash,
            "equity": equity,
            "peak_equity": self.peak_equity,
            "max_drawdown": self.max_drawdown * 100,
            "total_pnl": total_pnl,
            "return_pct": (equity / self.initial_cash - 1.0) * 100.0,
            "total_trades": total_trades,
            "winning_trades": total_wins,
            "losing_trades": total_losses,
            "win_rate": (total_wins / total_trades * 100) if total_trades > 0 else 0.0,
            "open_positions": len(self.positions),
            "total_fees": self.total_fees_paid,
            "avg_win": sum(winning_trades) / len(winning_trades) if winning_trades else 0.0,
            "avg_loss": sum(losing_trades) / len(losing_trades) if losing_trades else 0.0,
        }

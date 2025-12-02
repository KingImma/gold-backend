from typing import Optional, Dict, List
from models import Signal, Order, Side, OrderType, Trade
from dataclasses import dataclass
from enum import Enum

class RiskLevel(str, Enum):
    CONSERVATIVE = "CONSERVATIVE" 
    MODERATE = "MODERATE"          
    AGGRESSIVE = "AGGRESSIVE"      


@dataclass
class TradeRisk:
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float


class RiskManager:
    def __init__(
        self, 
        account_equity: float = 100000.0,
        risk_level: RiskLevel = RiskLevel.CONSERVATIVE,
        min_risk_reward_ratio: float = 2.0,  
        max_position_pct: float = 0.10,      
        max_total_exposure: float = 0.30,    
        max_drawdown_pct: float = 0.10,      
        trailing_stop_enabled: bool = True,
        min_trade_value: float = 100.0
    ):
        self.initial_equity = account_equity
        self.account_equity = account_equity
        self.risk_level = risk_level
        self.min_risk_reward_ratio = min_risk_reward_ratio
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.max_drawdown_pct = max_drawdown_pct
        self.trailing_stop_enabled = trailing_stop_enabled
        self.min_trade_value = min_trade_value
        
        # Risk per trade based on level
        self._risk_per_trade_map = {
            RiskLevel.CONSERVATIVE: 0.01,  # 1%
            RiskLevel.MODERATE: 0.02,      # 2%
            RiskLevel.AGGRESSIVE: 0.03     # 3%
        }

        self.open_positions: Dict[str, float] = {} 
        self.trade_history: List[Trade] = []
        self.peak_equity = account_equity
        self.current_drawdown = 0.0
        
    @property
    def risk_per_trade(self) -> float:
        return self._risk_per_trade_map[self.risk_level]
    
    @property
    def is_trading_allowed(self) -> bool:
        return self.current_drawdown < self.max_drawdown_pct
    
    def calculate_stop_loss(
        self, 
        entry_price: float, 
        side: Side,
        atr: Optional[float] = None,
        fixed_pct: Optional[float] = None
    ) -> float:
        if atr:
            # ATR-based stop: 2x ATR from entry
            stop_distance = 2.0 * atr
        else:
            # Fixed percentage stop (default 2%)
            pct = fixed_pct if fixed_pct else 0.02
            stop_distance = entry_price * pct
        
        if side == Side.BUY:
            return entry_price - stop_distance
        else:  # SELL
            return entry_price + stop_distance
    
    def calculate_take_profit(
        self, 
        entry_price: float, 
        stop_loss: float,
        side: Side,
        risk_reward_ratio: Optional[float] = None
    ) -> float:
        ratio = risk_reward_ratio if risk_reward_ratio else self.min_risk_reward_ratio
        risk = abs(entry_price - stop_loss)
        reward = risk * ratio
        
        if side == Side.BUY:
            return entry_price + reward
        else:  # SELL
            return entry_price - reward
    
    def calculate_position_size(
        self, 
        entry_price: float,
        stop_loss: float,
        signal_confidence: float = 1.0
    ) -> float:
        # Adjust risk by signal confidence
        adjusted_risk_pct = self.risk_per_trade * signal_confidence
        risk_amount = self.account_equity * adjusted_risk_pct
        
        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit <= 0:
            return 0.0
        
        # Position size based on risk
        position_size = risk_amount / risk_per_unit
        
        # Apply maximum position size limit
        max_position_value = self.account_equity * self.max_position_pct
        max_qty = max_position_value / entry_price
        
        return min(position_size, max_qty)
    
    def check_exposure_limit(self, new_position_value: float) -> bool:
        current_exposure = sum(self.open_positions.values())
        total_exposure = current_exposure + new_position_value
        max_exposure = self.account_equity * self.max_total_exposure
        
        return total_exposure <= max_exposure
    
    def apply(
        self, 
        signal: Signal, 
        price: float, 
        timestamp: int,
        atr: Optional[float] = None,
        custom_stop_pct: Optional[float] = None,
        custom_rr_ratio: Optional[float] = None
    ) -> Optional[Order]:
        # Check if trading is allowed (drawdown protection)
        if not self.is_trading_allowed:
            print(f"⚠️ Trading halted: Max drawdown ({self.max_drawdown_pct*100:.1f}%) reached")
            return None
        
        # Calculate stop loss
        stop_loss = self.calculate_stop_loss(
            price, 
            signal.side, 
            atr=atr,
            fixed_pct=custom_stop_pct
        )
        
        # Calculate take profit
        take_profit = self.calculate_take_profit(
            price,
            stop_loss,
            signal.side,
            risk_reward_ratio=custom_rr_ratio
        )
        
        # Calculate position size
        qty = self.calculate_position_size(
            price,
            stop_loss,
            signal.confidence
        )
        
        if qty <= 0:
            return None
        
        # Check minimum trade value
        position_value = qty * price
        if position_value < self.min_trade_value:
            return None
        
        # Check total exposure limit
        if not self.check_exposure_limit(position_value):
            print(f"⚠️ Trade rejected: Would exceed max exposure ({self.max_total_exposure*100:.0f}%)")
            return None
        
        # Track open position
        self.open_positions[signal.symbol] = position_value
        
        # Create order
        order = Order(
            symbol=signal.symbol,
            side=signal.side,
            qty=qty,
            order_type=OrderType.MARKET,
            price=price,
            ts=timestamp
        )
        
        return order
    
    def get_trade_risk_details(
        self,
        entry_price: float,
        side: Side,
        signal_confidence: float = 1.0,
        atr: Optional[float] = None
    ) -> TradeRisk:
        stop_loss = self.calculate_stop_loss(entry_price, side, atr=atr)
        take_profit = self.calculate_take_profit(entry_price, stop_loss, side)
        position_size = self.calculate_position_size(entry_price, stop_loss, signal_confidence)
        
        risk_per_unit = abs(entry_price - stop_loss)
        reward_per_unit = abs(take_profit - entry_price)
        
        risk_amount = position_size * risk_per_unit
        reward_amount = position_size * reward_per_unit
        risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
        
        return TradeRisk(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            risk_amount=risk_amount,
            reward_amount=reward_amount,
            risk_reward_ratio=risk_reward_ratio
        )
    
    def update_equity(self, new_equity: float):
        if new_equity > 0:
            self.account_equity = new_equity
            
            # Update peak equity
            if new_equity > self.peak_equity:
                self.peak_equity = new_equity
            
            # Calculate current drawdown
            self.current_drawdown = (self.peak_equity - new_equity) / self.peak_equity
    
    def close_position(self, symbol: str):
        if symbol in self.open_positions:
            del self.open_positions[symbol]
    
    def update_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float,
        side: Side,
        trailing_pct: float = 0.02 
    ) -> float:
        if not self.trailing_stop_enabled:
            return current_stop
        
        if side == Side.BUY:
            new_stop = current_price * (1 - trailing_pct)
            return max(new_stop, current_stop)
        else:
            new_stop = current_price * (1 + trailing_pct)
            return min(new_stop, current_stop)
    
    def get_risk_summary(self) -> Dict:
        return {
            "account_equity": self.account_equity,
            "initial_equity": self.initial_equity,
            "peak_equity": self.peak_equity,
            "current_drawdown_pct": self.current_drawdown * 100,
            "max_drawdown_pct": self.max_drawdown_pct * 100,
            "risk_level": self.risk_level.value,
            "risk_per_trade_pct": self.risk_per_trade * 100,
            "min_risk_reward_ratio": self.min_risk_reward_ratio,
            "open_positions": len(self.open_positions),
            "total_exposure": sum(self.open_positions.values()),
            "total_exposure_pct": (sum(self.open_positions.values()) / self.account_equity * 100) if self.account_equity > 0 else 0,
            "max_exposure_pct": self.max_total_exposure * 100,
            "trading_allowed": self.is_trading_allowed,
            "total_return_pct": ((self.account_equity / self.initial_equity - 1) * 100) if self.initial_equity > 0 else 0
        }

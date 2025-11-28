from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from typing import Optional, List, Literal
from uuid import uuid4
from math import isclose


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class Candle(BaseModel):
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator('ts', mode='before')
    def ts_must_be_int(cls, v):
        if not isinstance(v, int):
            raise TypeError('ts must be int')
        return v


class Signal(BaseModel):
    symbol: str
    side: Side
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator('symbol')
    def symbol_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('symbol must not be empty')
        return v.upper()

class Order(BaseModel):
    symbol: str
    side: Side
    qty: float = Field(..., gt=0)
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    ts: Optional[int] = None
    id: str = Field(default_factory=lambda: str(uuid4()))

    @model_validator(mode="after")
    def check_limit_has_price(self):
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError('Limit orders requires a price')
        return self

    @field_validator('symbol')
    def symbol_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('symbol must not be empty')
        return v.upper()

class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    order_id: Optional[str] = None
    symbol: str
    side: Side
    qty: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    ts: int
    fee: float = Field(default=0.0, ge=0.0)

    @field_validator('symbol')
    def symbol_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('symbol must not be empty')
        return v.upper()

class Lot(BaseModel):
    qty: float
    price: float

class Position(BaseModel):
    symbol: str
    qty: float
    lots: List[Lot] = Field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @field_validator('symbol')
    def symbol_upper(cls, v):
        return v.upper()
    
    def avg_price(self) -> float:
        total_qty = 0.0
        total_cost = 0.0
        for lot in self.lots:
            total_qty += lot.qty
            total_cost += lot.qty * lot.price
        if isclose(total_qty, 0.0):
            return 0.0
        return total_cost / total_qty
        
    def update_unrealized(self, market_price: float):
        net = sum(l.qty for l in self.lots)
        if isclose(net, 0.0):
            self.unrealized_pnl = 0.0
            return
        avg = self.avg_price()
        if net > 0:
            self.unrealized_pnl = (market_price - avg) * net
        else:
            self.unrealized_pnl = (avg - market_price) * abs(net)

    def apply_trade(self, trade: Trade, accounting: Literal['FIFO', 'LIFO'] = 'FIFO'):
        if trade.symbol != self.symbol:
            raise ValueError("Trade symbol does not match position symbol")

        signed_qty = trade.qty if trade.side == Side.BUY else -trade.qty
        if signed_qty > 0:
            self.lots.append(Lot(qty=signed_qty, price=trade.price))
            self.qty = sum(l.qty for l in self.lots)
            return
        sell_qty = -signed_qty
        if accounting == 'FIFO':
            iterable = range(len(self.lots))
        else:
            iterable = range(len(self.lots)-1, -1, -1)
        realized = 0.0
        remaining = sell_qty
        for i in list(iterable):
            if remaining <= 0:
                break
            lot = self.lots[i]
            if lot.qty <= 0:
                continue
            take = min(lot.qty, remaining)
            pnl = (trade.price - lot.price) * take
            realized += pnl
            lot.qty -= take
            remaining -= take
        self.lots = [lot for lot in self.lots if lot.qty > 0.0]
        if remaining > 0:
            self.lots.append(Lot(qty=-remaining, price=trade.price))
            remaining = 0.0
        self.realized_pnl += realized - trade.fee
        self.qty = sum(l.qty for l in self.lots)

    def serialize(self):
        return {
            "symbol": self.symbol,
            "qty": round(self.qty, 8),
            "avg_price": round(self.avg_price(), 8),
            "realized_pnl": round(self.realized_pnl, 8),
            "unrealized_pnl": round(self.unrealized_pnl, 8),
            "lots": [{"qty": round(l.qty,8), "price": round(l.price,8)} for l in self.lots]
        }


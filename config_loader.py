import json
from dataclasses import dataclass
from typing import Dict

@dataclass
class TradingConfig:
     symbols: list
     default_interval: str
     risk_level: str
     max_positions: int

@dataclass
class StrategyConfig:
    ema_cross: Dict
    rsi: Dict

@dataclass
class RiskConfig:
    stop_loss_pct: float
    take_profit_ratio: float
    trailing_stop_enabled: bool
    max_drawdown_pct: float
    daily_loss_limit: float

class ConfigLoader:
    @staticmethod
    def load(config: Dict, config_path: str = "config.json"):
        with open(config_path, 'r') as f:
            data = json.load(f)
        return data
    
    @staticmethod
    def save(config: Dict, config_path: str = "config.json"):
        with open(config_path, 'w') as f:
            json.dump(config, f, indent = 2)
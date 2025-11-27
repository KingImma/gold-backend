import os


# TWELVE_DATA_API_KEY = "28162c62fc5e4f90a9c390801556b98c"

# # Alpha Vantage API Key (Alternative - 25 free requests/day)
# # Sign up at: https://www.alphavantage.co/support/#api-key
# ALPHA_VANTAGE_API_KEY = "F1TSCN899DNUXN6P"

# # Trading symbols to track
# SYMBOLS = ["XAU/USD"]  # Gold vs USD

# # Data collection settings
# DEFAULT_INTERVAL = "1h"  # 1 hour candles
# HISTORICAL_LIMIT = 1000  # Number of historical candles to fetch
# REALTIME_INTERVAL = 5.0  # Seconds between price updates

# # Database
# DATABASE_PATH = "gold_trading.db"


TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY", "28162c62fc5e4f90a9c390801556b98c"
)
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "F1TSCN899DNUXN6P")

SYMBOLS = ["XAU/USD"]
DEFAULT_INTERVAL = "1h"
HISTORICAL_LIMIT = 1000
REALTIME_INTERVAL = 15.0
DATABASE_PATH = "gold_trading.db"

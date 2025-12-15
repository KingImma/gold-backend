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
SAXO_APP_KEY =  "af23ad50efd740788e85c97da548711e "
SAXO_APP_SECRET = "ee2fbee711f3432bbe10153b935e4465"
SAXO_REDIRECT_URL = "http://localhost:8000/saxo/callback"
SAXO_ACCESS_TOKEN = " eyJhbGciOiJFUzI1NiIsIng1dCI6IjY3NEM0MjFEMzZEMUE1OUNFNjFBRTIzMjMyOTVFRTAyRTc3MDMzNTkifQ.eyJvYWEiOiI3Nzc3NSIsImlzcyI6Im9hIiwiYWlkIjoiMTA5IiwidWlkIjoiS0d4c1lOQ2tNbmJiNENCLTAyNXJLUT09IiwiY2lkIjoiS0d4c1lOQ2tNbmJiNENCLTAyNXJLUT09IiwiaXNhIjoiRmFsc2UiLCJ0aWQiOiIyMDAyIiwic2lkIjoiYTQ3M2Y3ZGZjYjYzNGUwY2JhNTA1YjA3YzkyZmQ2OWIiLCJkZ2kiOiI4NCIsImV4cCI6IjE3NjU5MDMyMzEiLCJvYWwiOiIxRiIsImlpZCI6Ijk4OGY5MjU0M2M5NzQwMTQ1NjFkMDhkZTM2ZjIxMWQ0In0.N-8RjRvoOu2UbbVNaz5Osk6jAX8R3EJynMT-3VyfDK-SxeieweoCDoUljrz5raZw8aivWRAkrSGQ1NPiUfx8yQ "
SAXO_UIC_MAP = {
    "XAUUSD": 123456,        # replace with real UIC
}
SAXO_ASSET_TYPE_MAP = {
    "XAUUSD": "CfdOnCommodity",  # or "FxSpot" if you trade spot XAUUSD
} 
SAXO_CLIENT_KEY= "KGxsYNCkMnbb4CB-025rKQ=="
SAXO_DEFAULT_ACCOUNT_KEY = "KGxsYNCkMnbb4CB-025rKQ=="
SAXO_CLIENT_ID = "21625769"
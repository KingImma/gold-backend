
import sqlite3
import pandas as pd
from datetime import datetime
from typing import List, Optional, Dict


class HistoricalDataStore:

    def __init__(self, db_path: str = "gold_trading.db"):
        self.db_path = db_path
        self.conn = None
        self._init_db()

    def _init_db(self):
        """Create database tables if they don't exist"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = self.conn.cursor()

        # Main table for OHLCV candle data
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                UNIQUE(symbol, interval, timestamp)
            )
            """
        )

        # Index for fast queries by symbol and time range
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup 
            ON ohlcv(symbol, interval, timestamp)
            """
        )

        self.conn.commit()
        print(f"✓ Database initialized: {self.db_path}")

    def store_ohlcv(self, symbol: str, interval: str, candles: List[List]):
        """
        Store OHLCV candles in database

        Args:
            symbol: 'XAU/USD'
            interval: '1h', '4h', '1day'
            candles: [[timestamp, open, high, low, close, volume], ...]
        """
        cursor = self.conn.cursor()
        stored_count = 0

        for candle in candles:
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO ohlcv 
                    (symbol, interval, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (symbol, interval, *candle),
                )
                stored_count += 1
            except Exception as e:
                print(f"⚠ Error storing candle: {e}")

        self.conn.commit()
        print(f"✓ Stored {stored_count} candles for {symbol} ({interval})")
        return stored_count

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> pd.DataFrame:
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = ? AND interval = ?
        """
        params = [symbol, interval]

        if start:
            query += " AND timestamp >= ?"
            params.append(start)
        if end:
            query += " AND timestamp <= ?"
            params.append(end)

        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, self.conn, params=params)

        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)

        return df

    def get_latest_timestamp(self, symbol: str, interval: str) -> Optional[int]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT MAX(timestamp) FROM ohlcv
            WHERE symbol = ? AND interval = ?
            """,
            (symbol, interval),
        )
        result = cursor.fetchone()
        return result[0] if result[0] else None

    def update_from_broker(self, broker, symbol: str, interval: str = "1h", limit: int = 1000):
        print(f"Updating {symbol} {interval} data...")

        latest = self.get_latest_timestamp(symbol, interval)
        if latest:
            print(f"  Latest data: {datetime.fromtimestamp(latest / 1000)}")

        try:
            candles = broker.fetch_ohlcv(symbol, interval, limit)

            if candles:
                if latest:
                    candles = [c for c in candles if c[0] > latest]

                if candles:
                    return self.store_ohlcv(symbol, interval, candles)
                else:
                    print("  No new candles to store")
                    return 0
            else:
                print("  No candles received from broker")
                return 0

        except Exception as e:
            print(f"✗ Update failed: {e}")
            return 0

    def get_stats(self, symbol: str, interval: str) -> Dict:
        """Get statistics about stored data"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) as count, MIN(timestamp) as first, MAX(timestamp) as last
            FROM ohlcv
            WHERE symbol = ? AND interval = ?
            """,
            (symbol, interval),
        )

        row = cursor.fetchone()
        if row[0] > 0:
            return {
                "candle_count": row[0],
                "first_candle": datetime.fromtimestamp(row[1] / 1000),
                "last_candle": datetime.fromtimestamp(row[2] / 1000),
            }
        return {}

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print("✓ Database connection closed")

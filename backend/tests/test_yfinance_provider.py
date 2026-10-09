import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.database import HKDuckDBDatabase, SQLiteDatabase, USDuckDBDatabase
from backend.app.provider.yfinance_provider import YFinanceProvider, YFinanceProviderError
from backend.app.repository import (
    HKStockRepository, USStockRepository, HKDailyBarRepository, USDailyBarRepository,
)
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.schemas.market import DailyBar
from backend.scripts.sync_hk_us_daily_bars import (
    format_yfinance_daily_bars, sync_hk_us_daily_bars,
)


def timestamp(value):
    return int(pd.Timestamp(value).timestamp() * 1000)


def history(timezone="America/New_York"):
    return pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [12.0, 13.0], "Low": [9.0, 10.0],
         "Close": [11.0, 12.0], "Volume": [100, 200]},
        index=pd.DatetimeIndex(["2026-03-06", "2026-03-09"], tz=timezone),
    )


class YFinanceProviderTests(unittest.TestCase):
    def test_symbol_mapping(self):
        cases = {"00700.HK": "0700.HK", "HK.00700": "0700.HK",
                 "700": "0700.HK", "09988.HK": "9988.HK",
                 "10000.HK": "10000.HK", "US.AAPL": "AAPL",
                 "NVDA.O": "NVDA", "AAPL.US": "AAPL", "BRK.B": "BRK-B",
                 "BRK.A": "BRK-A", "US.BRK.A": "BRK-A"}
        for symbol, expected in cases.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(YFinanceProvider._market_symbol(symbol)[0], expected)
        for symbol in ["", "600519.SH", "SH.600519", "123456", "HK.BAD"]:
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                YFinanceProvider._market_symbol(symbol)

    def test_market_dates_inclusive_end_and_provider_contract(self):
        for symbol, timezone in [("AAPL", "America/New_York"), ("00700.HK", "Asia/Hong_Kong")]:
            with self.subTest(symbol=symbol):
                ticker = Mock()
                ticker.history.return_value = history(timezone)
                factory = Mock(return_value=ticker)
                provider = YFinanceProvider(ticker_factory=factory)
                result = provider.fetch_historical(
                    symbol, timestamp(f"2026-03-06 00:00:00{('-05:00' if symbol == 'AAPL' else '+08:00')}"),
                    timestamp("2026-03-10 02:00:00+08:00") if symbol == "AAPL" else timestamp("2026-03-09 23:00:00+08:00"),
                )
                args = ticker.history.call_args.kwargs
                self.assertEqual(args["start"], "2026-03-06")
                self.assertEqual(args["end"], "2026-03-10")
                self.assertTrue(args["auto_adjust"])
                self.assertTrue(args["raise_errors"])
                self.assertFalse(args["back_adjust"])
                self.assertFalse(args["prepost"])
                bars = format_yfinance_daily_bars(symbol, result)
                self.assertEqual(bars["trade_date"].tolist(), [date(2026, 3, 6), date(2026, 3, 9)])
                self.assertEqual(bars["symbol"].tolist(), [symbol, symbol])
                self.assertEqual(bars["volume"].tolist(), [100, 200])
                self.assertTrue(bars["amount"].isna().all())
                self.assertEqual(bars["source"].tolist(), ["YFinance", "YFinance"])

    def test_raw_offset_empty_and_invalid_arguments(self):
        ticker = Mock()
        ticker.history.return_value = history()
        provider = YFinanceProvider(ticker_factory=lambda _: ticker)
        start, end = timestamp("2026-03-06T05:00:00Z"), timestamp("2026-03-10T00:00:00Z")
        result = provider.fetch_historical("AAPL", start, end, adjust="raw", offset=1)
        self.assertFalse(ticker.history.call_args.kwargs["auto_adjust"])
        self.assertEqual(len(result["data"]["item"]), 1)
        ticker.history.return_value = pd.DataFrame()
        self.assertEqual(provider.fetch_historical("AAPL", start, end), {"data": {"item": []}})
        for kwargs in [{"adjust": "hfq"}, {"interval": "5m"}, {"offset": -1}]:
            with self.assertRaises(ValueError):
                provider.fetch_historical("AAPL", start, end, **kwargs)
        with self.assertRaises(ValueError):
            provider.fetch_historical("AAPL", end, start)

    def test_retries_errors_and_rejects_missing_columns(self):
        ticker = Mock()
        ticker.history.side_effect = [RuntimeError("rate limited"), history()]
        provider = YFinanceProvider(ticker_factory=lambda _: ticker, max_attempts=2, retry_delay=0)
        start, end = timestamp("2026-03-06T05:00:00Z"), timestamp("2026-03-10T00:00:00Z")
        self.assertEqual(len(provider.fetch_historical("AAPL", start, end)["data"]["item"]), 2)
        ticker.history.side_effect = RuntimeError("unavailable")
        with self.assertRaisesRegex(YFinanceProviderError, "AAPL.*unavailable"):
            provider.fetch_historical("AAPL", start, end)
        ticker.history.side_effect = None
        ticker.history.return_value = history().drop(columns="Volume")
        with self.assertRaisesRegex(YFinanceProviderError, "Volume"):
            provider.fetch_historical("AAPL", start, end)

    def test_sync_both_markets_upserts_null_amount_and_preserves_failed_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            hk_db = HKDuckDBDatabase(Path(tmp) / "hk.duckdb")
            us_db = USDuckDBDatabase(Path(tmp) / "us.duckdb")
            app_db = SQLiteDatabase(Path(tmp) / "app.sqlite")
            app_db.initialize()
            watchlists = WatchlistRepository(app_db)
            hk_pool = watchlists.ensure_default_pool("HK")["id"]
            us_pool = watchlists.ensure_default_pool("US")["id"]
            for db, stock_cls, bar_cls, symbol in [
                (hk_db, HKStockRepository, HKDailyBarRepository, "00700.HK"),
                (us_db, USStockRepository, USDailyBarRepository, "AAPL"),
            ]:
                db.initialize()
                stock_cls(db).upsert_stocks(pd.DataFrame([dict(symbol=symbol, name=symbol, source="Manual")]))
                bar_cls(db).upsert_daily_bars(pd.DataFrame([dict(
                    symbol=symbol, trade_date="2026-03-06", open=10, high=12,
                    low=9, close=10, volume=100, amount=1000, source="Futu",
                )]))
                watchlists.add_item(hk_pool if symbol.endswith(".HK") else us_pool,
                                    "HK" if symbol.endswith(".HK") else "US", symbol)
            USStockRepository(us_db).upsert_stocks(pd.DataFrame([
                dict(symbol="FAIL", name="failure", source="Manual")
            ]))
            watchlists.add_item(us_pool, "US", "FAIL")

            def factory(symbol):
                ticker = Mock()
                if symbol == "FAIL":
                    ticker.history.side_effect = RuntimeError("unavailable")
                else:
                    ticker.history.return_value = history("Asia/Hong_Kong" if symbol.endswith(".HK") else "America/New_York")
                return ticker

            provider = YFinanceProvider(ticker_factory=factory, max_attempts=1)
            with patch("backend.scripts.sync_hk_us_daily_bars.time.time", return_value=timestamp("2026-03-10T08:00:00Z") / 1000):
                for _ in range(2):
                    result = sync_hk_us_daily_bars(
                        10, 1, 0, provider=provider, hk_database=hk_db,
                        us_database=us_db, app_database=app_db,
                    )
                    self.assertEqual(result["hk"]["rows"], 2)
                    self.assertEqual(result["us"]["failed_symbols"], ["FAIL"])
            for db, cls in [(hk_db, HKDailyBarRepository), (us_db, USDailyBarRepository)]:
                bars = cls(db).get_table_data()
                self.assertEqual(len(bars), 2)
                self.assertTrue(bars["amount"].isna().all())
                self.assertEqual(bars["source"].tolist(), ["YFinance", "YFinance"])
                # 与生产接口相同的 Pandas -> 响应模型路径，空成交额应输出 JSON null。
                app = FastAPI()

                @app.get("/bars", response_model=list[DailyBar])
                def daily_bars():
                    return bars.to_dict(orient="records")

                with TestClient(app) as client:
                    response = client.get("/bars")
                    self.assertEqual(response.status_code, 200)
                    self.assertIsNone(response.json()[0]["amount"])


if __name__ == "__main__":
    unittest.main()

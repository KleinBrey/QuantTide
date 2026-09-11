from __future__ import annotations

import unittest

import pandas as pd

from backend.app.provider.futu_provider import FutuProvider, FutuProviderError


class FakeQuoteContext:
    def __init__(self, **kwargs) -> None:
        self.options = kwargs
        self.closed = False
        self.history_calls: list[dict] = []

    def close(self) -> None:
        self.closed = True

    def get_stock_basicinfo(self, market, stock_type, code_list=None):
        return 0, pd.DataFrame(
            {
                "code": code_list or [f"{market}.600000"],
                "name": ["贵州茅台"] if code_list else ["浦发银行"],
                "delisting": [False],
            }
        )

    def get_market_snapshot(self, code_list):
        return 0, pd.DataFrame({"code": code_list, "last_price": [1500.0]})

    def get_hot_list(self, **kwargs):
        return 0, (
            6342,
            pd.DataFrame(
                {
                    "security": ["US.AAPL"],
                    "name": ["Apple"],
                    "average_heat": [999.0],
                }
            ),
        )

    def request_history_kline(self, **kwargs):
        self.history_calls.append(kwargs)
        page = len(self.history_calls)
        frame = pd.DataFrame(
            {
                "time_key": [f"2026-09-0{page} 00:00:00"],
                "open": [100.0 + page],
                "high": [102.0 + page],
                "low": [99.0 + page],
                "close": [101.0 + page],
                "volume": [1000 * page],
                "turnover": [100_000.0 * page],
            }
        )
        return 0, frame, b"next" if page == 1 else None


class FutuProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contexts: list[FakeQuoteContext] = []

        def factory(**kwargs):
            context = FakeQuoteContext(**kwargs)
            self.contexts.append(context)
            return context

        self.provider = FutuProvider(context_factory=factory)

    def test_normalizes_supported_a_share_code_formats(self) -> None:
        self.assertEqual(self.provider._futu_code("600519"), "SH.600519")
        self.assertEqual(self.provider._futu_code("600519.sh"), "SH.600519")
        self.assertEqual(self.provider._futu_code("sz.000001"), "SZ.000001")

    def test_fetch_stock_list_adapts_fields_and_closes_context(self) -> None:
        result = self.provider.fetch_stock_list(["600519.SH"])["data"]["item"]

        self.assertEqual(
            result,
            [
                {
                    "ticker": "600519",
                    "name": "贵州茅台",
                    "exchange": "SH",
                    "source": "Futu",
                }
            ],
        )
        self.assertTrue(self.contexts[-1].closed)

    def test_empty_stock_code_list_does_not_open_context(self) -> None:
        result = self.provider.fetch_stock_list([])

        self.assertEqual(result, {"data": {"item": []}})
        self.assertEqual(self.contexts, [])

    def test_fetch_snapshot_uses_futu_code(self) -> None:
        result = self.provider.fetch_snapshot("600519.SH")["data"]["item"]

        self.assertEqual(result[0]["code"], "SH.600519")
        self.assertEqual(result[0]["source"], "Futu")
        self.assertTrue(self.contexts[-1].closed)

    def test_fetch_hot_list_returns_total_and_frame(self) -> None:
        all_count, frame = self.provider.fetch_hot_list(market="us", count=1)

        self.assertEqual(all_count, 6342)
        self.assertEqual(frame.loc[0, "security"], "US.AAPL")
        self.assertEqual(frame.loc[0, "source"], "Futu")
        self.assertTrue(self.contexts[-1].closed)

    def test_fetch_historical_collects_pages_and_adapts_fields(self) -> None:
        result = self.provider.fetch_historical(
            "600519.SH",
            1_787_846_400_000,
            1_788_105_600_000,
        )["data"]["item"]

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["open_price"], 101.0)
        self.assertEqual(result[1]["turnover"], 200_000.0)
        self.assertEqual(result[0]["source"], "Futu")
        self.assertEqual(len(self.contexts[-1].history_calls), 2)
        self.assertEqual(
            self.contexts[-1].history_calls[1]["page_req_key"], b"next"
        )
        self.assertTrue(self.contexts[-1].closed)

    def test_api_error_closes_context(self) -> None:
        context = FakeQuoteContext()
        context.get_market_snapshot = lambda _codes: (-1, "permission denied")
        provider = FutuProvider(context_factory=lambda **_kwargs: context)

        with self.assertRaisesRegex(FutuProviderError, "permission denied"):
            provider.fetch_snapshot("600519.SH")

        self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()

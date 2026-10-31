import json
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.provider import TdxProvider
from backend.app.provider.tdx_provider import TdxProviderError


def timestamp(value):
    return int(pd.Timestamp(value, tz="Asia/Shanghai").timestamp() * 1000)


def market_data():
    values = {
        "Open": [10, 11, 12], "High": [12, 13, 14], "Low": [9, 10, 11],
        "Close": [11, 12, 13], "Volume": [100, 200, 300], "Amount": [1.1, 2.4, 3.9],
    }
    result = {}
    for field, items in values.items():
        frame = pd.DataFrame({"688318.SH": items}, index=pd.to_datetime(["2026-08-26", "2026-08-27", "2026-08-28"]))
        result[field] = frame
    return result


class TdxProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.provider = TdxProvider(client=self.client)
        self.start = timestamp("2026-08-27")
        self.end = timestamp("2026-08-28")

    def test_lazy_import_and_actionable_missing_sdk_error(self):
        with patch.dict(sys.modules, {"tdxaidata": None}):
            provider = TdxProvider()
            with self.assertRaisesRegex(TdxProviderError, "uv sync"):
                provider.fetch_tick_data("688318.SH", "20260827")
        self.assertIs(self.provider.client, self.client)

    def test_symbol_mapping_and_rejection(self):
        cases = {"688318": "688318.SH", "sz.000001": "000001.SZ",
                 " 600519.sh ": "600519.SH", "920001": "920001.BJ",
                 "BJ.830001": "830001.BJ", "000300.SH": "000300.SH",
                 "932000.ZZ": "932000.ZZ", "980112.GZ": "980112.GZ"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(self.provider._stock_code(value), expected)
        for value in ["", "AAPL", "00700.HK", "12345", "SH.600519.SZ"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.provider._stock_code(value)

    def test_historical_contract_dates_units_and_frame_layout(self):
        self.client.get_market_data.return_value = market_data()
        result = self.provider.fetch_historical("SH.688318", self.start, self.end)
        self.client.get_market_data.assert_called_with(
            field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
            stock_list=["688318.SH"], period="1d",
            start_time="2026-08-27 00:00:00", end_time="2026-08-28 23:59:59",
            count=-1, dividend_type="front", fill_data=False,
        )
        rows = result["data"]["item"]
        self.assertEqual([row["date_ms"] for row in rows], [self.start, self.end])
        self.assertEqual(rows[0], dict(open_price=11, high_price=13, low_price=10,
            close_price=12, volume=200, turnover=24000, date_ms=self.start, source="Tdx"))
        self.assertEqual(rows[1]["turnover"], 39000)

    def test_historical_mapping_sorting_offset_and_empty_rows(self):
        data = market_data()
        for field in data:
            data[field] = data[field].iloc[[2, 0, 1, 1]]
        self.client.get_market_data.return_value = data
        for interval, expected in [("daily", "1d"), ("weekly", "1w"), ("1mo", "1mon")]:
            with self.subTest(interval=interval):
                result = self.provider.fetch_historical("688318", self.start, self.end, interval=interval, adjust="hfq", offset=1)
                self.assertEqual([r["date_ms"] for r in result["data"]["item"]], [self.end])
                self.assertEqual(self.client.get_market_data.call_args.kwargs["period"], expected)
                self.assertEqual(self.client.get_market_data.call_args.kwargs["dividend_type"], "back")
        self.client.get_market_data.return_value = {}
        self.assertEqual(self.provider.fetch_historical("688318", self.start, self.end), {"data": {"item": []}})
        self.client.get_market_data.return_value = {key: pd.DataFrame() for key in data}
        self.assertEqual(self.provider.fetch_historical("688318", self.start, self.end), {"data": {"item": []}})

    def test_minute_bars_keep_intraday_times_and_filter_exact_range(self):
        data = market_data()
        for frame in data.values():
            frame.index = pd.to_datetime(["2026-08-27 09:30", "2026-08-27 09:31", "2026-08-27 09:32"])
        self.client.get_market_data.return_value = data
        result = self.provider.fetch_historical("688318.SH", timestamp("2026-08-27 09:31"), timestamp("2026-08-27 09:32"), interval="1m", adjust="raw")
        self.assertEqual(len(result["data"]["item"]), 2)
        self.assertEqual(result["data"]["item"][0]["date_ms"], timestamp("2026-08-27 09:31"))
        self.assertEqual(self.client.get_market_data.call_args.kwargs["dividend_type"], "none")

    def test_daily_bars_normalize_market_dates_and_ignore_no_data_rows(self):
        data = market_data()
        for frame in data.values():
            frame.index = pd.date_range("2026-08-26 15:00", periods=3, tz="Asia/Shanghai")
        data["Open"].iloc[0, 0] = float("nan")
        self.client.get_market_data.return_value = data
        result = self.provider.fetch_historical("688318", timestamp("2026-08-26"), self.end)
        self.assertEqual([r["date_ms"] for r in result["data"]["item"]], [self.start, self.end])

    def test_installed_sdk_adapter_without_loading_native_library(self):
        from tdxaidata import tqs

        native = Mock()
        native.get_his_dats.return_value = json.dumps({
            "ErrorId": 0, "Date": [20260827], "Time": [0],
            "Open": [11], "High": [13], "Low": [10], "Close": [12],
            "Volume": [200], "Amount": [2.4],
        })
        native.get_tick_data.return_value = json.dumps({
            "Time": ["093000", "093000"], "Price": ["11", "12"],
            "Volume": ["10", "20"], "BSFlag": ["0", "1"], "TotalNum": 2,
        })
        native.get_minute_data.return_value = json.dumps({
            "Time": ["093000"], "Price": ["11"], "Average": ["11.2"], "Volume": ["30"],
        })
        with patch.object(tqs, "_tdx", return_value=native):
            provider = TdxProvider(client=tqs)
            bars = provider.fetch_historical("688318.SH", self.start, self.end)["data"]["item"]
            ticks = provider.fetch_tick_data("688318.SH", "20260827")["data"]["item"]
            minutes = provider.fetch_minute_data("688318.SH", "20260827", ["Time", "Average"])["data"]["item"]
        self.assertEqual(bars[0]["turnover"], 24000)
        self.assertEqual(bars[0]["volume"], 200)
        self.assertEqual(bars[0]["date_ms"], self.start)
        self.assertEqual(len(ticks), 2)
        self.assertEqual(ticks[0]["bs_flag"], "0")
        self.assertEqual(minutes[0]["average_price"], 11.2)
        self.assertNotIn("price", minutes[0])

    def test_bad_historical_arguments_do_not_request_data(self):
        for kwargs in [dict(offset=-1), dict(interval="tick"), dict(adjust="unsupported")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.provider.fetch_historical("688318", self.start, self.end, **kwargs)
        with self.assertRaises(ValueError):
            self.provider.fetch_historical("688318", self.end, self.start)
        self.client.get_market_data.assert_not_called()

    def test_malformed_or_truncated_historical_data_is_rejected(self):
        for corruption in ("missing", "wrong_code", "misaligned", "infinite", "bad_date", "limit"):
            with self.subTest(corruption=corruption):
                data = market_data()
                if corruption == "missing":
                    del data["Amount"]
                elif corruption == "wrong_code":
                    data["Open"] = data["Open"].rename(columns={"688318.SH": "000001.SZ"})
                elif corruption == "misaligned":
                    data["Low"] = data["Low"].iloc[::-1]
                elif corruption == "infinite":
                    data["Amount"].iloc[0, 0] = float("inf")
                elif corruption == "bad_date":
                    for frame in data.values():
                        frame.index = ["bad", "dates", "here"]
                else:
                    data["Open"] = pd.DataFrame({"688318.SH": [1] * 24000})
                self.client.get_market_data.return_value = data
                with self.assertRaises(TdxProviderError):
                    self.provider.fetch_historical("688318", self.start, self.end)

    def test_ticks_keep_same_second_trades_and_buy_sell_flags(self):
        self.client.get_tick_data.return_value = pd.DataFrame({
            "Time": ["093000", "093000"], "Price": ["76.26", "76.61"],
            "Volume": ["43", "2"], "BSFlag": ["0", "1"],
        })
        rows = self.provider.fetch_tick_data("SH.688318", "20260827", startxh=5, wantnum=2)["data"]["item"]
        self.client.get_tick_data.assert_called_once_with(stock_code="688318.SH", date="2026-08-27", startxh=5, wantnum=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["bs_flag"] for r in rows], ["0", "1"])
        self.assertEqual(rows[0], dict(time="093000", price=76.26, volume=43, bs_flag="0", ticker="688318.SH", source="Tdx"))

    def test_minute_field_selection_and_empty_data(self):
        self.client.get_minute_data.return_value = {"Time": ["093000"], "Price": ["11.36"]}
        result = self.provider.fetch_minute_data("000001.SZ", "2026-08-27 12:00:00", field_list=["Time", "Price"])
        self.client.get_minute_data.assert_called_once_with(stock_code="000001.SZ", date="2026-08-27", field_list=["Time", "Price"])
        self.assertEqual(result["data"]["item"][0]["price"], 11.36)
        self.assertNotIn("volume", result["data"]["item"][0])
        for empty in ({}, {"TotalNum": 0}, [], pd.DataFrame()):
            self.client.get_minute_data.return_value = empty
            self.assertEqual(self.provider.fetch_minute_data("000001", "20260827")["data"]["item"], [])

    def test_auction_preserves_negative_unmatched_volume(self):
        self.client.get_call_auction.return_value = {"Time": ["091505"], "Price": ["79"], "Volume": ["9"], "LeaveQty": ["-5"], "TotalNum": 1}
        result = self.provider.fetch_call_auction("688318")
        self.assertEqual(result["data"]["item"][0]["unmatched_volume"], -5)
        self.assertEqual(result["data"]["total_num"], 1)

    def test_index_constituents_preserve_explicit_index_market(self):
        self.client.get_zzgz_stocklist.return_value = ["000001.SZ", "600000.SH"]
        rows = self.provider.fetch_index_constituents("000300.SH")["data"]["item"]
        self.client.get_zzgz_stocklist.assert_called_once_with(index_code="000300.SH", list_type=0)
        self.assertEqual(rows[0], dict(ticker="000001.SZ", exchange="SZ", source="Tdx"))

    def test_invalid_intraday_arguments_do_not_request_data(self):
        for kwargs in [dict(startxh=-1), dict(wantnum=0), dict(wantnum=2001)]:
            with self.assertRaises(ValueError):
                self.provider.fetch_tick_data("688318", "20260827", **kwargs)
        for day in ["", "2026-02-30", "yesterday", None]:
            with self.subTest(day=day), self.assertRaises(ValueError):
                self.provider.fetch_tick_data("688318", day)
        self.client.get_tick_data.assert_not_called()

    def test_intraday_errors_are_not_empty_success(self):
        for value in (None, {"ErrorId": "7", "Error": "bad token"}, {"Time": ["093000"], "Price": []}, {"Price": ["NaN"]}, {"Price": ["inf"]}, "bad response"):
            with self.subTest(value=value):
                self.client.get_tick_data.return_value = value
                with self.assertRaises(TdxProviderError):
                    self.provider.fetch_tick_data("688318", "20260827")
        self.client.get_tick_data.side_effect = OSError("native failure")
        with self.assertRaises(TdxProviderError) as context:
            self.provider.fetch_tick_data("688318", "20260827")
        self.assertIsInstance(context.exception.__cause__, OSError)

    def test_subscription_forwards_raw_callback_and_cleans_up_after_exception(self):
        callback = Mock()
        codes = (value for value in ["SH.688318", "688318.SH"])
        with self.assertRaisesRegex(RuntimeError, "consumer failed"):
            with self.provider.subscription(codes, callback):
                self.client.subscribe.assert_called_once_with(stock_list=["688318.SH"], callback=callback)
                callback('{"ErrorId": 0, "ResultSets": []}')
                raise RuntimeError("consumer failed")
        self.client.unsubscribe.assert_called_once_with(stock_list=["688318.SH"])
        callback.assert_called_once_with('{"ErrorId": 0, "ResultSets": []}')

    def test_subscription_rejects_invalid_arguments_and_cleans_up_partial_failure(self):
        with self.assertRaises(ValueError):
            self.provider.subscribe([], print)
        with self.assertRaises(ValueError):
            self.provider.subscribe(["688318"], None)
        self.client.subscribe.assert_not_called()
        self.client.subscribe.side_effect = OSError("subscribe failed")
        with self.assertRaises(TdxProviderError):
            with self.provider.subscription(["688318"], print):
                self.fail("failed subscription must not enter body")
        self.client.unsubscribe.assert_called_once_with(stock_list=["688318.SH"])


if __name__ == "__main__":
    unittest.main()

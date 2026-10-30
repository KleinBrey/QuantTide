import unittest
from unittest.mock import Mock, patch

import requests

from backend.app.provider import BinanceProvider


def kline(open_time):
    return [open_time, "10.1", "12", "9", "11", "2.5",
            open_time + 59999, "27.5", 3, "1", "11", "0"]


class BinanceProviderTests(unittest.TestCase):
    @patch("backend.app.provider.binance_provider.requests.get")
    def test_historical_pagination_fields_and_offset(self, get):
        first_page = [kline(i * 60000) for i in range(1000)]
        get.side_effect = [
            Mock(json=Mock(return_value=first_page)),
            Mock(json=Mock(return_value=[kline(60000000)])),
        ]
        provider = BinanceProvider(timeout=8, base_url="https://api.binance.com/")
        items = provider.fetch_historical(
            " btcusdt ", 0, 60000000, interval="1m", offset=999
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[-1], {
            "date_ms": 60000000, "open_price": 10.1, "high_price": 12.0,
            "low_price": 9.0, "close_price": 11.0, "volume": 2.5,
            "turnover": 27.5, "source": "Binance",
        })
        first, second = get.call_args_list
        self.assertEqual(first.args[0], "https://api.binance.com/api/v3/klines")
        self.assertEqual(first.kwargs, {"timeout": 8, "params": {
            "symbol": "BTCUSDT", "interval": "1m", "startTime": 0,
            "endTime": 60000000, "limit": 1000,
        }})
        self.assertEqual(second.kwargs["params"]["startTime"], 59940001)

    @patch("backend.app.provider.binance_provider.requests.get")
    def test_intervals_and_empty_result(self, get):
        get.return_value.json.return_value = []
        provider = BinanceProvider()
        for interval, expected in [("1m", "1m"), ("1M", "1M"), ("1mo", "1M"),
                                   ("daily", "1d"), ("weekly", "1w"), ("monthly", "1M")]:
            with self.subTest(interval=interval):
                self.assertEqual(provider.fetch_historical("BTCUSDT", 0, 0, interval),
                                 [])
                self.assertEqual(get.call_args.kwargs["params"]["interval"], expected)

    @patch("backend.app.provider.binance_provider.requests.get")
    def test_public_market_endpoints(self, get):
        provider = BinanceProvider()
        cases = [
            (provider.fetch_snapshot, {}, "ticker/24hr", {"symbol": "BTCUSDT", "lastPrice": "10.12345678"}),
            (provider.fetch_depth, {"limit": 5}, "depth", {"lastUpdateId": 1, "bids": [["10", "2"]], "asks": []}),
            (provider.fetch_trades, {"limit": 5}, "trades", [{"id": 1, "price": "10", "qty": "2", "time": 123}]),
        ]
        for method, kwargs, endpoint, payload in cases:
            with self.subTest(endpoint=endpoint):
                get.return_value.json.return_value = payload
                expected = (
                    [{**row, "source": "Binance"} for row in payload]
                    if isinstance(payload, list)
                    else {**payload, "source": "Binance"}
                )
                self.assertEqual(method("btcusdt", **kwargs), expected)
                self.assertEqual(get.call_args.args[0], f"https://api.binance.com/api/v3/{endpoint}")
                self.assertEqual(get.call_args.kwargs["params"], {"symbol": "BTCUSDT", **kwargs})

    @patch("backend.app.provider.binance_provider.requests.get")
    def test_invalid_arguments_do_not_request(self, get):
        provider = BinanceProvider()
        for kwargs in [{"interval": "2d"}, {"adjust": "forward"}, {"offset": -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                provider.fetch_historical("BTCUSDT", 0, 1, **kwargs)
        with self.assertRaises(ValueError):
            provider.fetch_historical("BTCUSDT", 2, 1)
        with self.assertRaises(ValueError):
            provider.fetch_snapshot(" ")
        for method, limits in [(provider.fetch_depth, [0, 5001]),
                               (provider.fetch_trades, [0, 1001])]:
            for limit in limits:
                with self.assertRaises(ValueError):
                    method("BTCUSDT", limit=limit)
        get.assert_not_called()

    @patch("backend.app.provider.binance_provider.requests.get")
    def test_http_and_network_errors_propagate(self, get):
        get.return_value.raise_for_status.side_effect = requests.HTTPError("429")
        with self.assertRaises(requests.HTTPError):
            BinanceProvider().fetch_historical("BTCUSDT", 0, 1)
        get.return_value.json.assert_not_called()
        get.side_effect = requests.Timeout("timeout")
        with self.assertRaises(requests.Timeout):
            BinanceProvider().fetch_snapshot("BTCUSDT")


if __name__ == "__main__":
    unittest.main()

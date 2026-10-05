"""用独立策略验证共用引擎、账户隔离和 API 分发，无需本地行情库。"""

import unittest
from unittest.mock import Mock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import router
from backend.quant.backtest.engine import BacktestConfig, BacktestEngine
from backend.quant.strategy.registry import STRATEGIES
from backend.quant.strategy.today_confirmed_breakout import (
    ENTRY_COLUMNS,
    TodayConfirmedBreakoutStrategy,
)


class HoldOneDayStrategy:
    """测试策略：按排名买入，下一交易日卖出，不设止盈止损。"""

    id = "test_hold_one_day"
    name = "持有一天"
    description = "只用于测试"

    def generate_entries_range(self, trade_dates, stocks, daily_bars, hot_stocks, stock_daily_basic):
        self.calendar = trade_dates
        self.bars_end = daily_bars.trade_date.max()
        return pd.DataFrame([
            dict(symbol=symbol, name=symbol, entry_date=trade_dates[0],
                 signal_date=trade_dates[0], selection_rank=rank, entry_reason="test_buy")
            for symbol, rank in [("A", 2), ("B", 1)]
        ])

    def find_exits(self, entries, daily_bars):
        return entries[["symbol", "entry_date"]].assign(
            exit_date=self.calendar[1], exit_reason="held_one_day"
        )

    def assumptions(self):
        return []


class HoldToEndStrategy(HoldOneDayStrategy):
    id = "test_hold_to_end"
    name = "持有到期末"

    def find_exits(self, entries, daily_bars):
        return pd.DataFrame(columns=["symbol", "entry_date", "exit_date", "exit_reason"])


def sample_data():
    dates = pd.date_range("2026-09-21", periods=3)
    bars = pd.DataFrame([
        dict(symbol=symbol, trade_date=day, open=price, high=price, low=price,
             close=price, volume=1000)
        for day, price in zip(dates, [10.0, 11.0, 12.0])
        for symbol in ["A", "B"]
    ])
    return dict(stocks=pd.DataFrame(), daily_bars=bars,
                hot_stocks=pd.DataFrame(), stock_daily_basic=pd.DataFrame())


class BacktestStrategyTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()
        self.config = BacktestConfig(
            initial_cash=10000, max_positions=1, max_position_pct=1,
            commission_rate=0, minimum_commission=0, sell_tax_rate=0,
        )

    def test_generic_strategy_without_breakout_fields_or_stop_prices(self):
        result = BacktestEngine(HoldOneDayStrategy(), self.config).run(**self.data)
        self.assertEqual(result.trades.symbol.tolist(), ["B", "B"])
        self.assertEqual(result.trades.side.tolist(), ["BUY", "SELL"])
        self.assertEqual(result.trades.reason.tolist(), ["test_buy", "held_one_day"])
        self.assertEqual(result.trades.quantity.tolist(), [1000, 1000])
        self.assertTrue(result.trades.stop_loss_price.isna().all())
        self.assertEqual(result.equity_curve.total_equity.tolist(), [10000, 11000, 11000])
        self.assertEqual(result.metadata["skipped_full_position_count"], 1)

    def test_strategies_and_repeated_runs_have_independent_accounts(self):
        first_engine = BacktestEngine(HoldOneDayStrategy(), self.config)
        first = first_engine.run(**self.data)
        held = BacktestEngine(HoldToEndStrategy(), self.config).run(**self.data)
        repeated = first_engine.run(**self.data)
        self.assertEqual(held.summary()["final_equity"], 12000)
        self.assertEqual(len(held.final_positions), 1)
        pd.testing.assert_frame_equal(first.trades, repeated.trades)
        pd.testing.assert_frame_equal(first.equity_curve, repeated.equity_curve)

    def test_history_is_cut_at_configured_end_date(self):
        strategy = HoldOneDayStrategy()
        config = BacktestConfig(start_date="2026-09-21", end_date="2026-09-22")
        result = BacktestEngine(strategy, config).run(**self.data)
        self.assertEqual(strategy.bars_end, pd.Timestamp("2026-09-22"))
        self.assertEqual(len(result.equity_curve), 2)

    def test_breakout_maps_dates_and_keeps_its_exit_rules(self):
        signal = {column: None for column in ENTRY_COLUMNS}
        signal.update(symbol="A", name="A", confirm_date=pd.Timestamp("2026-09-21"),
                      breakout_date=pd.Timestamp("2026-09-18"), confirm_close=10.0,
                      breakout_prev_close=9.5, selection_rank=1)
        pattern = Mock()
        pattern.scan_range.return_value = pd.DataFrame([signal])
        strategy = TodayConfirmedBreakoutStrategy(pattern=pattern)
        result = BacktestEngine(strategy, self.config).run(**self.data)
        self.assertEqual(result.trades.reason.tolist(), ["confirm_buy", "take_profit"])
        self.assertEqual(result.trades.price.tolist(), [10.0, 11.0])
        self.assertEqual(result.trades.iloc[0].signal_date.isoformat(), "2026-09-18")
        self.assertEqual(result.trades.iloc[0].stop_loss_price, 9.5)
        self.assertEqual(result.trades.iloc[0].take_profit_price, 11.0)

    def test_empty_entries_keep_flat_equity(self):
        pattern = Mock()
        pattern.scan_range.return_value = pd.DataFrame()
        strategy = TodayConfirmedBreakoutStrategy(pattern=pattern)
        result = BacktestEngine(strategy, self.config).run(**self.data)
        self.assertTrue(result.trades.empty)
        self.assertEqual(result.equity_curve.total_equity.tolist(), [10000] * 3)


class BacktestApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        data = sample_data()
        for attribute, key in [
            ("stock_repository", "stocks"), ("daily_repository", "daily_bars"),
            ("stock_hot_repository", "hot_stocks"),
            ("stock_daily_basic_repository", "stock_daily_basic"),
        ]:
            repository = Mock()
            repository.get_table_data.return_value = data[key]
            setattr(app.state, attribute, repository)
        self.client = TestClient(app)

    def test_list_and_dispatch_registered_strategies(self):
        with patch.dict(STRATEGIES, {
            HoldOneDayStrategy.id: HoldOneDayStrategy,
            HoldToEndStrategy.id: HoldToEndStrategy,
        }):
            listed = self.client.get("/api/backtests/strategies")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()[0]["id"], "confirmed_volume_breakout")
            self.assertEqual(listed.json()[-1]["id"], HoldToEndStrategy.id)
            for strategy in [HoldOneDayStrategy, HoldToEndStrategy]:
                with self.subTest(strategy=strategy.id):
                    url = f"/api/backtests/{strategy.id}"
                    params = dict(initial_cash=10000, max_positions=1, max_position_pct=0.5)
                    response = self.client.get(url, params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertEqual(result["strategy"]["id"], strategy.id)
                    self.assertEqual(len(result["trades"]), 2 if strategy is HoldOneDayStrategy else 1)
                    self.assertEqual(result["metadata"]["max_positions"], 1)
                    self.assertIsNone(result["trades"][0]["stop_loss_price"])
                    self.assertEqual(result["trades"][0]["quantity"], 400)
                    self.assertEqual(result["trades"][0]["fee"], 5)
                    # 每次请求创建新策略和账户，重跑不能继承上次持仓。
                    rerun = self.client.get(url, params=params).json()
                    self.assertEqual(result["trades"], rerun["trades"])
                    self.assertEqual(result["equity_curve"], rerun["equity_curve"])

    def test_unknown_strategy_and_invalid_parameters(self):
        self.assertEqual(self.client.get("/api/backtests/missing").status_code, 404)
        response = self.client.get("/api/backtests/confirmed_volume_breakout?max_positions=0")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

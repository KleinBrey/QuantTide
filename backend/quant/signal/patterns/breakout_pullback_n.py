"""选股信号：强势上涨 → 缩量回调 → 最新一根放量大阳线。

整体思路（把一只股票的日 K 线从左到右看）：

    ① 上涨段   连续几天涨得又快又稳（例如涨了 10% 以上）
    ② 回调段   涨完之后回落，并且成交量萎缩（说明没人急着卖）
    ③ 确认日   最新一天突然放量拉出一根大阳线（说明资金回来了）

只有三段全部满足，这只股票才会被选出来。

"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from rich.console import Console

from backend.quant.signal.range_utils import (
    DateLike, normalize_trade_dates, select_by_snapshot, trim_history_bars,
)

from backend.app.database import DuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    DailyBasicRepository,
    DailyHotRepository,
    DailyStockRepository,
)

console = Console()

# 让中文在终端表格里尽量对齐。
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)


# ============================================================
# 1. 参数配置：所有阈值集中放这里
# ============================================================

# 日 K 数据必须包含的列。
REQUIRED_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]

# 形态识别阶段输出的列。
SIGNAL_COLUMNS = [
    "symbol",
    "date",
    "close",
    "return_1d",
    "volume_ratio",
    "breakout_return",
    "pullback_depth",
    "pullback_volume_ratio",
]

# 最终结果的列（拼上股票信息之后）。
RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "latest_date",
    "latest_close",
    "latest_1d_pct",
    "volume_ratio",
    "breakout_return",
    "pullback_depth",
    "pullback_volume_ratio",
    "signal_stage",
    "hot_rank",
]

# 终端展示用：英文列名 → 中文列名（顺序就是展示顺序）。
DISPLAY_NAMES = {
    "symbol": "股票代码",
    "name": "股票名称",
    "market_cap": "市值(亿)",
    "latest_close": "最新价",
    "latest_1d_pct": "今日涨幅(%)",
    "volume_ratio": "确认量比",
    "breakout_return": "突破涨幅(%)",
    "pullback_depth": "回调幅度(%)",
    "pullback_volume_ratio": "回调量比",
    "signal_stage": "信号阶段",
    "hot_rank": "热度排名",
}


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """信号识别的阈值参数"""

    # ---------- ① 上涨段 ----------
    # 上涨段最小持续交易日 3
    min_breakout_days: int = 3
    # 上涨段最大持续交易日 25
    max_breakout_days: int = 25
    # 涨幅至少 10%（以上涨开始前一天的收盘价为起点）
    min_breakout_return: float = 0.10
    # 上涨"效率"：净涨幅 / 每天涨跌幅度的总和。
    # 越接近 1 说明涨得越"直"，来回震荡凑出来的涨幅会被排除。
    min_breakout_efficiency: float = 0.65

    # ---------- ② 回调段 ----------
    # 最少回调天数 3
    min_pullback_days: int = 3
    # 最多回调天数 40
    max_pullback_days: int = 40
    # 最小回调幅度 3%
    min_pullback_depth: float = 0.03
    # 最大回调幅度 30%
    max_pullback_depth: float = 0.30
    # 回吐比例：回调吞掉了前面上涨空间的多少，最多 50%
    max_pullback_retracement: float = 0.50
    # 回调期间的平均成交量，不能超过上涨期平均量的 75%（缩量）
    max_pullback_volume_ratio: float = 0.75
    # 确认日前一天的收盘价，要比上涨段最高收盘价至少低 2%。
    min_pullback_end_discount: float = 0.02

    # ---------- ③ 确认日（最新一根大阳线） ----------
    # 实体涨幅（收盘相对开盘）至少 4%。
    min_confirm_body: float = 0.04
    # 当日涨幅（收盘相对前一日收盘）至少 4%。
    min_confirm_return: float = 0.04
    # 实体占整根 K 线（最高-最低）的比例，至少 60%，即影线要短。
    min_confirm_body_ratio: float = 0.60
    # 收盘价在当日区间的位置，至少在上 25% 的位置。
    min_confirm_close_position: float = 0.75
    # 确认日成交量 / 回调期平均成交量，至少 1.8 倍（放量）。
    min_confirm_volume_ratio: float = 1.80
    # 回调期均量有两种算法：整段回调 或 最近 N 天，取较小的那个。
    confirm_volume_days: int = 5
    # 防止"回调缩得太狠，随便一点量就算放量"：
    # 确认日成交量还必须达到上涨期均量的 80%。
    min_confirm_breakout_volume_ratio: float = 0.80

    @property
    def max_required_days(self) -> int:
        """最长形态所需的最大交易日数，含基准日和确认日。"""
        return self.max_breakout_days + self.max_pullback_days + 2

    @property
    def min_required_days(self) -> int:
        """最短形态所需的最少交易日数，含基准日和确认日。"""
        return self.min_breakout_days + self.min_pullback_days + 2


DEFAULT_CONFIG = SignalConfig()


# ============================================================
# 2. 数据读取
# ============================================================


def load_market_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """从本地数据库读取：股票列表、日 K、热度、基本面。"""

    database = DuckDBDatabase()
    latest_stocks = DailyStockRepository(database).get_latest_data()
    daily_bars = DailyBarRepository(database).get_table_data()
    latest_hot = DailyHotRepository(database).get_latest_data()
    latest_basic = DailyBasicRepository(database).get_latest_data()
    return latest_stocks, daily_bars, latest_hot, latest_basic


# ============================================================
# 3. 形态判断（核心）
#    先把一只股票的价格装进 Prices，再分别判断三段。
# ============================================================


@dataclass(frozen=True, slots=True)
class Prices:
    """一只股票一个时间窗口内的价格和成交量（每个字段都是按日期排好的数组）。

    取值小技巧：close[-1] 是最后一天（确认日），close[-2] 是倒数第二天。
    """

    open_: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @classmethod
    def from_bars(cls, bars: pd.DataFrame) -> Prices:
        """把 DataFrame 转成 numpy 数组（数组计算更快）。"""
        values = bars[["open", "high", "low", "close", "volume"]].to_numpy(
            dtype=float, na_value=float("nan")
        )
        return cls(*values.T)

    def is_valid(self) -> bool:
        """检查数据有没有问题。有问题就整个窗口不要，避免算出假信号。"""
        all_values = np.vstack(
            [self.open_, self.high, self.low, self.close, self.volume]
        )
        # 所有数字必须是正数，且不能是空值/无穷大（零成交量也会被排除）。
        if not ((all_values > 0) & np.isfinite(all_values)).all():
            return False
        # 最高价必须是最高的；最低价必须是最低的。
        high_is_wrong = (
            (self.high < self.open_) | (self.high < self.close) | (self.high < self.low)
        )
        low_is_wrong = (self.low > self.open_) | (self.low > self.close)
        return not (high_is_wrong.any() or low_is_wrong.any())


@dataclass(frozen=True, slots=True)
class PullbackInfo:
    """回调段通过检查后，记录下来的关键数据。"""

    peak_close: float  # 上涨段最高收盘价
    peak_high: float  # 上涨段最高价
    low: float  # 回调期间最低价
    depth: float  # 回调幅度（负数，例如 -0.08 表示跌了 8%）
    avg_volume: float  # 回调期平均成交量
    late_avg_volume: float  # 回调最后 3 天平均成交量
    confirm_volume_ratio: float  # 确认日成交量 / 回调均量


def check_confirm(p: Prices, config: SignalConfig) -> bool:
    """③ 判断最新一根 K 线是否为强势突破大阳线。"""

    open_price = p.open_[-1]  # 今日开盘价
    high_price = p.high[-1]  # 今日最高价
    low_price = p.low[-1]  # 今日最低价
    close_price = p.close[-1]  # 今日收盘价
    prev_close = p.close[-2]  # 昨日收盘价

    # 当日振幅区间：最高价 - 最低价
    candle_range = high_price - low_price
    if candle_range <= 0:
        return False

    # 阳线实体长度：收盘价 - 开盘价
    body = close_price - open_price

    # 实体涨幅：相对于开盘价的涨幅
    body_return = body / open_price

    # 当日涨幅：相对于昨日收盘价的涨幅
    daily_return = close_price / prev_close - 1

    # 实体占比：实体长度 / 当日振幅区间，越大说明实体越饱满
    body_ratio = body / candle_range

    # 收盘位置：收盘价在最高价和最低价之间的位置
    # 越接近 1，说明收盘价越接近当日最高价
    close_position = (close_price - low_price) / candle_range

    # 实体涨幅至少 4%
    if body_return < config.min_confirm_body:
        return False

    # 当日涨幅至少 4%
    if daily_return < config.min_confirm_return:
        return False

    # 阳线实体至少占整根 K 线振幅的 60%，排除长影线
    if body_ratio < config.min_confirm_body_ratio:
        return False

    # 收盘价必须位于当日振幅的上方 25% 区域
    if close_position < config.min_confirm_close_position:
        return False

    # 获取最近 N 根 K 线的最高价（不包含今天）
    # 默认检查最近 3 根，且不超过最短回调天数
    recent_days = min(3, config.min_pullback_days)
    max_recent_high = p.high[-recent_days - 1 : -1].max()

    # 今日收盘价必须严格高于近期最高价
    if close_price <= max_recent_high:
        return False

    # 所有条件满足，确认信号成立
    return True


def check_pullback(
    p: Prices, breakout_end: int, config: SignalConfig
) -> PullbackInfo | None:
    """② 假设上涨在 breakout_end 这天结束，检查之后的回调是否合格。

    合格返回 PullbackInfo，不合格返回 None。
    """

    latest = len(p.close) - 1
    pullback = slice(breakout_end + 1, latest)  # 回调段：上涨结束的次日 ~ 确认日前一天
    peak_close = p.close[breakout_end]
    peak_high = p.high[breakout_end]

    # --- 价格方面 ---
    # 回调期间不能再创新高（否则说明上涨还没结束）。
    if p.high[pullback].max() > peak_high or p.close[pullback].max() > peak_close:
        return None

    # 回调幅度要在合理范围：太浅不算回调，太深说明走坏了。
    low = p.low[pullback].min()
    depth = low / peak_high - 1
    if not -config.max_pullback_depth <= depth <= -config.min_pullback_depth:
        return None

    # 确认日前一天的收盘，要明显低于上涨最高收盘价。
    if p.close[-2] > peak_close * (1 - config.min_pullback_end_discount):
        return None

    # 回调中允许反弹，但确认日收盘要高过回调最后 3 天的最高价。
    if p.close[-1] <= p.high[pullback][-3:].max():
        return None

    # --- 成交量方面 ---
    avg_volume = p.volume[pullback].mean()
    late_avg_volume = p.volume[pullback][-3:].mean()
    recent_avg_volume = p.volume[pullback][-config.confirm_volume_days :].mean()
    # 回调初期可能还有放量，所以取"整段均量"和"最近几天均量"中较小的，
    # 等价于：任意一种算法达到放量门槛就行。
    confirm_volume_ratio = p.volume[-1] / min(avg_volume, recent_avg_volume)
    if confirm_volume_ratio < config.min_confirm_volume_ratio:
        return None

    return PullbackInfo(
        peak_close=peak_close,
        peak_high=peak_high,
        low=low,
        depth=depth,
        avg_volume=avg_volume,
        late_avg_volume=late_avg_volume,
        confirm_volume_ratio=confirm_volume_ratio,
    )


def check_rise(
    p: Prices,
    breakout_end: int,
    pullback: PullbackInfo,
    daily_moves: np.ndarray,
    config: SignalConfig,
) -> tuple[float, float] | None:
    """① 上涨段在 breakout_end 结束，往前试各种长度，看有没有一段合格。

    合格返回 (突破涨幅, 回调量比)，不合格返回 None。
    daily_moves 是"每天收盘价变动的绝对值"，用来算上涨效率。
    """

    for rise_days in range(config.min_breakout_days, config.max_breakout_days + 1):
        start = breakout_end - rise_days + 1  # 上涨段第一天
        if start < 1:
            break  # 再往前就没数据了，更长的上涨段也不可能成立
        rise = slice(start, breakout_end + 1)
        base_close = p.close[start - 1]  # 上涨开始前一天的收盘价，作为涨幅起点

        # --- 涨幅和涨得"直不直" ---
        breakout_return = pullback.peak_close / base_close - 1
        if breakout_return < config.min_breakout_return:
            continue
        # 峰值必须是上涨段内的最高点。
        if (
            pullback.peak_close < p.close[rise].max()
            or pullback.peak_high < p.high[rise].max()
        ):
            continue
        travel = daily_moves[start - 1 : breakout_end].sum()  # 每天涨跌幅度累加
        if travel <= 0:
            continue
        efficiency = (pullback.peak_close - base_close) / travel
        if efficiency < config.min_breakout_efficiency:
            continue

        # --- 回吐比例：回调吞掉了多少上涨空间 ---
        retracement = (pullback.peak_high - pullback.low) / (
            pullback.peak_high - base_close
        )
        if retracement > config.max_pullback_retracement:
            continue

        # --- 量能对比：回调是不是明显缩量 ---
        rise_avg_volume = p.volume[rise].mean()
        pullback_volume_ratio = pullback.avg_volume / rise_avg_volume
        late_ratio = pullback.late_avg_volume / rise_avg_volume
        if (
            pullback_volume_ratio > config.max_pullback_volume_ratio
            or late_ratio > config.max_pullback_volume_ratio
        ):
            continue
        # 确认日的量，至少要达到上涨期均量的一定比例。
        if p.volume[-1] / rise_avg_volume < config.min_confirm_breakout_volume_ratio:
            continue

        return breakout_return, pullback_volume_ratio

    return None


def find_latest_signal(
    bars: pd.DataFrame, config: SignalConfig
) -> dict[str, object] | None:
    """以窗口最后一天为确认日，判断这只股票是否出现信号。

    思路：先检查确认日，再从"最短回调"开始，逐步假设上涨在更早的某天结束，
    每个假设依次检查 ② 回调 和 ① 上涨，第一个全部通过的就是信号。
    """

    # 数据太少，或数据有问题：直接放弃。
    if len(bars) < config.min_required_days:
        return None
    p = Prices.from_bars(bars)
    if not p.is_valid():
        return None

    # 先看确认日（最便宜的检查放最前面，大部分股票在这里就被淘汰了）。
    if not check_confirm(p, config):
        return None

    latest = len(p.close) - 1
    # 上涨结束日的可选范围：最晚是"回调刚好 min_pullback_days 天"，
    # 最早是"回调长达 max_pullback_days 天"。
    latest_breakout_end = latest - config.min_pullback_days - 1
    earliest_breakout_end = max(
        config.min_breakout_days,  # 上涨段前保留一根 K 线作涨幅基准。
        latest - config.max_pullback_days - 1,
    )
    daily_moves = np.abs(np.diff(p.close))

    # 从最近的结束日往前试。
    for breakout_end in range(latest_breakout_end, earliest_breakout_end - 1, -1):
        pullback = check_pullback(p, breakout_end, config)
        if pullback is None:
            continue
        rise = check_rise(p, breakout_end, pullback, daily_moves, config)
        if rise is None:
            continue

        breakout_return, pullback_volume_ratio = rise
        last_bar = bars.iloc[-1]
        # 同一只股票同一天，只记录找到的第一组。
        return {
            "symbol": last_bar["symbol"],
            "date": last_bar["date"],
            "close": p.close[-1],
            "return_1d": p.close[-1] / p.close[-2] - 1,
            "volume_ratio": pullback.confirm_volume_ratio,
            "breakout_return": breakout_return,
            "pullback_depth": pullback.depth,
            "pullback_volume_ratio": pullback_volume_ratio,
        }

    return None


# ============================================================
# 4. 批量扫描所有股票
# ============================================================


def clean_daily_bars(
    df: pd.DataFrame,
    config: SignalConfig,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """整理日 K 数据：检查列、转类型、去重、排序、裁剪日期。

    返回 (整理后的数据, 确认日起始日期)。
    """

    missing = [column for column in REQUIRED_COLUMNS if column not in df]
    if missing:
        raise ValueError(f"日 K 数据缺少字段：{', '.join(missing)}")

    bars = df[REQUIRED_COLUMNS].copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="raise")
    for column in ["open", "high", "low", "close", "volume"]:
        bars[column] = pd.to_numeric(bars[column], errors="raise")

    end_date = end_date if end_date is not None else bars["date"].max()
    start_date = start_date if start_date is not None else end_date

    bars = (
        bars[bars["date"] <= end_date]
        .sort_values(["symbol", "date"], kind="stable")
        .drop_duplicates(["symbol", "date"], keep="last")
    )
    # 只查最新一天时，每只股票只需保留最后若干天，能大幅提速。
    if start_date == end_date:
        bars = bars.groupby("symbol", sort=False).tail(config.max_required_days)

    return bars.reset_index(drop=True), start_date


def mark_candidate_days(
    bars: pd.DataFrame, config: SignalConfig, start_date: pd.Timestamp
) -> pd.Series:
    """批量粗筛：哪些 (股票, 日期) 的 K 线长得像"放量大阳线"。

    这一步用向量化计算，一次处理全部数据，比逐只股票判断快得多；
    粗筛没通过的，后面不用再费力检查。
    """

    body = bars["close"] - bars["open"]
    candle_range = bars["high"] - bars["low"]
    previous_close = bars.groupby("symbol", sort=False)["close"].shift()
    close_position = (bars["close"] - bars["low"]) / candle_range
    recent_days = min(3, config.min_pullback_days)
    previous_high = bars.groupby("symbol", sort=False)["high"].shift()
    recent_high = (
        previous_high.groupby(bars["symbol"], sort=False)
        .rolling(recent_days).max().droplevel(0)
    )

    return (
        (bars["date"] >= start_date)
        & (candle_range > 0)
        & (bars["close"] > recent_high)
        & (body / bars["open"] >= config.min_confirm_body)
        & (bars["close"] / previous_close - 1 >= config.min_confirm_return)
        & (body / candle_range >= config.min_confirm_body_ratio)
        & (close_position >= config.min_confirm_close_position)
    )


def detect_strong_breakout_pullback(
    df: pd.DataFrame,
    config: SignalConfig = DEFAULT_CONFIG,
    *,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """扫描全部股票，返回每个确认日出现的信号。

    - 不传日期：只查最新交易日。
    - 传了 start_date / end_date：查这个区间内每一天（可用于回测）。
      开始日期只限制"确认日"，上涨和回调可以用区间之前的行情。
    """

    if df.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    bars, start_date = clean_daily_bars(df, config, start_date, end_date)
    is_candidate = mark_candidate_days(bars, config, start_date)

    signals = []
    candidate_symbols = bars.loc[is_candidate, "symbol"].unique()
    candidate_bars = bars[bars["symbol"].isin(candidate_symbols)]

    # 对粗筛通过的股票，逐个候选日截取窗口做精确判断。
    for _, symbol_bars in candidate_bars.groupby("symbol", sort=False):
        flags = is_candidate.loc[symbol_bars.index]
        for position in np.flatnonzero(flags.to_numpy()):
            # 窗口以候选日为终点，向前最多取 max_required_days 天。
            window_start = max(0, position + 1 - config.max_required_days)
            window = symbol_bars.iloc[window_start : position + 1]
            signal = find_latest_signal(window, config)
            if signal:
                signals.append(signal)

    return pd.DataFrame(signals, columns=SIGNAL_COLUMNS)


# ============================================================
# 5. 结果整理：拼上股票名称、市值、热度
# ============================================================


def attach_stock_info(
    signals: pd.DataFrame,
    latest_stocks: pd.DataFrame,
    latest_hot: pd.DataFrame,
    latest_basic: pd.DataFrame,
) -> pd.DataFrame:
    """把信号结果和股票基本信息、热度排名合并，并按热度排序。"""

    if signals.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    # 给信号列改成更直观的名字，并标记信号阶段。
    signals = signals.rename(
        columns={
            "date": "latest_date",
            "close": "latest_close",
            "return_1d": "latest_1d_pct",
        }
    )
    signals["signal_stage"] = "放量大阳线"

    # 股票列表 + 基本面（市值等）。
    stock_info = latest_stocks.drop(
        columns=["trade_date", "update_time"], errors="ignore"
    ).merge(latest_basic, on="symbol", how="left")

    # 热度表：每只股票只留一行，把 rank 改名为 hot_rank。
    hot_rank = latest_hot.drop_duplicates("symbol").rename(
        columns={"rank": "hot_rank"}
    )[["symbol", "hot_rank"]]

    merged = stock_info.merge(signals, on="symbol").merge(
        hot_rank, on="symbol", how="left"
    )
    # 热度排名靠前的优先；没有热度排名的放最后；同名次按今日涨幅从高到低。
    merged = merged.sort_values(
        ["hot_rank", "latest_1d_pct"],
        ascending=[True, False],
        na_position="last",
    )
    return merged[RESULT_COLUMNS].reset_index(drop=True)


class StrongBreakoutPullbackPattern:
    """N 字形态的区间入口；窗口长度由上涨段、回调段参数决定。"""

    def __init__(self, config: SignalConfig = DEFAULT_CONFIG):
        self.config = config

    def scan_range(
        self,
        trade_dates: Iterable[DateLike],
        historical_stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        historical_hot: pd.DataFrame,
        historical_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        trade_dates = normalize_trade_dates(trade_dates)
        if trade_dates.empty or daily_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)
        bars = trim_history_bars(
            daily_bars, trade_dates, lookback_rows=self.config.max_required_days,
        )
        signals = detect_strong_breakout_pullback(
            bars.rename(columns={"trade_date": "date"}), config=self.config,
            start_date=trade_dates.min(), end_date=trade_dates.max(),
        )
        signals = signals[signals["date"].isin(trade_dates)]
        return select_by_snapshot(
            signals, historical_stocks, historical_hot, historical_basic,
            self.select_indicators, date_column="date",
        )

    @staticmethod
    def select_indicators(signals, stocks, basic, hot):
        return attach_stock_info(signals, stocks, hot, basic)


def run_signal(
    *,
    latest_stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    latest_hot: pd.DataFrame,
    latest_basic: pd.DataFrame,
    config: SignalConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """对外入口：计算最新交易日的信号，返回完整结果表。"""

    if daily_bars.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    # 数据库里日期列叫 trade_date，这里统一改成 date。
    signals = detect_strong_breakout_pullback(
        daily_bars.rename(columns={"trade_date": "date"}),
        config=config,
    )
    return attach_stock_info(signals, latest_stocks, latest_hot, latest_basic)


# ============================================================
# 6. 展示
# ============================================================


def format_for_display(result: pd.DataFrame) -> pd.DataFrame:
    """把结果转成适合人看的样子：换单位、四舍五入、改中文列名。"""

    display = result.copy()
    display["market_cap"] = display["market_cap"] / 1e8  # 元 → 亿元

    # 这些列原本是小数（0.05），展示成百分数（5.0）。
    for column in [
        "latest_1d_pct",
        "breakout_return",
        "pullback_depth",
    ]:
        display[column] = display[column] * 100

    number_columns = [
        "market_cap",
        "latest_close",
        "latest_1d_pct",
        "volume_ratio",
        "breakout_return",
        "pullback_depth",
        "pullback_volume_ratio",
    ]
    display[number_columns] = display[number_columns].round(2)

    return display[list(DISPLAY_NAMES)].rename(columns=DISPLAY_NAMES)


def main() -> None:
    with console.status("[bold green]正在读取本地数据并识别突破回调信号..."):
        latest_stocks, daily_bars, latest_hot, latest_basic = load_market_data()
        latest_date = pd.to_datetime(daily_bars["trade_date"]).max()
        latest_trade_date = (
            latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "无数据"
        )
        selected = run_signal(
            latest_stocks=latest_stocks,
            daily_bars=daily_bars,
            latest_hot=latest_hot,
            latest_basic=latest_basic,
        )

    console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
    console.print("[green]✓ 信号识别完成[/green]")

    if selected.empty:
        console.print("[yellow]当前交易日没有上涨缩量回调信号。[/yellow]")
        return

    console.print(format_for_display(selected))
    console.print(f"[green]共筛选出 {len(selected)} 只股票。[/green]")


if __name__ == "__main__":
    main()

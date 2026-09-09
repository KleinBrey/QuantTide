"""
Tushare 最小连通性测试。
"""

from backend.app.provider.tushare_provider import TushareProvider


def main() -> None:
    provider = TushareProvider()

    # data = provider.pro.stock_basic(
    #     fields="ts_code,symbol,name,area,industry,market",
    # )

    data = provider.pro.daily_basic(
        ts_code="",
        trade_date="",
        fields="ts_code,trade_date,turnover_rate,volume_ratio,pe,pb",
    )

    # 提取单个股票，跨时间段的历史日线
    # data = provider.pro.daily(
    #     ts_code="000001.SZ", start_date="20180701", end_date="20200718"
    # )

    # 获取查询月份券商金股
    # data = provider.pro.ths_hot(
    #     trade_date="20260818",
    #     market="热股",
    #     is_new="N",
    #     fields="ts_code,ts_name,hot,concept",
    # )
    print(data)


if __name__ == "__main__":
    main()

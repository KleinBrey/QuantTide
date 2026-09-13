"""港股市场数据服务。"""

from ..provider import IwencaiProvider
from ..repository import HKStockHotDailyRepository
from .hot_stock_service import HotStockService


class HKMarketService(HotStockService):
    """负责港股热度数据同步与缓存。"""

    def __init__(
        self,
        iwencai_provider: IwencaiProvider | None = None,
        stock_hot_repository: HKStockHotDailyRepository | None = None,
    ) -> None:
        super().__init__(
            iwencai_provider=iwencai_provider,
            stock_hot_repository=stock_hot_repository,
            fetch_method_name="fetch_hk_hot_rank",
            market_name="港股",
        )

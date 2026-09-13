"""美股市场数据服务。"""

from ..provider import IwencaiProvider
from ..repository import USStockHotDailyRepository
from .hot_stock_service import HotStockService


class USMarketService(HotStockService):
    """负责美股热度数据同步与缓存。"""

    def __init__(
        self,
        iwencai_provider: IwencaiProvider | None = None,
        stock_hot_repository: USStockHotDailyRepository | None = None,
    ) -> None:
        super().__init__(
            iwencai_provider=iwencai_provider,
            stock_hot_repository=stock_hot_repository,
            fetch_method_name="fetch_us_hot_rank",
            market_name="美股",
        )

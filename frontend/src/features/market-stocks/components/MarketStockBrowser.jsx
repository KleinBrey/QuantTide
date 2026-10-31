import { useState } from 'react';

import StockKlineChart from '@/components/tradingView/StockKlineChart.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import { useMarketStockKline } from '../hooks/useMarketStockKline.js';
import { useMarketStocks } from '../hooks/useMarketStocks.js';
import MarketStockList from './MarketStockList.jsx';
import MarketStockGroups from '@/components/watchlist/WatchlistGroups.jsx';
import styles from '@/components/watchlist/MarketBrowser.module.css';

const MARKET_CONFIG = {
  futures: { title: '期货主力合约行情' },
  'a-share': {
    title: 'A股行情'
  },
  'hk-share': {
    title: '港股行情'
  },
  'us-share': {
    title: '美股行情'
  }
};

export default function MarketStockBrowser({ marketId }) {
  const market = MARKET_CONFIG[marketId] || MARKET_CONFIG['hk-share'];
  const stockList = useMarketStocks(marketId);

  return (
    <div className={cn('dashboard-content', styles.content)}>
      <section aria-label={market.title} className={cn('dashboard-panel', styles.panel)}>
        <MarketStockGroups
          marketId={marketId}
          {...stockList}
          hasStockPool={marketId !== 'futures' && stockList.hasStockPool}
        />
        <MarketStockContent key={marketId} marketId={marketId} market={market} stockList={stockList} />
      </section>
    </div>
  );
}

function MarketStockContent({ marketId, market, stockList }) {
  const { selectedStock } = stockList;
  const kline = useMarketStockKline(marketId, selectedStock?.symbol);
  const [period, setPeriod] = useState('daily');

  return (
    <div className={styles.browser}>
      <aside aria-label={`${market.title}股票列表`} className={styles.stockPane}>
        <MarketStockList marketId={marketId} {...stockList} />
      </aside>

      <div className={styles.chartPane}>
        <StockKlineChart
          emptyTitle={marketId === 'futures' ? '主力合约 K 线' : undefined}
          data={kline.data}
          fillContainer
          enableMouseWheelZoom
          error={kline.error}
          loading={kline.loading}
          onPeriodChange={setPeriod}
          period={period}
          stock={selectedStock}
        />
      </div>
    </div>
  );
}

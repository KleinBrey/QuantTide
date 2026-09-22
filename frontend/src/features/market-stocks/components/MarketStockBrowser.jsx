import { useState } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';

import StockKlineChart from '@/components/TradingView/StockKlineChart.jsx';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import { useMarketStockKline } from '../hooks/useMarketStockKline.js';
import { useMarketStocks } from '../hooks/useMarketStocks.js';
import styles from './MarketStockBrowser.module.css';

const MARKET_CONFIG = {
  'hk-share': {
    title: '港股行情',
    description: '港股数据库股票池'
  },
  'us-share': {
    title: '美股行情',
    description: '美股数据库股票池'
  }
};

export default function MarketStockBrowser({ marketId }) {
  const market = MARKET_CONFIG[marketId] || MARKET_CONFIG['hk-share'];
  const { stocks, selectedStock, setSelectedStock, loading, error, refresh } = useMarketStocks(marketId);
  const kline = useMarketStockKline(marketId, selectedStock?.symbol);
  const [period, setPeriod] = useState('daily');

  return (
    <div className="dashboard-content">
      <section className={cn('dashboard-panel', styles.panel)}>
        <div className="dashboard-panel-header">
          <div>
            <h2>{market.title}</h2>
            <span>{error || `${market.description} · ${stocks.length} 只`}</span>
          </div>
          <Button
            aria-label={`刷新${market.title}股票列表`}
            className="dashboard-ghost-button"
            disabled={loading}
            onClick={refresh}
            type="button"
            variant="outline"
          >
            {loading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
            <span>{loading ? '加载中' : '刷新列表'}</span>
          </Button>
        </div>

        <div className={styles.browser}>
          <aside aria-label={`${market.title}股票列表`} className={styles.stockPane}>
            <div className={styles.listHeader}>
              <span>股票列表</span>
              <strong>{stocks.length}</strong>
            </div>

            {loading && !stocks.length ? (
              <div className={styles.listState}>
                <Loader2 className="dashboard-spin" size={20} />
                <span>正在读取 stocks 表</span>
              </div>
            ) : error ? (
              <div className={cn(styles.listState, styles.error)}>{error}</div>
            ) : stocks.length ? (
              <div aria-label="股票" className={styles.stockList} role="listbox">
                {stocks.map(stock => {
                  const selected = stock.symbol === selectedStock?.symbol;
                  return (
                    <button
                      aria-selected={selected}
                      className={cn(styles.stockItem, selected && styles.selected)}
                      key={stock.symbol}
                      onClick={() => setSelectedStock(stock)}
                      role="option"
                      type="button"
                    >
                      <span>{stock.name}</span>
                      <small>{stock.symbol}</small>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className={styles.listState}>数据库 stocks 表暂无股票</div>
            )}
          </aside>

          <div className={styles.chartPane}>
            <StockKlineChart
              data={kline.data}
              enableMouseWheelZoom
              error={kline.error}
              loading={kline.loading}
              onPeriodChange={setPeriod}
              period={period}
              stock={selectedStock}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

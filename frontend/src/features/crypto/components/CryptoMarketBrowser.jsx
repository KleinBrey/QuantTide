import { useState } from 'react';
import WatchlistGroups from '@/components/watchlist/WatchlistGroups.jsx';
import StockKlineChart from '@/components/TradingView/StockKlineChart.jsx';
import { useCryptoMarket } from '../hooks/useCryptoMarket.js';
import { useCryptoKline } from '../hooks/useCryptoKline.js';
import CryptoMarketList from './CryptoMarketList.jsx';
import styles from './CryptoMarketBrowser.module.css';

export default function CryptoMarketBrowser() {
  const market = useCryptoMarket();
  const kline = useCryptoKline(market.selected, market.revision);
  const [period, setPeriod] = useState('daily');

  return (
    <div className={`dashboard-content ${styles.content}`}>
      <section aria-label="加密货币行情" className={`dashboard-panel ${styles.panel}`}>
        <WatchlistGroups {...market} marketId="crypto" poolLabel="交易对池" groupPlaceholder="例如 主流币"
          mutating={market.syncing} actionError={market.error} />
        <div className={styles.browser}>
          <aside aria-label="加密货币交易对列表" className={styles.listPane}>
            <CryptoMarketList {...market} />
          </aside>
          <div className={styles.chartPane}>
            {market.selected ? (
              <StockKlineChart {...kline} fillContainer enableMouseWheelZoom
                stock={{ name: '现货', symbol: market.selected }}
                period={period} onPeriodChange={setPeriod} />
            ) : <div className={styles.emptyChart}>添加交易对后，在这里查看 K 线与成交量。</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

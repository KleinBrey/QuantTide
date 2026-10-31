import { cn } from '@/shadcn/lib/utils.js';
import { useHotStockRanking } from '../hooks/useHotStockRanking.js';
import MarketRankingPanel from './MarketRankingPanel.jsx';
import styles from './HotRankings.module.css';

export default function HotRankingsView() {
  const cnStockRanking = useHotStockRanking('cn_stock');
  const hkStockRanking = useHotStockRanking('hk_stock');
  const usStockRanking = useHotStockRanking('us_stock');

  const markets = [
    { id: 'cn_stock', title: 'A股热榜', state: cnStockRanking },
    { id: 'hk_stock', title: '港股热榜', state: hkStockRanking },
    { id: 'us_stock', title: '美股热榜', state: usStockRanking }
  ];

  return (
    <div className={cn('dashboard-content', styles.dashboardGrid)}>
      {markets.map(market => (
        <MarketRankingPanel key={market.id} market={market} />
      ))}
    </div>
  );
}

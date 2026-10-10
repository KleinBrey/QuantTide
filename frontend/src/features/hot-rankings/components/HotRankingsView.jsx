import { cn } from '@/shadcn/lib/utils.js';
import { useHotStockRanking } from '../hooks/useHotStockRanking.js';
import MarketRankingPanel from './MarketRankingPanel.jsx';
import styles from './HotRankings.module.css';

export default function HotRankingsView() {
  const aShareRanking = useHotStockRanking('a-share');
  const hkShareRanking = useHotStockRanking('hk-share');
  const usShareRanking = useHotStockRanking('us-share');

  const markets = [
    { id: 'a-share', title: 'A股热榜', state: aShareRanking },
    { id: 'hk-share', title: '港股热榜', state: hkShareRanking },
    { id: 'us-share', title: '美股热榜', state: usShareRanking }
  ];

  return (
    <div className={cn('dashboard-content', styles.dashboardGrid)}>
      {markets.map(market => (
        <MarketRankingPanel key={market.id} market={market} />
      ))}
    </div>
  );
}

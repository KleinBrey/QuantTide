import { useEffect, useRef, useState } from 'react';

import RankingTable from '@/features/hot-rankings/components/RankingTable.jsx';
import styles from '@/features/hot-rankings/HotRankingsDashboard.module.css';
import { useHotStockRanking } from '@/features/hot-rankings/hooks/useHotStockRanking.js';
import { Loader2, Maximize2, Minimize2, RefreshCcw } from 'lucide-react';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import moment from 'moment';

export default function HotRankingsDashboard() {
  const panelRefs = useRef({});
  const [fullscreenMarket, setFullscreenMarket] = useState(null);
  const aShareRanking = useHotStockRanking('a-share');
  const hkShareRanking = useHotStockRanking('hk-share');
  const usShareRanking = useHotStockRanking('us-share');

  const markets = [
    { id: 'a-share', title: 'A股热榜', state: aShareRanking },
    { id: 'hk-share', title: '港股热榜', state: hkShareRanking },
    { id: 'us-share', title: '美股热榜', state: usShareRanking }
  ];

  useEffect(() => {
    const handleFullscreenChange = () => {
      const activeMarket = Object.entries(panelRefs.current).find(([, panel]) => panel === document.fullscreenElement);
      setFullscreenMarket(activeMarket?.[0] || null);
    };

    const handleEscape = event => {
      if (event.key === 'Escape' && !document.fullscreenElement) setFullscreenMarket(null);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('keydown', handleEscape);
    };
  }, []);

  async function toggleFullscreen(marketId) {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        const panel = panelRefs.current[marketId];
        if (typeof panel?.requestFullscreen === 'function') {
          await panel.requestFullscreen();
        } else {
          setFullscreenMarket(currentMarket => (currentMarket === marketId ? null : marketId));
        }
      }
    } catch (fullscreenError) {
      console.error('切换热榜全屏失败', fullscreenError);
    }
  }

  function formatTimestamp(timestamp) {
    if (!timestamp) return '未刷新';

    const value = moment(timestamp);

    const time = value.format('YYYY-MM-DD HH:mm:ss');
    return value.isValid() ? time : '未刷新';
  }

  return (
    <div className={cn('dashboard-content', styles.dashboardGrid)}>
      {markets.map(market => {
        const isFullscreen = fullscreenMarket === market.id;
        const { ranking, loading: rankingLoading, error: rankingError, refresh } = market.state;

        return (
          <section
            className={cn(
              'dashboard-panel',
              'dashboard-table-panel',
              styles.panel,
              isFullscreen && !document.fullscreenElement && styles.fallbackFullscreen
            )}
            data-market-id={market.id}
            key={market.id}
            ref={node => {
              panelRefs.current[market.id] = node;
            }}
          >
            <div className={cn('dashboard-panel-header', styles.panelHeader)}>
              <div>
                <h2>{market.title}</h2>
                <span>{rankingError || formatTimestamp(ranking.timestamp)}</span>
              </div>
              <div className={styles.headerActions}>
                <Button
                  aria-label={isFullscreen ? `退出${market.title}全屏` : `全屏显示${market.title}`}
                  aria-pressed={isFullscreen}
                  className={cn('dashboard-ghost-button', styles.fullscreenButton)}
                  onClick={() => toggleFullscreen(market.id)}
                  size="icon-lg"
                  title={isFullscreen ? '退出全屏' : '全屏显示'}
                  type="button"
                  variant="outline"
                >
                  {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                </Button>
                <Button
                  aria-label={`刷新${market.title}数据`}
                  type="button"
                  className="dashboard-ghost-button"
                  variant="outline"
                  onClick={refresh}
                  disabled={rankingLoading}
                >
                  {rankingLoading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
                  <span>{rankingLoading ? '更新中' : '刷新数据'}</span>
                </Button>
              </div>
            </div>
            <div className={styles.tableWrap}>
              <RankingTable
                rows={ranking.rows}
                loading={rankingLoading}
                marketId={market.id}
                showKline={isFullscreen}
              />
            </div>
          </section>
        );
      })}
    </div>
  );
}

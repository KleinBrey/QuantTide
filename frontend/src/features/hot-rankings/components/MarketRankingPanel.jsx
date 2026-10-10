import { useRef } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';
import moment from 'moment';

import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import { useWindowFullscreen, FULLSCREEN_MODE } from '@/hooks/useFullscreen.js';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import RankingTable from './RankingTable.jsx';
import styles from './HotRankings.module.css';

function formatTimestamp(timestamp) {
  if (!timestamp) return '未刷新';

  const value = moment(timestamp);

  const time = value.format('YYYY-MM-DD HH:mm:ss');
  return value.isValid() ? time : '未刷新';
}

export default function MarketRankingPanel({ market }) {
  const panelRef = useRef(null);
  const { isFullscreen, targetClassName, toggleFullscreen } = useWindowFullscreen();

  const { ranking, loading: rankingLoading, error: rankingError, refresh } = market.state;

  return (
    <section
      className={cn('dashboard-panel', 'dashboard-table-panel', styles.panel, targetClassName)}
      data-market-id={market.id}
      ref={panelRef}
    >
      <div className={cn('dashboard-panel-header', styles.panelHeader)}>
        <div>
          <h2>{market.title}</h2>
          <span>{rankingError || formatTimestamp(ranking.timestamp)}</span>
        </div>
        <div className={styles.headerActions}>
          <FullscreenButton isFullscreen={isFullscreen} mode={FULLSCREEN_MODE.WINDOW} onToggle={toggleFullscreen} />
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
        <RankingTable rows={ranking.rows} loading={rankingLoading} marketId={market.id} showKline={isFullscreen} />
      </div>
    </section>
  );
}

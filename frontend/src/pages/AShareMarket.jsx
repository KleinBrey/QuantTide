import { useRef } from 'react';

import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import AShareMarketTable from '@/features/a-share-market/components/AShareMarketTable.jsx';
import styles from '@/features/a-share-market/AShareMarket.module.css';
import { useAShareMarketRanking } from '@/features/a-share-market/hooks/useAShareMarketRanking.js';
import { useBrowserFullscreen } from '@/hooks/useFullscreen.js';
import { Loader2, RefreshCcw } from 'lucide-react';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import moment from 'moment';

export default function AShareMarket() {
  const panelRef = useRef(null);
  const { isFullscreen, targetClassName, toggleFullscreen } = useBrowserFullscreen(panelRef);
  const { ranking, loading: rankingLoading, error: rankingError, refresh } = useAShareMarketRanking();

  function formatTimestamp(timestamp) {
    if (!timestamp) return '未刷新';

    const value = moment(timestamp);

    const time = value.format('YYYY-MM-DD HH:mm:ss');
    return value.isValid() ? time : '未刷新';
  }

  return (
    <div className="dashboard-content">
      <section className={cn('dashboard-panel', 'dashboard-table-panel', styles.panel, targetClassName)} ref={panelRef}>
        <div className="dashboard-panel-header">
          <div>
            <h2>{ranking.title}</h2>
            <span>{rankingError || formatTimestamp(ranking.timestamp)}</span>
          </div>
          <div className={styles.headerActions}>
            <FullscreenButton isFullscreen={isFullscreen} onToggle={toggleFullscreen} />
            <Button
              type="button"
              className="dashboard-ghost-button"
              variant="outline"
              onClick={refresh}
              disabled={rankingLoading}
            >
              {rankingLoading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
              <span>{rankingLoading ? '更新中' : '刷新当前'}</span>
            </Button>
          </div>
        </div>
        <div className={cn(styles.tableWrap, isFullscreen && styles.fullscreenTableWrap)}>
          <AShareMarketTable rows={ranking.rows} loading={rankingLoading} />
        </div>
      </section>
    </div>
  );
}

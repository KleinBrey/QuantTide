import { BookOpenText, ChevronRight, Loader2, RefreshCcw } from 'lucide-react';
import moment from 'moment';
import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import { FULLSCREEN_MODE, useWindowFullscreen } from '@/hooks/useFullscreen.js';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import StrategyResultsTable from './StrategyResultsTable.jsx';
import styles from './StrategySignals.module.css';

function formatTimestamp(value) {
  if (!value) return '尚未运行';
  const timestamp = moment(value);
  return timestamp.isValid() ? timestamp.format('YYYY-MM-DD HH:mm:ss') : '尚未运行';
}

export default function StrategySignalsView({ state }) {
  const { isFullscreen, targetClassName, toggleFullscreen } = useWindowFullscreen();
  const { strategies, activeStrategyId, result, columnDefs, loading, error, selectStrategy, refresh } = state;
  const activeStrategy = result?.strategy || strategies.find(strategy => strategy.id === activeStrategyId);
  const rows = result?.items || [];

  return (
    <div className={cn('dashboard-content', styles.root)}>
      <aside className={cn('dashboard-panel', styles.strategySidebar)} aria-label="策略列表">
        <div className={styles.sidebarHeader}>
          <span>策略列表</span>
          <small>{strategies.length}</small>
        </div>
        <nav className={styles.strategyList}>
          {strategies.map(strategy => {
            const active = strategy.id === activeStrategyId;
            return (
              <button
                key={strategy.id}
                type="button"
                className={cn(styles.strategyItem, active && styles.strategyItemActive)}
                onClick={() => selectStrategy(strategy.id)}
                aria-current={active ? 'page' : undefined}
              >
                <span className={styles.strategyIcon}>
                  <BookOpenText size={17} />
                </span>
                <span className={styles.strategyText}>
                  <strong>{strategy.name}</strong>
                </span>
                <ChevronRight size={16} />
              </button>
            );
          })}
          {!strategies.length && !loading ? <p className={styles.noStrategy}>暂无可用策略</p> : null}
        </nav>
      </aside>

      <section className={cn('dashboard-panel', 'dashboard-table-panel', styles.resultPanel, targetClassName)}>
        <div className={cn('dashboard-panel-header', styles.resultHeader)}>
          <div className={styles.headerContent}>
            <div className={styles.strategyHeading}>
              <h2>{activeStrategy?.name || '策略结果'}</h2>
              {activeStrategy?.description ? <span>{activeStrategy.description}</span> : null}
            </div>
            <div className={styles.headerMeta}>
              <span>
                最近运行 <strong>{formatTimestamp(result?.generated_at)}</strong>
              </span>
              <span>
                命中股票 <strong>{loading && !result ? '-' : (result?.count ?? 0)}</strong>
              </span>
              <span>
                交易日期 <strong>{result?.trade_date || '-'}</strong>
              </span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <FullscreenButton isFullscreen={isFullscreen} mode={FULLSCREEN_MODE.WINDOW} onToggle={toggleFullscreen} />
            <Button
              type="button"
              className="dashboard-ghost-button"
              onClick={refresh}
              disabled={loading || !activeStrategyId}
              variant="outline"
            >
              {loading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
              <span>{loading ? '运行中' : '重新运行'}</span>
            </Button>
          </div>
        </div>

        {error ? <div className={styles.errorNotice}>{error}</div> : null}
        <div className={cn(styles.tableWrap, isFullscreen && styles.fullscreenTableWrap)}>
          <StrategyResultsTable rows={rows} columnDefs={columnDefs} loading={loading} />
        </div>
      </section>
    </div>
  );
}

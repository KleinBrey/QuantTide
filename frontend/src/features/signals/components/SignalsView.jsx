import { BookOpenText, ChevronRight, Loader2, RefreshCcw } from 'lucide-react';
import moment from 'moment';
import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import { FULLSCREEN_MODE, useWindowFullscreen } from '@/hooks/useFullscreen.js';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import SignalResultsTable from './SignalResultsTable.jsx';
import styles from './Signals.module.css';

function formatTimestamp(value) {
  if (!value) return '尚未运行';
  const timestamp = moment(value);
  return timestamp.isValid() ? timestamp.format('YYYY-MM-DD HH:mm:ss') : '尚未运行';
}

export default function SignalsView({ state }) {
  const { isFullscreen, targetClassName, toggleFullscreen } = useWindowFullscreen();
  const { signals, activeSignalId, result, columnDefs, loading, error, selectSignal, refresh } = state;
  const activeSignal = result?.signal || signals.find(signal => signal.id === activeSignalId);
  const rows = result?.items || [];

  return (
    <div className={cn('dashboard-content', styles.root)}>
      <aside className={cn('dashboard-panel', styles.signalSidebar)} aria-label="信号列表">
        <div className={styles.sidebarHeader}>
          <span>信号列表</span>
          <small>{signals.length}</small>
        </div>
        <nav className={styles.signalList}>
          {signals.map(signal => {
            const active = signal.id === activeSignalId;
            return (
              <button
                key={signal.id}
                type="button"
                className={cn(styles.signalItem, active && styles.signalItemActive)}
                onClick={() => selectSignal(signal.id)}
                aria-current={active ? 'page' : undefined}
              >
                <span className={styles.signalIcon}>
                  <BookOpenText size={17} />
                </span>
                <span className={styles.signalText}>
                  <strong>{signal.name}</strong>
                </span>
                <ChevronRight size={16} />
              </button>
            );
          })}
          {!signals.length && !loading ? <p className={styles.noSignal}>暂无可用信号</p> : null}
        </nav>
      </aside>

      <section className={cn('dashboard-panel', 'dashboard-table-panel', styles.resultPanel, targetClassName)}>
        <div className={cn('dashboard-panel-header', styles.resultHeader)}>
          <div className={styles.headerContent}>
            <div className={styles.signalHeading}>
              <h2>{activeSignal?.name || '信号结果'}</h2>
              {activeSignal?.description ? <span>{activeSignal.description}</span> : null}
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
              disabled={loading || !activeSignalId}
              variant="outline"
            >
              {loading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
              <span>{loading ? '运行中' : '重新运行'}</span>
            </Button>
          </div>
        </div>

        {error ? <div className={styles.errorNotice}>{error}</div> : null}
        <div className={cn(styles.tableWrap, isFullscreen && styles.fullscreenTableWrap)}>
          <SignalResultsTable rows={rows} columnDefs={columnDefs} loading={loading} />
        </div>
      </section>
    </div>
  );
}

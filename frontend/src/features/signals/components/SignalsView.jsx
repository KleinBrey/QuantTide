import { BookOpenText, ChevronRight, Loader2, RefreshCcw } from 'lucide-react';
import moment from 'moment';
import { Tabs } from 'radix-ui';
import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import { useWindowFullscreen } from '@/hooks/useFullscreen.js';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import { useSignals } from '../hooks/useSignals.js';
import SignalResultsTable from './SignalResultsTable.jsx';
import styles from './Signals.module.css';

function formatTimestamp(value) {
  if (!value) return '尚未运行';
  const timestamp = moment(value);
  return timestamp.isValid() ? timestamp.format('YYYY-MM-DD HH:mm:ss') : '尚未运行';
}

export default function SignalsView() {
  const { isFullscreen, targetClassName, toggleFullscreen } = useWindowFullscreen();
  const {
    signals,
    activeSignalId,
    result,
    columnDefs,
    loading,
    error,
    selectSignal,
    refresh,
    range,
    setRange,
    validRange,
    scanMode,
    selectMode
  } = useSignals();
  const isHistory = scanMode === 'history';
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
                disabled={!validRange}
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

      <Tabs.Root value={scanMode} onValueChange={selectMode} activationMode="manual" asChild>
        <section className={cn('dashboard-panel', 'dashboard-table-panel', styles.resultPanel, targetClassName)}>
          <div className={cn('dashboard-panel-header', styles.resultHeader)}>
            <Tabs.List className={styles.scanTabs} aria-label="扫描方式">
              <Tabs.Trigger className={styles.scanTab} value="today" disabled={!activeSignalId}>
                当日扫描
              </Tabs.Trigger>
              <Tabs.Trigger className={styles.scanTab} value="history" disabled={!activeSignalId}>
                历史扫描
              </Tabs.Trigger>
            </Tabs.List>
            <div className={styles.headerContent}>
              <div className={styles.signalHeading}>
                <h2>{activeSignal?.name || '信号结果'}</h2>
                {activeSignal?.description ? <span>{activeSignal.description}</span> : null}
              </div>
              <dl className={styles.resultStats} aria-label="扫描结果统计" aria-busy={loading}>
                <div className={styles.statItem}>
                  <dt>命中股票</dt>
                  <dd>
                    <strong>{result ? (result.stock_count ?? 0) : '0'}</strong>
                    <span>只</span>
                  </dd>
                </div>
                <div className={styles.statItem}>
                  <dt>命中次数</dt>
                  <dd>
                    <strong>{result ? (result.count ?? 0) : '0'}</strong>
                    <span>次</span>
                  </dd>
                </div>
              </dl>
            </div>
            <form
              className={styles.headerActions}
              onSubmit={event => {
                event.preventDefault();
                refresh();
              }}
            >
              {isHistory ? (
                <div className={styles.dateRange}>
                  <label>
                    开始日期
                    <input
                      type="date"
                      required
                      value={range.startDate}
                      max={range.endDate || undefined}
                      onInput={event => setRange({ ...range, startDate: event.currentTarget.value })}
                    />
                  </label>
                  <label>
                    结束日期
                    <input
                      type="date"
                      required
                      value={range.endDate}
                      min={range.startDate || undefined}
                      onInput={event => setRange({ ...range, endDate: event.currentTarget.value })}
                    />
                  </label>
                </div>
              ) : (
                <span className={styles.todayHint}>按本地最新交易日扫描</span>
              )}
              <div className={styles.actionButtons}>
                <FullscreenButton isFullscreen={isFullscreen} onToggle={toggleFullscreen} />
                <Button
                  type="submit"
                  className="dashboard-ghost-button"
                  disabled={loading || !activeSignalId || !validRange}
                  variant="outline"
                >
                  {loading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
                  <span>{loading ? '扫描中' : '扫描信号'}</span>
                </Button>
              </div>
            </form>
            {/* <div className={styles.headerMeta}>
              <span>最近运行 <time dateTime={result?.generated_at}>{formatTimestamp(result?.generated_at)}</time></span>
              {result ? <span>
                {isHistory ? '已扫描范围' : '扫描交易日'}{' '}
                {isHistory ? `${result.start_date} 至 ${result.end_date}` : result.end_date}
              </span> : null}
            </div> */}
          </div>

          <Tabs.Content value={scanMode} className={styles.scanBody}>
            {error ? <div className={styles.errorNotice}>{error}</div> : null}
            <div className={cn(styles.tableWrap, isFullscreen && styles.fullscreenTableWrap)}>
              <SignalResultsTable
                rows={rows}
                columnDefs={columnDefs}
                loading={loading}
                emptyMessage={isHistory ? '所选日期范围内暂无命中股票' : '最新交易日暂无命中股票'}
              />
            </div>
          </Tabs.Content>
        </section>
      </Tabs.Root>
    </div>
  );
}

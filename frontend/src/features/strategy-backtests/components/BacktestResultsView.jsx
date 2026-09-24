import { Loader2, RefreshCcw } from 'lucide-react';
import moment from 'moment';
import FullscreenButton from '@/components/fullscreen/FullscreenButton.jsx';
import { FULLSCREEN_MODE, useWindowFullscreen } from '@/hooks/useFullscreen.js';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { cn } from '@/shadcn/lib/utils.js';
import { formatNumber, formatPercent } from '../utils/backtestFormatters.jsx';
import BacktestEquityChart from './BacktestEquityChart.jsx';
import BacktestTradesTable from './BacktestTradesTable.jsx';
import styles from './BacktestResultsView.module.css';

function formatTimestamp(value) {
  const timestamp = moment(value);
  return value && timestamp.isValid() ? timestamp.format('YYYY-MM-DD HH:mm:ss') : '尚未运行';
}

function Metric({ label, value, tone }) {
  return (
    <div className={styles.metric}>
      <span>{label}</span>
      <strong className={tone ? styles[tone] : undefined}>{value}</strong>
    </div>
  );
}

export default function BacktestResultsView({ state }) {
  const { isFullscreen, targetClassName, toggleFullscreen } = useWindowFullscreen();
  const { result, loading, error, refresh } = state;
  const summary = result?.summary;
  const strategy = result?.strategy;
  const trades = result?.trades || [];
  const returnTone = summary?.total_return > 0 ? 'positive' : summary?.total_return < 0 ? 'negative' : '';

  return (
    <div className={cn('dashboard-content', styles.root)}>
      <div className={styles.overviewColumn}>
        <section className={cn('dashboard-panel', styles.summaryPanel)}>
          <div className={styles.summaryHeader}>
            <div>
              <div className={styles.heading}>
                <h2>{strategy?.name ? `${strategy.name}回测` : '策略回测'}</h2>
                {strategy?.description ? <span>{strategy.description}</span> : null}
              </div>
              <div className={styles.meta}>
                <span>
                  最近运行 <strong>{formatTimestamp(result?.generated_at)}</strong>
                </span>
                <span>
                  回测区间 <strong>{summary ? `${summary.start_date} ~ ${summary.end_date}` : '-'}</strong>
                </span>
                <span>
                  交易记录 <strong>{summary?.trade_count ?? '-'}</strong>
                </span>
              </div>
            </div>
            <Button
              type="button"
              className="dashboard-ghost-button"
              onClick={refresh}
              disabled={loading}
              variant="outline"
            >
              {loading ? <Loader2 className="dashboard-spin" size={15} /> : <RefreshCcw size={15} />}
              <span>{loading ? '回测中' : '重新运行'}</span>
            </Button>
          </div>
          <div className={styles.metrics}>
            <Metric label="初始资金" value={formatNumber(summary?.initial_cash)} />
            <Metric label="期末资产" value={formatNumber(summary?.final_equity)} />
            <Metric label="累计收益" value={formatPercent(summary?.total_return)} tone={returnTone} />
            <Metric label="最大回撤" value={formatPercent(summary?.max_drawdown)} tone="negative" />
            <Metric label="夏普比率" value={formatNumber(summary?.sharpe_ratio, 3)} />
            <Metric label="胜率" value={formatPercent(summary?.win_rate)} />
          </div>
        </section>

        <BacktestEquityChart equityCurve={result?.equity_curve} initialCash={summary?.initial_cash} loading={loading} />
      </div>

      <section
        className={cn(
          'dashboard-panel',
          'dashboard-table-panel',
          styles.tradesPanel,
          isFullscreen && styles.fullscreenPanel,
          targetClassName
        )}
      >
        <div className={cn('dashboard-panel-header', styles.tableHeader)}>
          <div>
            <h2>交易记录</h2>
            <span>同一股票的交易按日期排列，末行汇总展示 K 线；B 为买点，S 为卖点</span>
          </div>
          <FullscreenButton isFullscreen={isFullscreen} mode={FULLSCREEN_MODE.WINDOW} onToggle={toggleFullscreen} />
        </div>
        {error ? <div className={styles.errorNotice}>{error}</div> : null}
        <div className={cn(styles.tableWrap, isFullscreen && styles.fullscreenTableWrap)}>
          <BacktestTradesTable trades={trades} loading={loading} />
        </div>
      </section>
    </div>
  );
}

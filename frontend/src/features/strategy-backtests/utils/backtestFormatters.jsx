import styles from '../components/BacktestTradesTable.module.css';

export function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatNumber(value, digits = 2) {
  const number = finiteNumber(value);
  return number === null ? '-' : number.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatPercent(value) {
  const number = finiteNumber(value);
  if (number === null) return '-';
  return `${number > 0 ? '+' : ''}${(number * 100).toFixed(2)}%`;
}

const reasonLabels = {
  confirm_buy: '确认买入',
  stop_loss: '止损',
  take_profit: '止盈',
  previous_close_decline: '较前收跌超5%',
  consecutive_bearish_candles: '连续三根阴线'
};

export function TradeSideCell({ value }) {
  const isBuy = value === 'BUY';
  return <span className={`${styles.sideBadge} ${isBuy ? styles.buy : styles.sell}`}>{isBuy ? '买入 B' : '卖出 S'}</span>;
}

export function ProfitCell({ value }) {
  const number = finiteNumber(value);
  const tone = number > 0 ? styles.positive : number < 0 ? styles.negative : '';
  return <span className={tone}>{formatNumber(value)}</span>;
}

export function ReturnCell({ value }) {
  const number = finiteNumber(value);
  const tone = number > 0 ? styles.positive : number < 0 ? styles.negative : '';
  return <span className={tone}>{formatPercent(value)}</span>;
}

export const tradeColumnDefs = [
  { headerName: '交易日期', field: 'trade_date', minWidth: 116, flex: 0.9 },
  { headerName: '股票', field: 'name', minWidth: 120, flex: 1, cellStyle: { color: '#ff7f50', fontWeight: 700 } },
  { headerName: '代码', field: 'symbol', minWidth: 110, flex: 0.9 },
  { headerName: '方向', field: 'side', minWidth: 96, flex: 0.7, cellRenderer: TradeSideCell },
  { headerName: '成交价', field: 'price', minWidth: 96, flex: 0.7, valueFormatter: params => formatNumber(params.value) },
  { headerName: '数量', field: 'quantity', minWidth: 90, flex: 0.65, valueFormatter: params => formatNumber(params.value, 0) },
  { headerName: '成交额', field: 'gross_amount', minWidth: 112, flex: 0.8, valueFormatter: params => formatNumber(params.value) },
  { headerName: '仓位', field: 'position_pct', minWidth: 88, flex: 0.65, valueFormatter: params => formatPercent(params.value) },
  { headerName: '止损价', field: 'stop_loss_price', minWidth: 92, flex: 0.7, valueFormatter: params => formatNumber(params.value) },
  { headerName: '止盈价', field: 'take_profit_price', minWidth: 92, flex: 0.7, valueFormatter: params => formatNumber(params.value) },
  { headerName: '实现盈亏', field: 'realized_pnl', minWidth: 108, flex: 0.8, cellRenderer: ProfitCell },
  { headerName: '收益率', field: 'return_pct', minWidth: 94, flex: 0.7, cellRenderer: ReturnCell },
  { headerName: '成交原因', field: 'reason', minWidth: 112, flex: 0.9, valueFormatter: params => reasonLabels[params.value] || params.value || '-' }
];

export function transformHistory(items = []) {
  if (!Array.isArray(items)) return [];
  return items.map(item => ({
    date: item.trade_date,
    open: Number(Number(item.open).toFixed(2)),
    high: Number(Number(item.high).toFixed(2)),
    low: Number(Number(item.low).toFixed(2)),
    close: Number(Number(item.close).toFixed(2)),
    volume: item.volume
  }));
}

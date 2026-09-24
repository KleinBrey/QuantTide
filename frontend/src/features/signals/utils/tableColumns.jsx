export const columnDefs = {
  confirmed_volume_breakout: [
    { headerName: '股票', field: 'name', minWidth: 120, flex: 1, cellStyle: { color: '#ff7f50', fontWeight: 700 } },
    { headerName: '代码', field: 'symbol', minWidth: 110, flex: 1 },
    { headerName: '突破日', field: 'breakout_date', minWidth: 112, flex: 0.9 },
    { headerName: '确认日', field: 'confirm_date', minWidth: 112, flex: 0.9 },
    {
      headerName: '确认收盘',
      field: 'confirm_close',
      minWidth: 92,
      flex: 0.7,
      valueFormatter: params => formatNumber(params.value)
    },
    {
      headerName: '突破量比',
      field: 'breakout_volume_ratio',
      minWidth: 104,
      flex: 0.8,
      valueFormatter: params => `${formatNumber(params.value)}x`
    },
    {
      headerName: '确认日量能',
      field: 'confirm_volume_ratio',
      minWidth: 112,
      flex: 0.8,
      valueFormatter: params => `${formatNumber(params.value)}x`
    },
    {
      headerName: '市值(亿)',
      field: 'market_cap',
      minWidth: 104,
      flex: 0.8,
      valueFormatter: params => formatMarketCap(params.value)
    },
    {
      headerName: '热度排名',
      field: 'hot_rank',
      minWidth: 100,
      flex: 0.7,
      valueFormatter: params => (params.value ? `${params.value}` : '-')
    }
  ],
  recent_volume_breakout: [
    { headerName: '股票', field: 'name', minWidth: 120, flex: 1, cellStyle: { color: '#ff7f50', fontWeight: 700 } },
    { headerName: '代码', field: 'symbol', minWidth: 110, flex: 1 },
    { headerName: '今日涨幅', field: 'latest_1d_pct', minWidth: 104, flex: 0.8, cellRenderer: PercentCell },
    {
      headerName: '成交量比',
      field: 'volume_ratio',
      minWidth: 104,
      flex: 0.8,
      valueFormatter: params => `${formatNumber(params.value)}x`
    },
    {
      headerName: '市值(亿)',
      field: 'market_cap',
      minWidth: 104,
      flex: 0.8,
      valueFormatter: params => formatMarketCap(params.value)
    },
    {
      headerName: '热度排名',
      field: 'hot_rank',
      minWidth: 100,
      flex: 0.7,
      valueFormatter: params => (params.value ? `${params.value}` : '-')
    }
  ],
  default: [
    { headerName: '股票', field: 'name', minWidth: 120, flex: 1, cellStyle: { color: '#ff7f50', fontWeight: 700 } },
    { headerName: '代码', field: 'symbol', minWidth: 110, flex: 1 },
    { headerName: '今日涨幅', field: 'latest_1d_pct', minWidth: 104, flex: 0.8, cellRenderer: PercentCell },
    {
      headerName: '市值(亿)',
      field: 'market_cap',
      minWidth: 104,
      flex: 0.8,
      valueFormatter: params => formatMarketCap(params.value)
    },
    {
      headerName: '热度排名',
      field: 'hot_rank',
      minWidth: 100,
      flex: 0.7,
      valueFormatter: params => (params.value ? `${params.value}` : '-')
    }
  ]
};

export function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatNumber(value, digits = 2) {
  const number = finiteNumber(value);
  return number === null ? '-' : number.toFixed(digits);
}

export function formatPercent(value) {
  const number = finiteNumber(value);
  if (number === null) return '-';
  const percent = number * 100;
  return `${percent > 0 ? '+' : ''}${percent.toFixed(2)}%`;
}

export function formatPlainPercent(value) {
  const number = finiteNumber(value);
  return number === null ? '-' : `${(number * 100).toFixed(2)}%`;
}

export function PercentCell({ value }) {
  const number = finiteNumber(value);
  const color = number > 0 ? '#f04451' : number < 0 ? '#24bd7a' : undefined;
  return <span style={{ color }}>{formatPercent(value)}</span>;
}

export function formatMarketCap(value) {
  const number = finiteNumber(value);
  return number === null ? '-' : formatNumber(number / 1e8);
}

export function transformHistory(items = []) {
  if (!Array.isArray(items)) return [];
  return items.map(item => ({
    date: item.trade_date,
    open: Number(item.open.toFixed(2)),
    high: Number(item.high.toFixed(2)),
    low: Number(item.low.toFixed(2)),
    close: Number(item.close.toFixed(2)),
    volume: item.volume
  }));
}

import moment from 'moment';

export function transformAShareStockHistory(items = []) {
  if (!Array.isArray(items)) return [];

  return items.map(item => {
    return {
      date: item.trade_date,
      open: Number(item.open.toFixed(2)),
      high: Number(item.high.toFixed(2)),
      low: Number(item.low.toFixed(2)),
      close: Number(item.close.toFixed(2)),
      volume: item.volume
    };
  });
}

export function attachSnapshots(stocks = [], snapshots = []) {
  const snapshotsBySymbol = new Map(
    snapshots.map(snapshot => {
      const symbol = snapshot.thscode;
      return [symbol, snapshot];
    })
  );

  return stocks.map(stock => ({
    ...stock,
    todaySnapshot: snapshotsBySymbol.get(stock?.symbol)
  }));
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function transformAShareMarketSnapshot(snapshot, date) {
  if (!snapshot) return null;

  const open = finiteNumber(snapshot.open_price);
  const high = finiteNumber(snapshot.high_price);
  const low = finiteNumber(snapshot.low_price);
  const close = finiteNumber(snapshot.last_price);
  const volume = finiteNumber(snapshot.volume / 100);

  if ([open, high, low, close, volume].some(value => value === null)) return null;

  return {
    date,
    open,
    high,
    low,
    close,
    volume
  };
}

export function mergeAShareStockHistoryWithSnapshot(historyRows = [], snapshot = null) {
  const today = moment().format('YYYY-MM-DD');
  const todayRow = transformAShareMarketSnapshot(snapshot, today);
  const rowsByDate = new Map((Array.isArray(historyRows) ? historyRows : []).map(row => [String(row.date), row]));
  if (todayRow) rowsByDate.set(today, todayRow);

  return [...rowsByDate.values()].sort((left, right) => String(left.date).localeCompare(String(right.date)));
}

export function transformAShareMarketResponse(payload) {
  const normalizeRows = rows =>
    (Array.isArray(rows) ? rows : []).map((row, index) => ({
      ...row,
      rank: row.rank ?? index + 1,
      name: row.name ?? row.股票简称 ?? '',
      thscode: row.thscode ?? row.code ?? row.symbol ?? '',
      heat: row.rank ?? row.hotRank ?? '-'
    }));

  if (Array.isArray(payload?.items)) {
    const ranking = payload.items.find(item => item.id === 'hot-stock-list') || payload.items[0];
    return {
      id: ranking?.id || 'hot-stock-list',
      title: ranking?.title || '同花顺热榜',
      timestamp: ranking?.timestamp || ranking?.updatedAt || null,
      rows: normalizeRows(ranking?.rows)
    };
  }

  return {
    id: 'hot-stock-list',
    title: '同花顺热榜',
    timestamp: payload?.data?.timestamp ?? null,
    rows: normalizeRows(payload?.data?.item)
  };
}

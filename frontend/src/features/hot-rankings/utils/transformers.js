export function transformStockHistory(items = []) {
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

export function transformHotRankingResponse(payload) {
  const normalizeRows = rows =>
    (Array.isArray(rows) ? rows : []).map((row, index) => ({
      ...row,
      rank: row.rank ?? index + 1,
      name: row.name ?? row.股票简称 ?? '',
      thscode: row.thscode ?? row.code ?? row.symbol ?? '',
      heat: row.rank ?? row.hotRank ?? '-'
    }));

  if (Array.isArray(payload)) {
    return {
      id: 'hot-stock-list',
      title: '股票热榜',
      timestamp: payload[0]?.update_time ?? null,
      rows: normalizeRows(payload)
    };
  }

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

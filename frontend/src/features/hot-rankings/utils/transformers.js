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
  const rows = Array.isArray(payload) ? payload : [];
  return {
    id: 'hot-stock-list',
    title: '股票热榜',
    timestamp: rows[0]?.update_time ?? null,
    rows: rows.map(row => ({
      ...row,
      thscode: row.symbol,
      heat: row.rank
    }))
  };
}

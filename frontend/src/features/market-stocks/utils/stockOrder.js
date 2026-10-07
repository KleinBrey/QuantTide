export function restoreStockOrder(stocks, symbols) {
  if (!Array.isArray(symbols)) return stocks;
  const bySymbol = new Map(stocks.map(stock => [stock.symbol, stock]));
  const ordered = [];
  for (const symbol of symbols) {
    if (!bySymbol.has(symbol)) continue;
    ordered.push(bySymbol.get(symbol));
    bySymbol.delete(symbol);
  }
  return [...ordered, ...bySymbol.values()];
}

export function moveStock(stocks, symbol, position) {
  const stock = stocks.find(item => item.symbol === symbol);
  if (!stock) return stocks;
  const remaining = stocks.filter(item => item.symbol !== symbol);
  return position === 'first' ? [stock, ...remaining] : [...remaining, stock];
}

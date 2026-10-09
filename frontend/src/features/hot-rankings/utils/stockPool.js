// 与后端 normalize_daily_bar_symbol 保持一致，热榜代码可能带交易所后缀。
export function stockPoolSymbol(stock, marketId) {
  const symbol = String(stock?.thscode || stock?.code || stock?.symbol || '').trim().toUpperCase();
  if (marketId === 'hk-share') {
    const code = symbol.replace(/^HK\./, '').replace(/\.HK$/, '');
    return /^\d{1,5}$/.test(code) ? `${code.padStart(5, '0')}.HK` : '';
  }
  if (marketId === 'us-share') {
    const code = symbol.startsWith('US.')
      ? symbol.slice(3)
      : symbol.endsWith('.US') ? symbol.slice(0, -3) : symbol.replace(/\.(O|N|A)$/, '');
    return /^[A-Z0-9][A-Z0-9.-]*$/.test(code) && !code.endsWith('.') ? code : '';
  }
  return '';
}

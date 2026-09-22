import { useState } from 'react';

import StockKlineChart from '@/components/TradingView/StockKlineChart.jsx';

export default function AShareStockKlinePanel({ stock, data, loading, error, enableMouseWheelZoom = true }) {
  const [period, setPeriod] = useState('daily');
  const chartStock = stock
    ? {
        ...stock,
        code: stock.thscode || stock.code
      }
    : null;

  return (
    <StockKlineChart
      stock={chartStock}
      data={data}
      loading={loading}
      error={error}
      period={period}
      onPeriodChange={setPeriod}
      enableMouseWheelZoom={enableMouseWheelZoom}
    />
  );
}

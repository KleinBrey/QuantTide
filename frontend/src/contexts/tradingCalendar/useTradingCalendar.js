import { useContext } from 'react';

import { TradingCalendarContext } from './tradingCalendarContext.js';

export function useTradingCalendar() {
  const context = useContext(TradingCalendarContext);

  if (!context) {
    throw new Error('useTradingCalendar 必须在 TradingCalendarProvider 内使用');
  }

  return context;
}

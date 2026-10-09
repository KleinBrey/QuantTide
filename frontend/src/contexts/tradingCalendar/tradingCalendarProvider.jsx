import { useCallback, useEffect, useMemo, useState } from 'react';

import { getTradingDaysCalendarApi } from '@/api/hithink/api.js';
import { TradingCalendarContext } from './tradingCalendarContext.js';

let cachedCalendar = null;
let calendarRequest = null;

function requestTradingCalendarOnce() {
  if (cachedCalendar) {
    return Promise.resolve(cachedCalendar);
  }

  if (!calendarRequest) {
    calendarRequest = getTradingDaysCalendarApi()
      .then(payload => {
        const calendar = payload.data.item;
        const latestTradingDay = calendar.at(-1)?.date;

        if (!latestTradingDay) {
          throw new Error('交易日历为空或日期格式无效');
        }

        cachedCalendar = {
          calendar,
          latestTradingDay
        };

        return cachedCalendar;
      })
      .catch(error => {
        calendarRequest = null;
        throw error;
      });
  }

  return calendarRequest;
}

export function TradingCalendarProvider({ children }) {
  const [calendar, setCalendar] = useState([]);
  const [latestTradingDay, setLatestTradingDay] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadCalendar = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const result = await requestTradingCalendarOnce();

      setCalendar(result.calendar);
      setLatestTradingDay(result.latestTradingDay);

      return result;
    } catch (error) {
      setError(error.message || '交易日历加载失败');
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  const getLatestTradingDay = useCallback(async () => {
    if (cachedCalendar) {
      return cachedCalendar.latestTradingDay;
    }

    const result = await loadCalendar();

    return result.latestTradingDay;
  }, [loadCalendar]);

  useEffect(() => {
    loadCalendar().catch(() => {});
  }, [loadCalendar]);

  const value = useMemo(
    () => ({
      calendar,
      latestTradingDay,
      loading,
      error,
      getLatestTradingDay
    }),
    [calendar, latestTradingDay, loading, error, getLatestTradingDay]
  );

  return <TradingCalendarContext.Provider value={value}>{children}</TradingCalendarContext.Provider>;
}

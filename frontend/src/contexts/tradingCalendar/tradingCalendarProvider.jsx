import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getTradingDaysCalendarApi } from '@/api/hithink/api.js';
import { TradingCalendarContext } from './tradingCalendarContext.js';

let cachedCalendar = null;
let calendarRequest = null;

function extractTradingDays(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.data?.item)) return payload.data.item;
  if (Array.isArray(payload?.item)) return payload.item;
  return [];
}

function findLatestTradingDay(calendar) {
  return calendar.reduce((latest, item) => {
    const date = String(item?.date ?? '');
    if (!/^\d{8}$/.test(date)) return latest;
    return !latest || date > latest ? date : latest;
  }, null);
}

function requestTradingCalendarOnce() {
  if (cachedCalendar) return Promise.resolve(cachedCalendar);

  if (!calendarRequest) {
    calendarRequest = getTradingDaysCalendarApi()
      .then(payload => {
        const calendar = extractTradingDays(payload);
        const latestTradingDay = findLatestTradingDay(calendar);

        if (!latestTradingDay) {
          throw new Error('交易日历为空或日期格式无效');
        }

        cachedCalendar = { calendar, latestTradingDay };
        return cachedCalendar;
      })
      .catch(error => {
        // 请求失败后允许下一次调用重试。
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
  const latestTradingDayRef = useRef(null);

  const loadCalendar = useCallback(async () => {
    if (latestTradingDayRef.current) return cachedCalendar;

    setLoading(true);
    setError('');

    try {
      const result = await requestTradingCalendarOnce();
      latestTradingDayRef.current = result.latestTradingDay;
      setCalendar(result.calendar);
      setLatestTradingDay(result.latestTradingDay);
      return result;
    } catch (requestError) {
      setError(requestError.message || '交易日历加载失败');
      throw requestError;
    } finally {
      setLoading(false);
    }
  }, []);

  const getLatestTradingDay = useCallback(async () => {
    if (latestTradingDayRef.current) return latestTradingDayRef.current;
    const result = await loadCalendar();
    return result.latestTradingDay;
  }, [loadCalendar]);

  useEffect(() => {
    loadCalendar().catch(() => {});
  }, [loadCalendar]);

  const value = useMemo(
    () => ({ calendar, latestTradingDay, loading, error, getLatestTradingDay }),
    [calendar, latestTradingDay, loading, error, getLatestTradingDay]
  );

  return <TradingCalendarContext.Provider value={value}>{children}</TradingCalendarContext.Provider>;
}

import React, { useEffect, useMemo, useRef, useState } from 'react';
import moment from 'moment';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart
} from 'lightweight-charts';
import { Loader2, RotateCcw } from 'lucide-react';
import { Button } from '@/shadcn/components/ui/button.jsx';
import styles from './StockKlineChart.module.css';

const periodOptions = [
  ['daily', '日线'],
  ['weekly', '周线'],
  ['monthly', '月线']
];

const movingAverages = [
  { days: 5, color: '#f59e0b' },
  { days: 10, color: '#38bdf8' },
  { days: 20, color: '#a78bfa' }
];

const weekdayLabels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function timeKey(value) {
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (value && typeof value === 'object' && 'year' in value) {
    const month = String(value.month).padStart(2, '0');
    const day = String(value.day).padStart(2, '0');
    return `${value.year}-${month}-${day}`;
  }
  return '';
}

function formatCrosshairDate(value) {
  const timestamp =
    typeof value === 'number' ? moment.unix(value).utc() : moment.utc(timeKey(value), 'YYYY-MM-DD', true);

  if (!timestamp.isValid()) return String(value ?? '');
  return `${weekdayLabels[timestamp.day()]} ${timestamp.format('YYYY-MM-DD')}`;
}

function chartRows(data) {
  return (data?.rows || [])
    .map(row => ({
      ...row,
      time: row.date,
      open: Number(row.open),
      high: Number(row.high),
      low: Number(row.low),
      close: Number(row.close),
      volume: Number(row.volume || 0)
    }))
    .filter(row => row.time && [row.open, row.high, row.low, row.close, row.volume].every(Number.isFinite))
    .sort((left, right) => String(left.time).localeCompare(String(right.time)));
}

function weekKey(time) {
  return moment.utc(String(time), 'YYYY-MM-DD', true).startOf('isoWeek').format('YYYY-MM-DD');
}

function aggregateRows(rows, period) {
  if (period === 'daily') return rows;

  const groups = new Map();

  rows.forEach(row => {
    const key = period === 'weekly' ? weekKey(row.time) : String(row.time).slice(0, 7);
    const current = groups.get(key);

    if (!current) {
      groups.set(key, { ...row });
      return;
    }

    current.time = row.time;
    current.date = row.date;
    current.high = Math.max(current.high, row.high);
    current.low = Math.min(current.low, row.low);
    current.close = row.close;
    current.volume += row.volume;
  });

  return Array.from(groups.values());
}

function calculateMA(rows, dayCount) {
  let rollingTotal = 0;
  return rows.flatMap((row, index) => {
    rollingTotal += row.close;
    if (index >= dayCount) rollingTotal -= rows[index - dayCount].close;
    if (index < dayCount - 1) return [];
    return [{ time: row.time, value: Number((rollingTotal / dayCount).toFixed(3)) }];
  });
}

function formatPrice(value) {
  return Number.isFinite(Number(value))
    ? Number(value).toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 3
      })
    : '—';
}

function formatVolume(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  if (number >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return number.toLocaleString('zh-CN');
}

function formatChangePercent(value) {
  if (value == null) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
}

function rowSummary(row, previousRow) {
  if (!row) return null;

  const previousClose = Number(previousRow?.close);
  const changePct =
    Number.isFinite(previousClose) && previousClose !== 0 ? ((row.close - previousClose) / previousClose) * 100 : null;

  return {
    time: row.time,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
    volume: row.volume,
    changePct,
    rising: row.close >= row.open
  };
}

function resetTimeScale(chart, rowCount) {
  if (rowCount > 120) {
    chart.timeScale().setVisibleLogicalRange({
      from: rowCount - 120,
      to: rowCount - 1 // 右侧不留空隙
    });
    return;
  }

  chart.timeScale().fitContent();
}

export default function StockKlineChart({
  data,
  stock,
  loading,
  error,
  period,
  onPeriodChange,
  enableMouseWheelZoom = true
}) {
  const chartRef = useRef(null);
  const contextMenuRef = useRef(null);
  const resetViewRef = useRef(() => {});
  const dailyRows = useMemo(() => chartRows(data), [data]);
  const rows = useMemo(() => aggregateRows(dailyRows, period), [dailyRows, period]);
  const stockName = stock?.name;
  const stockCode = stock?.symbol || stock?.code || stock?.thscode;
  const [activeBar, setActiveBar] = useState(() => rowSummary(rows.at(-1), rows.at(-2)));
  const [contextMenu, setContextMenu] = useState(null);

  useEffect(() => {
    setActiveBar(rowSummary(rows.at(-1), rows.at(-2)));
    setContextMenu(null);
  }, [rows]);

  useEffect(() => {
    if (!contextMenu) return undefined;

    contextMenuRef.current?.querySelector('button')?.focus();

    const closeMenu = event => {
      if (!contextMenuRef.current?.contains(event.target)) setContextMenu(null);
    };
    const closeOnEscape = event => {
      if (event.key === 'Escape') setContextMenu(null);
    };
    const close = () => setContextMenu(null);

    document.addEventListener('pointerdown', closeMenu);
    document.addEventListener('keydown', closeOnEscape);
    window.addEventListener('blur', close);
    window.addEventListener('resize', close);

    return () => {
      document.removeEventListener('pointerdown', closeMenu);
      document.removeEventListener('keydown', closeOnEscape);
      window.removeEventListener('blur', close);
      window.removeEventListener('resize', close);
    };
  }, [contextMenu]);

  useEffect(() => {
    const container = chartRef.current;
    if (!container || !rows.length) return undefined;

    const chart = createChart(container, {
      autoSize: true,
      height: 520,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: '#111114' },
        textColor: '#a1a1aa',
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        panes: {
          separatorColor: '#27272a',
          separatorHoverColor: '#3f3f46',
          enableResize: true
        }
      },
      grid: {
        vertLines: { color: '#202024', style: LineStyle.Dotted },
        horzLines: { color: '#27272a', style: LineStyle.Dotted }
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#71717a',
          labelBackgroundColor: '#27272a',
          style: LineStyle.Dashed,
          labelVisible: true
        },
        horzLine: {
          color: '#71717a',
          labelBackgroundColor: '#27272a',
          style: LineStyle.Dashed,
          labelVisible: true
        }
      },
      rightPriceScale: {
        borderColor: '#3f3f46',
        entireTextOnly: true,
        scaleMargins: { top: 0.12, bottom: 0.08, right: 0.02 }
      },
      timeScale: {
        borderColor: '#3f3f46',
        rightOffset: 0,
        barSpacing: 8,
        minBarSpacing: 3,
        fixLeftEdge: false,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        timeVisible: false
      },
      localization: {
        locale: 'zh-CN',
        timeFormatter: formatCrosshairDate
      },
      handleScroll: {
        mouseWheel: enableMouseWheelZoom,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: enableMouseWheelZoom,
        pinch: true
      }
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
      priceLineVisible: false,
      lastValueVisible: true
    });

    candleSeries.setData(
      rows.map(({ time, open, high, low, close }) => ({
        time,
        open,
        high,
        low,
        close
      }))
    );

    movingAverages.forEach(({ days, color }) => {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false
        // title: `MA${days}`,
      });
      series.setData(calculateMA(rows, days));
    });

    const volumeSeries = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
        lastValueVisible: false
      },
      1
    );
    volumeSeries.setData(
      rows.map(row => ({
        time: row.time,
        value: row.volume,
        color: row.close >= row.open ? 'rgba(239, 68, 68, 0.72)' : 'rgba(34, 197, 94, 0.72)'
      }))
    );

    const panes = chart.panes();
    if (panes[1]) panes[1].setHeight(120);

    resetViewRef.current = () => {
      candleSeries.priceScale().applyOptions({ autoScale: true });
      volumeSeries.priceScale().applyOptions({ autoScale: true });
      resetTimeScale(chart, rows.length);
    };

    const summariesByTime = new Map(rows.map((row, index) => [String(row.time), rowSummary(row, rows[index - 1])]));
    const latestSummary = rowSummary(rows.at(-1), rows.at(-2));
    const handleCrosshairMove = parameter => {
      const selected = parameter.time ? summariesByTime.get(timeKey(parameter.time)) : latestSummary;
      setActiveBar(selected || latestSummary);
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    resetTimeScale(chart, rows.length);

    return () => {
      resetViewRef.current = () => {};
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
    };
  }, [enableMouseWheelZoom, rows]);

  const handleContextMenu = event => {
    event.preventDefault();

    const bounds = event.currentTarget.getBoundingClientRect();
    const menuWidth = 232;
    const menuHeight = 48;
    const leftLimit = Math.max(8, bounds.width - menuWidth - 8);
    const topLimit = Math.max(8, bounds.height - menuHeight - 8);

    setContextMenu({
      left: Math.max(8, Math.min(event.clientX - bounds.left, leftLimit)),
      top: Math.max(8, Math.min(event.clientY - bounds.top, topLimit))
    });
  };

  const handleResetView = () => {
    resetViewRef.current();
    setActiveBar(rowSummary(rows.at(-1), rows.at(-2)));
    setContextMenu(null);
  };

  return (
    <section className={styles.kline}>
      <div className={styles.header}>
        <div>
          <h3>{stock ? `${stockName}  |  ${String(stockCode)}` : '个股 K 线'}</h3>
          <span>TradingView Charts</span>
        </div>
        <div className={styles.periods}>
          {periodOptions.map(([value, label]) => (
            <Button
              key={value}
              type="button"
              className={period === value ? styles.active : ''}
              onClick={() => onPeriodChange(value)}
              disabled={!stock || loading}
              size="sm"
              variant="ghost"
            >
              {label}
            </Button>
          ))}
        </div>
      </div>
      {loading ? (
        <div className={styles.state}>
          <Loader2 className={styles.spinner} size={24} />
          <span>正在读取股票历史行情</span>
        </div>
      ) : error ? (
        <div className={styles.state + ' ' + styles.error}>
          <span>{error}</span>
        </div>
      ) : rows.length ? (
        <div className={styles.chartShell} onContextMenu={handleContextMenu}>
          {activeBar ? (
            <div className={styles.legend} aria-live="polite">
              <div className={styles.legendValues}>
                <span className={styles.legendDate}>{activeBar.time}</span>
                <span>
                  开 <strong>{formatPrice(activeBar.open)}</strong>
                </span>
                <span>
                  高 <strong>{formatPrice(activeBar.high)}</strong>
                </span>
                <span>
                  低 <strong>{formatPrice(activeBar.low)}</strong>
                </span>
                <span>
                  收{' '}
                  <strong className={activeBar.rising ? styles.rise : styles.fall}>
                    {formatPrice(activeBar.close)}
                  </strong>
                </span>
                <span>
                  量 <strong>{formatVolume(activeBar.volume)}</strong>
                </span>
                <span>
                  涨幅{' '}
                  <strong
                    className={
                      activeBar.changePct > 0 ? styles.rise : activeBar.changePct < 0 ? styles.fall : undefined
                    }
                  >
                    {formatChangePercent(activeBar.changePct)}
                  </strong>
                </span>
              </div>
              <div className={styles.legendValues}>
                {movingAverages.map(({ days, color }) => (
                  <span className={styles.maKey} key={days} style={{ '--ma-color': color }}>
                    MA{days}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          <div
            className={styles.canvas}
            ref={chartRef}
            role="img"
            aria-label={`${stockName || '个股'} K线、均线及成交量图`}
          />
          {contextMenu ? (
            <div
              aria-label="图表操作菜单"
              className={styles.contextMenu}
              onContextMenu={event => event.preventDefault()}
              ref={contextMenuRef}
              role="menu"
              style={{ left: contextMenu.left, top: contextMenu.top }}
              tabIndex={-1}
            >
              <button onClick={handleResetView} role="menuitem" type="button">
                <RotateCcw aria-hidden="true" size={18} />
                <span>重置图表视图</span>
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className={styles.state}>
          <span>无数据展示</span>
        </div>
      )}
    </section>
  );
}

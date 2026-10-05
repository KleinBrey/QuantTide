import { useEffect, useMemo, useRef, useState } from 'react';
import { LineChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { getIndexHistoricalPriceApi } from '@/api/hithink/api.js';
import { formatPercent } from '../utils/backtestFormatters.jsx';
import styles from './BacktestResultsView.module.css';

echarts.use([CanvasRenderer, GridComponent, LineChart, MarkLineComponent, TooltipComponent]);

function normalizeEquityCurve(equityCurve) {
  return (equityCurve || [])
    .map(row => ({
      date: row.trade_date,
      totalEquity: Number(row.total_equity)
    }))
    .filter(row => row.date && Number.isFinite(row.totalEquity));
}

// 按上海交易日期对齐，沪深300收益率以回测首日收盘价为基准。
function getBenchmarkReturns(points, bars, initialCash) {
  const closeByDate = new Map();
  for (const bar of bars) {
    const close = Number(bar.close_price);
    const timestamp = Number(bar.date_ms);
    if (bar.date_ms == null || !Number.isFinite(timestamp) || !Number.isFinite(close) || close <= 0) continue;
    const date = new Date(timestamp + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
    closeByDate.set(date, close);
  }

  const firstClose = closeByDate.get(points[0]?.date);
  if (!firstClose || !Number.isFinite(initialCash) || initialCash <= 0) return [];
  return points.map(({ date }) => {
    const close = closeByDate.get(date);
    return close == null ? null : close / firstClose - 1;
  });
}

function returnClass(value) {
  if (value > 0) return styles.positive;
  if (value < 0) return styles.negative;
  return undefined;
}

function buildChartOption(points, initialCash, benchmark) {
  const dates = points.map(point => point.date);
  const returns = points.map(point => (initialCash > 0 ? point.totalEquity / initialCash - 1 : null));

  return {
    animationDuration: 650,
    animationEasing: 'cubicOut',
    grid: { left: 16, right: 22, top: 24, bottom: 18, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        lineStyle: { color: '#71717a', type: 'dashed' },
        type: 'line'
      },
      backgroundColor: '#18181b',
      borderColor: '#3f3f46',
      borderWidth: 1,
      extraCssText: 'box-shadow: 0 10px 30px rgba(0, 0, 0, 0.38);',
      padding: [10, 12],
      textStyle: { color: '#f4f4f5', fontSize: 12 },
      formatter(params) {
        const point = points[params?.[0]?.dataIndex];
        if (!point) return '';
        const benchmarkReturn = benchmark[params[0].dataIndex];
        return [
          `<div style="color:#a1a1aa;margin-bottom:7px">${point.date}</div>`,
          `<div style="display:flex;gap:24px;justify-content:space-between;color:#f59e0b"><span>策略收益率</span><strong>${formatPercent(returns[params[0].dataIndex])}</strong></div>`,
          `<div style="display:flex;gap:24px;justify-content:space-between;margin-top:7px;color:#38bdf8"><span>沪深300</span><strong>${benchmarkReturn == null ? '暂无数据' : formatPercent(benchmarkReturn)}</strong></div>`
        ].join('');
      }
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: '#3f3f46' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#71717a',
        fontSize: 11,
        hideOverlap: true,
        margin: 12,
        showMaxLabel: true,
        showMinLabel: true,
        formatter: value => value.slice(5)
      }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: '#71717a',
        fontSize: 11,
        formatter: value => `${Number((value * 100).toFixed(2))}%`
      },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#27272a', type: 'dashed' } }
    },
    series: [
      {
        name: '沪深300',
        type: 'line',
        data: benchmark,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: '#38bdf8', width: 2 },
        itemStyle: { color: '#38bdf8' }
      },
      {
        name: '策略收益率',
        type: 'line',
        data: returns,
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: '#f59e0b', width: 2 },
        itemStyle: { color: '#f59e0b' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(245, 158, 11, 0.28)' },
              { offset: 1, color: 'rgba(245, 158, 11, 0.01)' }
            ]
          }
        },
        emphasis: {
          itemStyle: { borderColor: '#18181b', borderWidth: 2, color: '#fbbf24' },
          scale: 1.5
        },
        markLine:
          initialCash > 0
            ? {
                silent: true,
                symbol: 'none',
                data: [{ name: '零收益', yAxis: 0 }],
                label: {
                  color: '#a1a1aa',
                  fontSize: 11,
                  formatter: '0%',
                  position: 'insideEndTop'
                },
                lineStyle: { color: '#52525b', type: 'dashed', width: 1 }
              }
            : undefined
      }
    ]
  };
}

export default function BacktestEquityChart({ equityCurve, initialCash, loading }) {
  const chartElementRef = useRef(null);
  const [indexState, setIndexState] = useState(null);
  const points = useMemo(() => normalizeEquityCurve(equityCurve), [equityCurve]);
  const initialEquity = Number(initialCash) > 0 ? Number(initialCash) : points[0]?.totalEquity;
  const periodReturn = initialEquity ? points.at(-1)?.totalEquity / initialEquity - 1 : null;
  const startDate = points[0]?.date;
  const endDate = points.at(-1)?.date;
  const rangeKey = `${startDate}/${endDate}`;
  const indexReady = indexState?.rangeKey === rangeKey;
  const benchmark = useMemo(
    () => getBenchmarkReturns(points, indexReady ? indexState.bars || [] : [], initialEquity),
    [points, indexReady, indexState, initialEquity]
  );
  const benchmarkReturn = benchmark.at(-1);
  const benchmarkStatus = !indexReady
    ? '沪深300加载中…'
    : indexState.error || (!benchmark.length ? '沪深300暂无回测首日数据，无法对比' : '');

  useEffect(() => {
    if (!startDate || !endDate) return undefined;
    // 切换回测区间后，忽略旧请求的结果。
    let active = true;
    getIndexHistoricalPriceApi({
      thscode: '000300.SH',
      interval: '1d',
      start: Date.parse(`${startDate}T00:00:00+08:00`),
      end: Date.parse(`${endDate}T23:59:59.999+08:00`)
    })
      .then(response => {
        if (active) setIndexState({ rangeKey, bars: response?.data?.item || [] });
      })
      .catch(() => {
        if (active) setIndexState({ rangeKey, error: '沪深300加载失败，请稍后刷新页面重试' });
      });
    return () => {
      active = false;
    };
  }, [startDate, endDate, rangeKey]);

  useEffect(() => {
    const element = chartElementRef.current;
    if (!element || points.length === 0) return undefined;

    const chart = echarts.init(element);
    chart.setOption(buildChartOption(points, initialEquity, benchmark));
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(element);

    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [initialEquity, points, benchmark]);

  return (
    <section className={`dashboard-panel ${styles.equityPanel}`}>
      <div className={`dashboard-panel-header ${styles.equityHeader}`}>
        <div>
          <h2>收益率走势</h2>
        </div>
        {points.length > 0 ? (
          <div className={styles.equitySnapshots}>
            <div className={styles.equitySnapshot}>
              <span>
                <i />
                策略收益率
              </span>
              <em className={returnClass(periodReturn)}>{formatPercent(periodReturn)}</em>
            </div>
            <div className={styles.equitySnapshot}>
              <span>
                <i className={styles.benchmarkDot} />
                沪深300
              </span>
              {benchmarkStatus ? (
                <small role="status">{benchmarkStatus}</small>
              ) : (
                <em className={returnClass(benchmarkReturn)}>{formatPercent(benchmarkReturn)}</em>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <div className={styles.equityChartWrap}>
        <div
          ref={chartElementRef}
          aria-label="策略与沪深300累计收益率对比折线图"
          className={styles.equityChart}
          role="img"
        />
        {points.length === 0 && (
          <div className={styles.chartState}>
            {loading ? '正在加载收益率曲线…' : '当前回测暂无收益率曲线数据'}
          </div>
        )}
      </div>
    </section>
  );
}

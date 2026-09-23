import { useEffect, useMemo, useRef } from 'react';
import { LineChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { formatNumber, formatPercent } from '../utils/backtestFormatters.jsx';
import styles from './BacktestResultsView.module.css';

echarts.use([CanvasRenderer, GridComponent, LineChart, MarkLineComponent, TooltipComponent]);

function normalizeEquityCurve(equityCurve) {
  return (equityCurve || [])
    .map((row) => ({
      date: row.trade_date,
      cash: Number(row.cash),
      marketValue: Number(row.market_value),
      totalEquity: Number(row.total_equity),
    }))
    .filter((row) => row.date && Number.isFinite(row.totalEquity));
}

function formatAxisAmount(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '-';
  if (Math.abs(amount) >= 10_000) return `${(amount / 10_000).toFixed(0)}万`;
  return amount.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

function buildChartOption(points, initialCash) {
  const dates = points.map((point) => point.date);
  const equity = points.map((point) => point.totalEquity);

  return {
    animationDuration: 650,
    animationEasing: 'cubicOut',
    grid: {
      bottom: 18,
      containLabel: true,
      left: 16,
      right: 22,
      top: 24,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        lineStyle: { color: '#71717a', type: 'dashed' },
        type: 'line',
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
        return [
          `<div style="color:#a1a1aa;margin-bottom:7px">${point.date}</div>`,
          `<div style="display:flex;gap:24px;justify-content:space-between"><span>资金余额</span><strong>${formatNumber(point.totalEquity)}</strong></div>`,
          `<div style="display:flex;gap:24px;justify-content:space-between;margin-top:5px;color:#a1a1aa"><span>现金</span><span>${formatNumber(point.cash)}</span></div>`,
          `<div style="display:flex;gap:24px;justify-content:space-between;margin-top:5px;color:#a1a1aa"><span>持仓市值</span><span>${formatNumber(point.marketValue)}</span></div>`,
        ].join('');
      },
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
        formatter: (value) => value.slice(5),
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: '#71717a',
        fontSize: 11,
        formatter: formatAxisAmount,
      },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#27272a', type: 'dashed' } },
    },
    series: [
      {
        name: '资金余额',
        type: 'line',
        data: equity,
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: '#f59e0b', width: 2 },
        itemStyle: { color: '#f59e0b' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(245, 158, 11, 0.28)' },
              { offset: 1, color: 'rgba(245, 158, 11, 0.01)' },
            ],
          },
        },
        emphasis: {
          focus: 'series',
          itemStyle: { borderColor: '#18181b', borderWidth: 2, color: '#fbbf24' },
          scale: 1.5,
        },
        markLine: Number.isFinite(initialCash)
          ? {
              silent: true,
              symbol: 'none',
              data: [{ name: '初始资金', yAxis: initialCash }],
              label: {
                color: '#a1a1aa',
                fontSize: 11,
                formatter: '初始资金',
                position: 'insideEndTop',
              },
              lineStyle: { color: '#52525b', type: 'dashed', width: 1 },
            }
          : undefined,
      },
    ],
  };
}

export default function BacktestEquityChart({ equityCurve, initialCash, loading }) {
  const chartElementRef = useRef(null);
  const points = useMemo(() => normalizeEquityCurve(equityCurve), [equityCurve]);
  const firstEquity = points[0]?.totalEquity;
  const lastEquity = points.at(-1)?.totalEquity;
  const initialEquity = Number(initialCash) > 0 ? Number(initialCash) : firstEquity;
  const periodReturn = initialEquity ? lastEquity / initialEquity - 1 : null;
  const periodReturnTone = periodReturn > 0 ? styles.positive : periodReturn < 0 ? styles.negative : undefined;

  useEffect(() => {
    const element = chartElementRef.current;
    if (!element || points.length === 0) return undefined;

    const chart = echarts.init(element);
    chart.setOption(buildChartOption(points, Number(initialCash)));
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(element);

    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [initialCash, points]);

  const showLoading = loading && points.length === 0;
  const showEmpty = !loading && points.length === 0;

  return (
    <section className={`dashboard-panel ${styles.equityPanel}`}>
      <div className={`dashboard-panel-header ${styles.equityHeader}`}>
        <div>
          <h2>资金余额走势</h2>
          <span>每日账户总资产变化，悬停可查看现金与持仓市值</span>
        </div>
        {points.length > 0 ? (
          <div className={styles.equitySnapshot}>
            <span><i />资金余额</span>
            <strong>{formatNumber(lastEquity)}</strong>
            <em className={periodReturnTone}>{formatPercent(periodReturn)}</em>
          </div>
        ) : null}
      </div>
      <div className={styles.equityChartWrap}>
        <div
          ref={chartElementRef}
          aria-label="资金余额走势折线图"
          className={styles.equityChart}
          role="img"
        />
        {showLoading ? <div className={styles.chartState}>正在加载资金曲线…</div> : null}
        {showEmpty ? <div className={styles.chartState}>当前回测暂无资金曲线数据</div> : null}
      </div>
    </section>
  );
}

import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spinner } from '@/shadcn/components/ui/spinner.jsx';
import PlaceholderDashboard from '@/components/PlaceholderDashboard.jsx';
import placeholderStyles from '@/components/PlaceholderDashboard.module.css';
import { defaultDashboardPath } from '@/routes/RouteConfig.js';

const DataSourcesDashboard = lazy(() => import('@/pages/DataSourcesDashboard.jsx'));
const HotRankingsDashboard = lazy(() => import('@/pages/HotRankingsDashboard.jsx'));
const SignalsDashboard = lazy(() => import('@/pages/SignalsDashboard.jsx'));
const StrategyBacktestsDashboard = lazy(() => import('@/pages/StrategyBacktestsDashboard.jsx'));
const MarketStocks = lazy(() => import('@/pages/MarketStocks.jsx'));

function RouteFallback() {
  return (
    <section className={placeholderStyles.placeholder}>
      <Spinner />
      <h2>加载页面</h2>
      <p>正在准备数据和界面</p>
    </section>
  );
}

export default function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route index element={<Navigate to={defaultDashboardPath} replace />} />
        <Route path="/hot-rankings" element={<HotRankingsDashboard />} />
        <Route path="/data-sources" element={<DataSourcesDashboard />} />
        <Route path="/signals" element={<SignalsDashboard />} />
        <Route path="/strategy-backtests" element={<StrategyBacktestsDashboard />} />
        <Route path="/a-share-market" element={<MarketStocks marketId="a-share" />} />
        <Route path="/hk-share-market" element={<MarketStocks marketId="hk-share" />} />
        <Route path="/us-share-market" element={<MarketStocks marketId="us-share" />} />

        <Route path="/chart-center" element={<PlaceholderDashboard dashboardId="chart-center" />} />
        <Route path="*" element={<Navigate to={defaultDashboardPath} replace />} />
      </Routes>
    </Suspense>
  );
}

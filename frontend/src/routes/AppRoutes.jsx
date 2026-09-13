import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spinner } from '@/shadcn/components/ui/spinner.jsx';
import PlaceholderDashboard from '@/components/PlaceholderDashboard.jsx';
import placeholderStyles from '@/components/PlaceholderDashboard.module.css';
import { defaultDashboardPath } from '@/routes/RouteConfig.js';

const DataSourcesDashboard = lazy(() => import('@/pages/DataSourcesDashboard.jsx'));
const HotRankingsDashboard = lazy(() => import('@/pages/HotRankingsDashboard.jsx'));
const StrategySignalsDashboard = lazy(() => import('@/pages/StrategySignalsDashboard.jsx'));
const AShareMarket = lazy(() => import('@/pages/AShareMarket.jsx'));
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
        <Route path="/strategy-signals" element={<StrategySignalsDashboard />} />
        <Route path="/a-share-market" element={<AShareMarket />} />
        <Route path="/hk-share-market" element={<MarketStocks key="hk-share" marketId="hk-share" />} />
        <Route path="/us-share-market" element={<MarketStocks key="us-share" marketId="us-share" />} />

        <Route path="/chart-center" element={<PlaceholderDashboard dashboardId="chart-center" />} />
        <Route path="*" element={<Navigate to={defaultDashboardPath} replace />} />
      </Routes>
    </Suspense>
  );
}

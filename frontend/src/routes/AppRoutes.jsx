import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { RouteFallback } from '@/components/pageState';
import { defaultDashboardPath } from '@/routes/RouteConfig.js';
import MarketStocks from '@/pages/MarketStocks.jsx';
import CryptoMarket from '@/pages/CryptoMarket.jsx';

const DataSourcesDashboard = lazy(() => import('@/pages/DataSourcesDashboard.jsx'));
const HotRankingsDashboard = lazy(() => import('@/pages/HotRankingsDashboard.jsx'));
const SignalsDashboard = lazy(() => import('@/pages/SignalsDashboard.jsx'));
const StrategyBacktestsDashboard = lazy(() => import('@/pages/StrategyBacktestsDashboard.jsx'));

export default function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route index element={<Navigate to={defaultDashboardPath} replace />} />
        <Route path="/hot-rankings" element={<HotRankingsDashboard />} />
        <Route path="/data-sources" element={<DataSourcesDashboard />} />
        <Route path="/signals" element={<SignalsDashboard />} />
        <Route path="/strategy-backtests" element={<StrategyBacktestsDashboard />} />
        <Route path="/cn_stock-market" element={<MarketStocks marketId="cn_stock" />} />
        <Route path="/hk_stock-market" element={<MarketStocks marketId="hk_stock" />} />
        <Route path="/us_stock-market" element={<MarketStocks marketId="us_stock" />} />
        <Route path="/futures-market" element={<MarketStocks marketId="futures" />} />
        <Route path="/crypto-market" element={<CryptoMarket />} />
        <Route path="*" element={<Navigate to={defaultDashboardPath} replace />} />
      </Routes>
    </Suspense>
  );
}

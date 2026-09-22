import BacktestResultsView from '@/features/strategy-backtests/components/BacktestResultsView.jsx';
import { useStrategyBacktest } from '@/features/strategy-backtests/hooks/useStrategyBacktest.js';

export default function StrategyBacktestsDashboard() {
  return <BacktestResultsView state={useStrategyBacktest()} />;
}

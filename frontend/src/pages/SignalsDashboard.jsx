import SignalsView from '@/features/signals/components/SignalsView.jsx';
import { useSignals } from '@/features/signals/hooks/useSignals.js';

export default function SignalsDashboard() {
  return <SignalsView state={useSignals()} />;
}

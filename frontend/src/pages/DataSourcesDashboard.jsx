import DataSourcesView from '@/features/data-sources/components/DataSourcesView.jsx';
import { useDataSources } from '@/features/data-sources/hooks/useDataSources.js';

export default function DataSourcesDashboard() {
  const taskState = useDataSources();
  return <DataSourcesView {...taskState} />;
}

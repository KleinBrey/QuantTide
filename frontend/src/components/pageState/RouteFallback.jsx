import { Spinner } from '@/shadcn/components/ui/spinner.jsx';
import styles from './PlaceholderDashboard.module.css';

export default function RouteFallback() {
  return (
    <section className={styles.placeholder}>
      <Spinner />
      <h2>加载页面</h2>
      <p>正在准备数据和界面</p>
    </section>
  );
}

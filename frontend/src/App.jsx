import { BrowserRouter } from 'react-router-dom';

import { ThemeProvider, TradingCalendarProvider } from '@/contexts';
import Layout from '@/layouts/Layout.jsx';
import AppRoutes from '@/routes/AppRoutes.jsx';

export default function App() {
  return (
    <ThemeProvider>
      <TradingCalendarProvider>
        <BrowserRouter>
          <Layout>
            <AppRoutes />
          </Layout>
        </BrowserRouter>
      </TradingCalendarProvider>
    </ThemeProvider>
  );
}

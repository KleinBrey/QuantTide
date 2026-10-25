import { BrowserRouter } from 'react-router-dom';

import { ThemeProvider, TradingCalendarProvider } from '@/contexts';
import Layout from '@/layouts/Layout.jsx';
import AppRoutes from '@/routes/AppRoutes.jsx';
import { Toaster } from '@/shadcn/components/ui/sonner.jsx';

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
      <Toaster position="top-right" duration={5000} richColors />
    </ThemeProvider>
  );
}

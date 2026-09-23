import { SidebarProvider, SidebarTrigger } from '@/shadcn/components/ui/sidebar';
import { AppSidebar } from './Sidebar.jsx';
import style from './Layout.module.css';

export default function Layout({ children }) {
  return (
    <SidebarProvider style={{ '--sidebar-width-icon': '4rem' }}>
      <AppSidebar />
      <section style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
        <header className={style.siteHeader}>
          <SidebarTrigger />
          <div className={style.headerTitle}>
            <div>
              <h1></h1>
            </div>
          </div>
        </header>
        <main>{children}</main>
      </section>
    </SidebarProvider>
  );
}

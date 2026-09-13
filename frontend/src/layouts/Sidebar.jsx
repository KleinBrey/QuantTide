import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader } from '@/shadcn/components/ui/sidebar';
import logoUrl from '@/assets/branding/logo.png';
import React from 'react';
import { ChartNoAxesCombined, LayoutDashboard, ChartCandlestick, DatabaseBackup, Flame, Server } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { dashboardGroups } from '../routes/RouteConfig.js';
import style from './Sidebar.module.css';

const iconById = {
  'hot-rankings': Flame,
  'strategy-signals': ChartNoAxesCombined,
  'a-share-market': ChartCandlestick,
  'hk-share-market': ChartCandlestick,
  'us-share-market': ChartCandlestick,
  'data-sources': DatabaseBackup
};

export function AppSidebar() {
  return (
    <Sidebar className="dark overflow-hidden" collapsible="icon">
      <SidebarHeader>
        <div className={style.logo}>
          <div className={style.mark}>
            <img src={logoUrl} alt="Stock Flow Logo" />
          </div>
          <div className={style.title}>
            <span>Quant Tide</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent className={style.sidebarContent}>
        <aside className={style.sidebar}>
          <nav className={style.sidebarNav} aria-label="股票看板导航">
            {dashboardGroups.map(group => (
              <section key={group.title}>
                <p>{group.title}</p>
                {group.items.map(item => {
                  const Icon = iconById[item.id] || LayoutDashboard;
                  return (
                    <NavLink
                      className={({ isActive }) => `${style.navItem}${isActive ? ` ${style.active}` : ''}`}
                      key={item.path}
                      title={`${item.title}`}
                      to={item.path}
                    >
                      <Icon size={16} />
                      <span>{item.title}</span>
                    </NavLink>
                  );
                })}
              </section>
            ))}
          </nav>
        </aside>
      </SidebarContent>
      <SidebarFooter>
        <div className={style.sidebarFooter} title="本地数据服务 127.0.0.1:8001">
          <Server size={16} />
          <span>
            本地数据服务
            <br />
            127.0.0.1:8001
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

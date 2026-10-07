import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader } from '@/shadcn/components/ui/sidebar';
import logoUrl from '@/assets/branding/logo.png';
import React from 'react';
import { Radar, LayoutDashboard, DatabaseBackup, Flame, History, Server } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { dashboardGroups } from '../routes/RouteConfig.js';
import style from './Sidebar.module.css';

function MarketIcon({ code, size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="20" height="18" rx="4" stroke="currentColor" strokeWidth="1.5" />
      <text
        x="12"
        y="12"
        dy="0.35em"
        textAnchor="middle"
        fill="currentColor"
        fontFamily="Arial, sans-serif"
        fontSize="9"
        fontWeight="700"
      >
        {code}
      </text>
    </svg>
  );
}

const AShareIcon = props => <MarketIcon {...props} code="CN" />;
const HKShareIcon = props => <MarketIcon {...props} code="HK" />;
const USShareIcon = props => <MarketIcon {...props} code="US" />;

const iconById = {
  'hot-rankings': Flame,
  signals: Radar,
  'strategy-backtests': History,
  'a-share-market': AShareIcon,
  'hk-share-market': HKShareIcon,
  'us-share-market': USShareIcon,
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

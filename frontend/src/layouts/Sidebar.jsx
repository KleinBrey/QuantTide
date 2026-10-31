import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader } from '@/shadcn/components/ui/sidebar';
import logoUrl from '@/assets/image/logo.png';
import cnStockIconUrl from '@/assets/icons/cn_stock.svg';
import hkStockIconUrl from '@/assets/icons/hk_stock.svg';
import usStockIconUrl from '@/assets/icons/us_stock.svg';
import futuresIconUrl from '@/assets/icons/futures.svg';
import cryptoIconUrl from '@/assets/icons/crypto.svg';
import React from 'react';
import { Radar, LayoutDashboard, DatabaseBackup, Flame, History } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { dashboardGroups } from '../routes/RouteConfig.js';
import { SidebarUser } from './SidebarUser.jsx';
import style from './Sidebar.module.css';

function MarketIcon({ src, size = 16 }) {
  return <img src={src} width={size} height={size} alt="" aria-hidden="true" />;
}

const CNStockIcon = props => <MarketIcon {...props} src={cnStockIconUrl} />;
const HKStockIcon = props => <MarketIcon {...props} src={hkStockIconUrl} />;
const USStockIcon = props => <MarketIcon {...props} src={usStockIconUrl} />;
const FuturesIcon = props => <MarketIcon {...props} src={futuresIconUrl} />;
const CryptoIcon = props => <MarketIcon {...props} src={cryptoIconUrl} />;

const iconById = {
  'hot-rankings': Flame,
  signals: Radar,
  'strategy-backtests': History,
  'cn_stock-market': CNStockIcon,
  'hk_stock-market': HKStockIcon,
  'us_stock-market': USStockIcon,
  'futures-market': FuturesIcon,
  'crypto-market': CryptoIcon,
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
        <SidebarUser />
      </SidebarFooter>
    </Sidebar>
  );
}

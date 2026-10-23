import { Menu } from '@base-ui/react/menu';
import { Bell, CircleUserRound, CreditCard, LogOut, MoreVertical } from 'lucide-react';
import { useSidebar } from '@/shadcn/components/ui/sidebar';
import avatarUrl from '@/assets/image/user.jpg';
import style from './SidebarUser.module.css';

// 前端展示用占位信息，菜单暂不接入账户、账单、通知或退出接口。
const user = { name: 'Klein Brey', email: 'kleinbrey@support.com' };

function UserInfo() {
  return (
    <>
      <img className={style.avatar} src={avatarUrl} alt="用户头像" />
      <span className={style.userInfo}>
        <span className={style.name}>{user.name}</span>
        <span className={style.email}>{user.email}</span>
      </span>
    </>
  );
}

export function SidebarUser() {
  const { isMobile } = useSidebar();

  return (
    <Menu.Root>
      <Menu.Trigger className={style.trigger} aria-label="用户菜单" title="用户菜单">
        <UserInfo />
        <MoreVertical size={16} className={style.moreIcon} />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side={isMobile ? 'top' : 'right'} align="end" sideOffset={8} className={style.positioner}>
          <Menu.Popup className={style.popup}>
            <div className={style.menuHeader}>
              <UserInfo />
            </div>
            <Menu.Separator className={style.separator} />
            <Menu.Item className={style.menuItem}>
              <CircleUserRound size={16} />
              账户
            </Menu.Item>
            <Menu.Item className={style.menuItem}>
              <CreditCard size={16} />
              账单
            </Menu.Item>
            <Menu.Item className={style.menuItem}>
              <Bell size={16} />
              通知
            </Menu.Item>
            <Menu.Separator className={style.separator} />
            <Menu.Item className={style.menuItem}>
              <LogOut size={16} />
              退出登录
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

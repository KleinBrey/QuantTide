export const dashboardGroups = [
  {
    title: '功能',
    items: [
      {
        id: 'hot-rankings',
        path: '/hot-rankings',
        title: '股票热度',
        description: '同花顺官方热股、飙升与涨停榜'
      },
      {
        id: 'strategy-signals',
        path: '/strategy-signals',
        title: '策略信号',
        description: 'Python 量化策略与最新选股信号'
      }
    ]
  },
  {
    title: '市场',
    items: [
      {
        id: 'a-share-market',
        path: '/a-share-market',
        title: 'A股',
        description: 'A股市场'
      },
      {
        id: 'hk-share-market',
        path: '/hk-share-market',
        title: '港股',
        description: '港股市场'
      },
      {
        id: 'us-share-market',
        path: '/us-share-market',
        title: '美股',
        description: '美股市场'
      }
    ]
  },
  {
    title: '数据',
    items: [
      {
        id: 'data-sources',
        path: '/data-sources',
        title: '数据同步',
        description: '手动执行数据库同步脚本'
      }
    ]
  }
];

export const defaultDashboardPath = '/hot-rankings';

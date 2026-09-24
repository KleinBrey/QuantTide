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
        id: 'signals',
        path: '/signals',
        title: '选股信号',
        description: 'Python 量化策略生成的最新选股信号'
      },
      {
        id: 'strategy-backtests',
        path: '/strategy-backtests',
        title: '策略回测',
        description: '策略绩效与逐笔交易记录'
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

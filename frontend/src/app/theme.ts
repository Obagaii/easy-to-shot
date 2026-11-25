import type { ThemeConfig } from 'antd';

// 视觉基线：Snow Shot（ant_design_qt）的 Ant Design 默认 Token。
// 主色 #1677FF、布局底 #f5f5f5、容器白、圆角 6、控件高 32。
// 离线桌面应用不加载网络字体，使用系统字体栈。
// antd 6 的 motionUnit 单位是秒（默认 0.1），不是毫秒；写成 100 会生成 300s 过渡，
// 导致选中态背景色几乎不变。数值与项目 120–220ms 动效约定对齐。
export function createThemeConfig(isMotionDisabled: boolean): ThemeConfig {
  return {
    token: {
      colorPrimary: '#1677ff',
      colorText: 'rgba(0, 0, 0, 0.88)',
      colorTextSecondary: 'rgba(0, 0, 0, 0.65)',
      colorTextTertiary: 'rgba(0, 0, 0, 0.45)',
      colorBorder: '#d9d9d9',
      colorBorderSecondary: '#f0f0f0',
      colorBgContainer: '#ffffff',
      colorBgLayout: '#f5f5f5',
      colorBgElevated: '#ffffff',
      colorError: '#ff4d4f',
      colorWarning: '#faad14',
      colorSuccess: '#52c41a',
      borderRadius: 6,
      borderRadiusLG: 8,
      borderRadiusSM: 4,
      fontSize: 14,
      controlHeight: 32,
      fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
      motionUnit: isMotionDisabled ? 0 : 0.1,
    },
    components: {
      Button: { fontWeight: 400, primaryShadow: 'none' },
      Menu: { itemBorderRadius: 4, itemHeight: 36, itemMarginInline: 8 },
      Card: { headerFontSize: 16 },
      Tabs: { horizontalItemPadding: '12px 0', horizontalItemGutter: 24 },
    },
  };
}

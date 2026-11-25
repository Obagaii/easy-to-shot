import type { ThemeConfig } from 'antd';

// 视觉基线见 AGENTS.md 第 6 节：配色来自 design-taste-frontend 的 devtool 分配结果。
// 离线桌面应用不加载网络字体，使用系统字体栈；antd 6 用 motionUnit 控制动效时长。
export function createThemeConfig(isMotionDisabled: boolean): ThemeConfig {
  return {
    token: {
      colorPrimary: '#2456d6',
      colorText: '#26251e',
      colorTextSecondary: '#5a5850',
      colorBorder: '#d3d2ce',
      colorBgContainer: '#f4f3f0',
      colorBgLayout: '#dfdedb',
      colorBgElevated: '#f4f3f0',
      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 4,
      fontSize: 14,
      fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
      motionUnit: isMotionDisabled ? 0 : 100,
    },
    components: {
      Button: { controlHeight: 36, fontWeight: 500 },
    },
  };
}

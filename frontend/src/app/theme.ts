import type { ThemeConfig } from 'antd';

// antd 6 用 motionUnit 控制动效时长；减少动态效果时将其置 0。
export function createThemeConfig(isMotionDisabled: boolean): ThemeConfig {
  return {
    token: {
      colorPrimary: '#1677ff',
      borderRadius: 8,
      fontSize: 14,
      motionUnit: isMotionDisabled ? 0 : 100,
    },
  };
}

import { createMockBridge } from './mock-client.ts';
import { createQtBridge, hasQtTransport } from './qt-client.ts';
import type { WorkbenchBridge } from './types.ts';

export type {
  CaptureRequest,
  HistoryItem,
  HistoryList,
  HistoryQuery,
  HotkeyState,
  SettingsDraft,
  SettingsResult,
  TaskListener,
  TaskResult,
  TaskState,
  WorkbenchBridge,
} from './types.ts';

// 开发期默认模拟；宿主提供 QWebChannel 传输时自动切换真实桥接。
export function createBridge(): WorkbenchBridge {
  if (import.meta.env.VITE_BRIDGE_MODE === 'mock') {
    return createMockBridge();
  }
  return hasQtTransport() ? createQtBridge() : createMockBridge();
}

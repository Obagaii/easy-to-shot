import type {
  CaptureRequest,
  HistoryItem,
  HistoryList,
  HistoryQuery,
  SettingsDraft,
  SettingsResult,
  TaskListener,
  TaskResult,
  WorkbenchBridge,
} from './types.ts';

// 合成可公开预览图，避免开发期依赖外部资源；内容仅作为文本传入界面。
function previewDataUrl(label: string, fill: string): string {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">' +
    `<rect width="320" height="180" fill="${fill}"/>` +
    `<text x="20" y="100" fill="#ffffff" font-size="24">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const defaultSettings: SettingsDraft = {
  hotkey: 'Ctrl+Shift+F8',
  outputDirectory: '',
  historyEnabled: true,
  maxHistoryItems: 100,
  schemaVersion: 1,
};

const mockItems: HistoryItem[] = [
  {
    historyItemId: 'h-001',
    sessionId: 's-001',
    revision: 1,
    createdAtUtc: '2026-11-22T01:12:00Z',
    source: 'capture',
    widthPx: 1920,
    heightPx: 1080,
    byteSize: 248120,
    previewUrl: previewDataUrl('截图 01', '#4a7fd4'),
  },
  {
    historyItemId: 'h-002',
    sessionId: 's-002',
    revision: 1,
    createdAtUtc: '2026-11-22T01:08:00Z',
    source: 'capture',
    widthPx: 1280,
    heightPx: 720,
    byteSize: 96480,
    previewUrl: previewDataUrl('截图 02', '#3f9e77'),
  },
  {
    historyItemId: 'h-003',
    sessionId: 's-003',
    revision: 2,
    createdAtUtc: '2026-11-21T10:41:00Z',
    source: 'pin',
    widthPx: 2560,
    heightPx: 1440,
    byteSize: 512640,
    // 保留不可达地址，用于验证缩略图失败与重试反馈。
    previewUrl: 'e2s://app/preview/h-003',
  },
];

let operationCounter = 0;

function createTaskResult(prefix: string): TaskResult {
  operationCounter += 1;
  return {
    operationId: `${prefix}-${operationCounter}`,
    state: 'succeeded',
    errorCode: null,
  };
}

// 开发期模拟实现：结构与真实 WebChannel 契约一致，联调时由 createBridge 切换。
export function createMockBridge(): WorkbenchBridge {
  let settings: SettingsDraft = { ...defaultSettings };
  let items: HistoryItem[] = mockItems.map((item) => ({ ...item }));
  const listeners = new Set<TaskListener>();

  const publish = (result: TaskResult) => {
    listeners.forEach((listener) => listener(result));
  };

  const finish = async (prefix: string): Promise<TaskResult> => {
    const result = createTaskResult(prefix);
    publish(result);
    return result;
  };

  const readSettings = (): SettingsResult => ({
    settings: { ...settings },
    hotkeyState: {
      registered: true,
      conflict: false,
      effectiveHotkey: settings.hotkey,
    },
    errorCode: null,
  });

  return {
    async startCapture(request: CaptureRequest) {
      return finish(`capture-${request.triggerSource}`);
    },
    async getSettings() {
      return readSettings();
    },
    async saveSettings(draft: SettingsDraft) {
      if (draft.maxHistoryItems < 1) {
        return { ...readSettings(), errorCode: 'invalid_max_history_items' };
      }
      // 开发期模拟：注册冲突与写入失败，供设置页反馈路径验证。
      if (draft.hotkey === 'Ctrl+Shift+F9') {
        return {
          ...readSettings(),
          hotkeyState: {
            registered: false,
            conflict: true,
            effectiveHotkey: settings.hotkey,
          },
          errorCode: 'hotkey_conflict',
        };
      }
      if (draft.outputDirectory === 'Z:\\invalid') {
        return { ...readSettings(), errorCode: 'write_failed' };
      }
      settings = { ...draft };
      return readSettings();
    },
    async resetSettings() {
      settings = { ...defaultSettings };
      return readSettings();
    },
    async listHistory(query: HistoryQuery): Promise<HistoryList> {
      const start = Math.max(0, query.offset);
      const end = start + Math.max(0, query.limit);
      return { items: items.slice(start, end).map((item) => ({ ...item })), total: items.length };
    },
    async copyHistoryItem(historyItemId: string) {
      return finish(`copy-${historyItemId}`);
    },
    async saveHistoryItemAs(historyItemId: string) {
      return finish(`save-as-${historyItemId}`);
    },
    async deleteHistoryItem(historyItemId: string) {
      const exists = items.some((item) => item.historyItemId === historyItemId);
      if (!exists) {
        return {
          operationId: `delete-${historyItemId}`,
          state: 'failed' as const,
          errorCode: 'not_found',
        };
      }
      items = items.filter((item) => item.historyItemId !== historyItemId);
      return finish(`delete-${historyItemId}`);
    },
    async clearHistory() {
      items = [];
      return finish('clear');
    },
    onTaskFinished(listener: TaskListener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

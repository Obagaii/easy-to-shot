import type {
  CaptureRequest,
  HistoryList,
  HistoryQuery,
  SettingsDraft,
  SettingsResult,
  TaskListener,
  TaskResult,
  WorkbenchBridge,
} from './types.ts';

interface QtWorkbenchApi {
  startCapture(request: CaptureRequest): Promise<TaskResult>;
  getSettings(): Promise<SettingsResult>;
  saveSettings(draft: SettingsDraft): Promise<SettingsResult>;
  resetSettings(): Promise<SettingsResult>;
  listHistory(query: HistoryQuery): Promise<HistoryList>;
  copyHistoryItem(historyItemId: string): Promise<TaskResult>;
  saveHistoryItemAs(historyItemId: string): Promise<TaskResult>;
  deleteHistoryItem(historyItemId: string): Promise<TaskResult>;
  clearHistory(): Promise<TaskResult>;
  taskFinished: {
    connect(listener: TaskListener): void;
    disconnect(listener: TaskListener): void;
  };
}

interface QtChannel {
  objects: { workbench?: QtWorkbenchApi };
}

type QWebChannelConstructor = new (
  transport: unknown,
  callback: (channel: QtChannel) => void
) => void;

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: QWebChannelConstructor;
  }
}

export function hasQtTransport(): boolean {
  return typeof window !== 'undefined'
    && Boolean(window.qt?.webChannelTransport)
    && typeof window.QWebChannel === 'function';
}

let channelPromise: Promise<QtWorkbenchApi> | null = null;
const taskListeners = new Set<TaskListener>();
let isSignalConnected = false;

function getChannel(): Promise<QtWorkbenchApi> {
  if (!channelPromise) {
    channelPromise = new Promise((resolve, reject) => {
      const Constructor = window.QWebChannel;
      const transport = window.qt?.webChannelTransport;
      if (!Constructor || !transport) {
        reject(new Error('未检测到 Qt WebChannel 传输'));
        return;
      }
      new Constructor(transport, (channel: QtChannel) => {
        const api = channel.objects.workbench;
        if (!api) {
          reject(new Error('宿主未发布工作台接口'));
          return;
        }
        resolve(api);
      });
    });
  }
  return channelPromise;
}

function connectTaskSignal(): void {
  if (isSignalConnected) return;
  isSignalConnected = true;
  void getChannel().then((api) => {
    api.taskFinished.connect((result) => {
      taskListeners.forEach((listener) => listener(result));
    });
  });
}

// 真实桥接：桌面宿主通过 QWebChannel 发布 workbench 对象与 taskFinished 信号。
export function createQtBridge(): WorkbenchBridge {
  return {
    async startCapture(request) {
      return (await getChannel()).startCapture(request);
    },
    async getSettings() {
      return (await getChannel()).getSettings();
    },
    async saveSettings(draft) {
      return (await getChannel()).saveSettings(draft);
    },
    async resetSettings() {
      return (await getChannel()).resetSettings();
    },
    async listHistory(query) {
      return (await getChannel()).listHistory(query);
    },
    async copyHistoryItem(historyItemId) {
      return (await getChannel()).copyHistoryItem(historyItemId);
    },
    async saveHistoryItemAs(historyItemId) {
      return (await getChannel()).saveHistoryItemAs(historyItemId);
    },
    async deleteHistoryItem(historyItemId) {
      return (await getChannel()).deleteHistoryItem(historyItemId);
    },
    async clearHistory() {
      return (await getChannel()).clearHistory();
    },
    onTaskFinished(listener) {
      taskListeners.add(listener);
      connectTaskSignal();
      return () => taskListeners.delete(listener);
    },
  };
}

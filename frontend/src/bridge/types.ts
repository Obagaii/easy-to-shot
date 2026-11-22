// WebChannel 对外契约：方法名与载荷统一 camelCase，状态值与错误码保持稳定。
export type TaskState = 'pending' | 'succeeded' | 'failed' | 'cancelled' | 'busy';

export interface SettingsDraft {
  hotkey: string;
  outputDirectory: string;
  historyEnabled: boolean;
  maxHistoryItems: number;
  schemaVersion: number;
}

export interface HotkeyState {
  registered: boolean;
  conflict: boolean;
  effectiveHotkey: string;
}

export interface SettingsResult {
  settings: SettingsDraft;
  hotkeyState: HotkeyState;
  errorCode: string | null;
}

export interface HistoryItem {
  historyItemId: string;
  sessionId: string;
  revision: number;
  createdAtUtc: string;
  source: string;
  widthPx: number;
  heightPx: number;
  byteSize: number;
  previewUrl: string;
}

export interface HistoryQuery {
  offset: number;
  limit: number;
}

export interface HistoryList {
  items: HistoryItem[];
  total: number;
}

export interface CaptureRequest {
  triggerSource: 'tray' | 'workbench' | 'hotkey';
}

export interface TaskResult {
  operationId: string;
  state: TaskState;
  errorCode: string | null;
}

export type TaskListener = (result: TaskResult) => void;

export interface WorkbenchBridge {
  startCapture(request: CaptureRequest): Promise<TaskResult>;
  getSettings(): Promise<SettingsResult>;
  saveSettings(draft: SettingsDraft): Promise<SettingsResult>;
  resetSettings(): Promise<SettingsResult>;
  listHistory(query: HistoryQuery): Promise<HistoryList>;
  copyHistoryItem(historyItemId: string): Promise<TaskResult>;
  saveHistoryItemAs(historyItemId: string): Promise<TaskResult>;
  deleteHistoryItem(historyItemId: string): Promise<TaskResult>;
  clearHistory(): Promise<TaskResult>;
  onTaskFinished(listener: TaskListener): () => void;
}

import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { HotkeyState, SettingsDraft, SettingsResult } from '../bridge';

interface SettingsPageProps {
  settings: SettingsDraft | null;
  hotkeyState: HotkeyState | null;
  notice: string;
  onSave: (draft: SettingsDraft) => Promise<SettingsResult>;
  onReset: () => Promise<SettingsResult>;
}

type FeedbackState = 'idle' | 'saving' | 'succeeded' | 'failed' | 'cancelled' | 'conflict';

interface Feedback {
  state: FeedbackState;
  message: string;
  errorCode: string | null;
}

const initialFeedback: Feedback = { state: 'idle', message: '', errorCode: null };
const modifierKeys = ['Ctrl', 'Alt', 'Shift'];
const namedKeys = new Set([
  'Space', 'Enter', 'Esc', 'Tab', 'Backspace', 'Delete', 'Insert',
  'Home', 'End', 'PageUp', 'PageDown', 'Up', 'Down', 'Left', 'Right',
  'PrintScreen', 'Pause',
]);
const reservedHotkeys = new Set([
  'Alt+Tab', 'Alt+Shift+Tab', 'Alt+Esc', 'Alt+F4',
  'Ctrl+Esc', 'Ctrl+Shift+Esc', 'Ctrl+Alt+Del',
]);
const errorMessages: Record<string, string> = {
  invalid_max_history_items: '历史条数需在 1 至 10000 之间。',
  invalid_draft: '草稿未通过校验。',
  hotkey_conflict: '热键已被占用，原设置仍生效。',
  write_failed: '写入失败，原设置仍生效。',
  settings_unavailable: '设置服务不可用。',
  settings_corrupt: '设置损坏，使用默认设置。',
  unexpected: '保存未完成。',
};

function isMainKey(value: string): boolean {
  if (/^F([1-9]|1[0-2])$/.test(value)) return true;
  if (/^[A-Za-z0-9]$/.test(value)) return true;
  return namedKeys.has(value);
}

function validateHotkey(value: string): string | null {
  const parts = value.split('+').map((part) => part.trim());
  if (parts.length < 2 || parts.some((part) => part.length === 0)) {
    return '热键需包含至少一个修饰键与一个主键。';
  }
  const modifiers = parts.slice(0, -1);
  const mainKey = parts[parts.length - 1];
  if (modifiers.some((part) => !modifierKeys.includes(part))) {
    return '修饰键只能是 Ctrl、Alt 或 Shift。';
  }
  if (new Set(modifiers).size !== modifiers.length) return '修饰键不能重复。';
  if (!isMainKey(mainKey)) return '主键格式不正确。';
  if (reservedHotkeys.has(value)) return '该组合为系统保留热键。';
  return null;
}

function validateDraft(draft: SettingsDraft): string | null {
  const hotkeyError = validateHotkey(draft.hotkey);
  if (hotkeyError) return hotkeyError;
  const limit = draft.maxHistoryItems;
  if (!Number.isInteger(limit) || limit < 1 || limit > 10000) {
    return '历史保留条数需为 1 至 10000 的整数。';
  }
  return null;
}

function describeResult(action: string, result: SettingsResult): Feedback {
  if (result.hotkeyState.conflict) {
    return {
      state: 'conflict',
      message: '热键已被占用，原设置仍生效。',
      errorCode: 'hotkey_conflict',
    };
  }
  if (result.errorCode === 'dialog_cancelled' || result.errorCode === 'cancelled') {
    return {
      state: 'cancelled',
      message: `${action}已取消`,
      errorCode: result.errorCode,
    };
  }
  if (result.errorCode) {
    return {
      state: 'failed',
      message: `${action}失败：${errorMessages[result.errorCode] ?? result.errorCode}`,
      errorCode: result.errorCode,
    };
  }
  return {
    state: 'succeeded',
    message: `${action}已生效`,
    errorCode: null,
  };
}

export function SettingsPage({
  settings,
  hotkeyState,
  notice,
  onSave,
  onReset,
}: SettingsPageProps) {
  const [draft, setDraft] = useState<SettingsDraft | null>(settings);
  const [feedback, setFeedback] = useState<Feedback>(initialFeedback);
  const [isResetOpen, setIsResetOpen] = useState(false);
  const busyRef = useRef(false);
  const taskTokenRef = useRef(0);
  const isMountedRef = useRef(true);
  const resetTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => setDraft(settings), [settings]);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  if (!draft) {
    return <Skeleton active paragraph={{ rows: 5 }} />;
  }

  const isDirty = settings !== null && (
    draft.hotkey !== settings.hotkey
    || draft.outputDirectory !== settings.outputDirectory
    || draft.historyEnabled !== settings.historyEnabled
    || draft.maxHistoryItems !== settings.maxHistoryItems
  );
  const isBusy = feedback.state === 'saving';
  const alertType =
    feedback.state === 'succeeded'
      ? 'success'
      : feedback.state === 'saving'
        ? 'info'
        : feedback.state === 'cancelled'
          ? 'warning'
          : 'error';

  const runTask = async (action: string, call: () => Promise<SettingsResult>) => {
    if (busyRef.current) return;
    const invalid = validateDraft(draft);
    if (invalid) {
      setFeedback({
        state: 'failed',
        message: `校验失败：${invalid}`,
        errorCode: 'invalid_draft',
      });
      return;
    }
    busyRef.current = true;
    const token = ++taskTokenRef.current;
    setFeedback({ state: 'saving', message: `${action}中`, errorCode: null });
    try {
      const result = await call();
      if (!isMountedRef.current || token !== taskTokenRef.current) return;
      const next = describeResult(action, result);
      setFeedback(next);
      if (next.state === 'succeeded') setDraft(result.settings);
    } catch {
      if (isMountedRef.current && token === taskTokenRef.current) {
        setFeedback({
          state: 'failed',
          message: `${action}失败：保存未完成。`,
          errorCode: 'unexpected',
        });
      }
    } finally {
      busyRef.current = false;
    }
  };

  const updateDraft = (patch: Partial<SettingsDraft>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setFeedback(initialFeedback);
  };

  return (
    <div className="settings-page">
      {notice && (
        <Alert className="settings-feedback" type="warning" showIcon message={notice} />
      )}
      <div className="settings-toolbar">
        <Tag color={isDirty ? 'gold' : 'default'}>{isDirty ? '未保存' : '已保存'}</Tag>
        <Typography.Text type="secondary">配置版本 {draft.schemaVersion}</Typography.Text>
      </div>

      {feedback.state !== 'idle' && (
        <Alert
          className="settings-feedback"
          type={alertType}
          showIcon
          message={feedback.message}
        />
      )}

      <Form layout="vertical" className="settings-form">
        <Form.Item
          label="截图热键"
          extra="例如 Ctrl+Shift+F8"
        >
          <Input
            value={draft.hotkey}
            disabled={isBusy}
            onChange={(event) => updateDraft({ hotkey: event.target.value })}
          />
        </Form.Item>

        <Form.Item label="实际热键状态">
          {hotkeyState ? (
            <Space direction="vertical" size="small">
              <Space>
                <Tag
                  color={
                    hotkeyState.conflict
                      ? 'error'
                      : hotkeyState.registered
                        ? 'success'
                        : 'warning'
                  }
                >
                  {hotkeyState.conflict
                    ? '注册冲突'
                    : hotkeyState.registered
                      ? '已注册'
                      : '未注册'}
                </Tag>
                <Typography.Text type="secondary">
                  实际生效：{hotkeyState.effectiveHotkey}
                </Typography.Text>
              </Space>
              {hotkeyState.conflict && (
                <Typography.Text type="danger">
                  草稿 {draft.hotkey} 未生效
                </Typography.Text>
              )}
            </Space>
          ) : (
            <Typography.Text type="secondary">读取中</Typography.Text>
          )}
        </Form.Item>

        <Form.Item
          label="默认输出目录"
          extra="留空则使用系统图片目录"
        >
          <Input
            value={draft.outputDirectory}
            disabled={isBusy}
            placeholder="例如 D:\\图片"
            onChange={(event) => updateDraft({ outputDirectory: event.target.value })}
          />
        </Form.Item>

        <Form.Item label="启用历史记录" extra="关闭后不再写入历史">
          <Switch
            checked={draft.historyEnabled}
            disabled={isBusy}
            onChange={(checked) => updateDraft({ historyEnabled: checked })}
          />
        </Form.Item>

        <Form.Item label="历史保留条数">
          <InputNumber
            min={1}
            max={10000}
            value={draft.maxHistoryItems}
            disabled={isBusy}
            onChange={(value) => updateDraft({ maxHistoryItems: value ?? 100 })}
          />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button
              type="primary"
              loading={isBusy}
              disabled={isBusy}
              onClick={() => void runTask('保存', () => onSave(draft))}
            >
              保存
            </Button>
            <Button
              disabled={isBusy}
              onClick={(event) => {
                resetTriggerRef.current = event.currentTarget;
                setIsResetOpen(true);
              }}
            >
              恢复默认
            </Button>
          </Space>
        </Form.Item>
      </Form>

      <Modal
        title="恢复默认设置？"
        open={isResetOpen}
        okText="恢复默认"
        cancelText="取消"
        okButtonProps={{ disabled: isBusy }}
        onOk={() => {
          setIsResetOpen(false);
          void runTask('恢复默认', onReset);
        }}
        onCancel={() => setIsResetOpen(false)}
        afterClose={() => resetTriggerRef.current?.focus()}
      >
        草稿会被默认值替换。
      </Modal>
    </div>
  );
}

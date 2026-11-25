import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { HotkeyState, SettingsDraft, SettingsResult } from '../bridge';

interface SettingsPageProps {
  settings: SettingsDraft | null;
  hotkeyState: HotkeyState | null;
  notice: string;
  query: string;
  onSave: (draft: SettingsDraft) => Promise<SettingsResult>;
  onReset: () => Promise<SettingsResult>;
}

type FeedbackState = 'idle' | 'saving' | 'succeeded' | 'failed' | 'cancelled' | 'conflict';
type SectionKey = 'capture' | 'storage' | 'about';

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

interface SettingsRowProps {
  label: string;
  description?: string;
  children: ReactNode;
}

function SettingsRow({ label, description, children }: SettingsRowProps) {
  return (
    <div className="settings-row">
      <div className="settings-row-text">
        <div className="settings-row-label">{label}</div>
        {description && <div className="settings-row-desc">{description}</div>}
      </div>
      <div className="settings-row-control">{children}</div>
    </div>
  );
}

export function SettingsPage({
  settings,
  hotkeyState,
  notice,
  query,
  onSave,
  onReset,
}: SettingsPageProps) {
  const [draft, setDraft] = useState<SettingsDraft | null>(settings);
  const [feedback, setFeedback] = useState<Feedback>(initialFeedback);
  const [activeSection, setActiveSection] = useState<SectionKey>('capture');
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

  const normalizedQuery = query.trim().toLowerCase();
  const matches = useMemo(
    () => (...texts: string[]) =>
      !normalizedQuery || texts.join(' ').toLowerCase().includes(normalizedQuery),
    [normalizedQuery]
  );

  useEffect(() => {
    if (!normalizedQuery) return;
    if (matches('截图热键', '热键状态', '截图')) setActiveSection('capture');
    else if (matches('输出目录', '历史记录', '历史保留条数', '存储')) setActiveSection('storage');
    else if (matches('关于', '配置版本', '本地数据')) setActiveSection('about');
  }, [normalizedQuery, matches]);

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

  const openResetConfirm = (trigger: HTMLElement) => {
    resetTriggerRef.current = trigger;
    setIsResetOpen(true);
  };

  const sectionHeader = (title: string, description: string) => (
    <div className="settings-section-head">
      <div>
        <Typography.Title level={5} className="settings-section-title">
          {title}
        </Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      <Tooltip title="恢复默认设置">
        <Button
          type="text"
          icon={<ReloadOutlined />}
          aria-label={`恢复${title}的默认设置`}
          disabled={isBusy}
          onClick={(event) => openResetConfirm(event.currentTarget)}
        />
      </Tooltip>
    </div>
  );

  const captureSection = (
    <div className="settings-section">
      {sectionHeader('截图', '设置触发截图的方式与热键注册结果。')}
      <div className="settings-rows">
        {matches('截图热键', '例如 Ctrl+Shift+F8', '截图') && (
          <SettingsRow label="截图热键" description="例如 Ctrl+Shift+F8">
            <Input
              value={draft.hotkey}
              disabled={isBusy}
              onChange={(event) => updateDraft({ hotkey: event.target.value })}
            />
          </SettingsRow>
        )}
        {matches('实际热键状态', '来自系统注册结果', '截图') && (
          <SettingsRow label="实际热键状态" description="来自系统注册结果">
            {hotkeyState ? (
              <Space direction="vertical" size={4}>
                <Space size="small">
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
                    {hotkeyState.effectiveHotkey}
                  </Typography.Text>
                </Space>
                {hotkeyState.conflict && (
                  <Typography.Text type="danger" className="settings-row-note">
                    草稿 {draft.hotkey} 未生效
                  </Typography.Text>
                )}
              </Space>
            ) : (
              <Typography.Text type="secondary">读取中</Typography.Text>
            )}
          </SettingsRow>
        )}
      </div>
    </div>
  );

  const storageSection = (
    <div className="settings-section">
      {sectionHeader('历史与存储', '管理输出目录与本地历史记录。')}
      <div className="settings-rows">
        {matches('默认输出目录', '留空则使用系统图片目录', '存储') && (
          <SettingsRow label="默认输出目录" description="留空则使用系统图片目录">
            <Input
              value={draft.outputDirectory}
              disabled={isBusy}
              placeholder="例如 D:\\图片"
              onChange={(event) => updateDraft({ outputDirectory: event.target.value })}
            />
          </SettingsRow>
        )}
        {matches('启用历史记录', '关闭后不再写入历史', '存储') && (
          <SettingsRow label="启用历史记录" description="关闭后不再写入历史">
            <Switch
              checked={draft.historyEnabled}
              disabled={isBusy}
              onChange={(checked) => updateDraft({ historyEnabled: checked })}
            />
          </SettingsRow>
        )}
        {matches('历史保留条数', '1 至 10000', '存储') && (
          <SettingsRow label="历史保留条数" description="1 至 10000">
            <InputNumber
              min={1}
              max={10000}
              value={draft.maxHistoryItems}
              disabled={isBusy}
              onChange={(value) => updateDraft({ maxHistoryItems: value ?? 100 })}
            />
          </SettingsRow>
        )}
      </div>
    </div>
  );

  const aboutSection = (
    <div className="settings-section">
      {sectionHeader('关于', '本地版本与数据存储说明。')}
      <div className="settings-rows">
        {matches('配置版本', '本地存储结构版本', '关于') && (
          <SettingsRow label="配置版本" description="本地存储结构版本">
            <Typography.Text>v{draft.schemaVersion}</Typography.Text>
          </SettingsRow>
        )}
        {matches('本地数据', '设置与历史保存在本机', '关于') && (
          <SettingsRow label="本地数据" description="设置与历史保存在本机">
            <Typography.Text type="secondary">不上传</Typography.Text>
          </SettingsRow>
        )}
      </div>
    </div>
  );

  return (
    <div className="settings-page">
      {notice && (
        <Alert className="settings-feedback" type="warning" showIcon message={notice} />
      )}
      {feedback.state !== 'idle' && (
        <Alert
          className="settings-feedback"
          type={alertType}
          showIcon
          message={feedback.message}
        />
      )}

      <Tabs
        className="settings-tabs"
        activeKey={activeSection}
        onChange={(key) => setActiveSection(key as SectionKey)}
        items={[
          { key: 'capture', label: '截图', children: captureSection },
          { key: 'storage', label: '历史与存储', children: storageSection },
          { key: 'about', label: '关于', children: aboutSection },
        ]}
      />

      <div className="settings-footer">
        <Space size="small" wrap>
          <Tag color={isDirty ? 'gold' : 'default'}>{isDirty ? '未保存' : '已保存'}</Tag>
          <Typography.Text type="secondary">配置版本 {draft.schemaVersion}</Typography.Text>
        </Space>
        <Space size="small">
          <Button
            disabled={isBusy}
            onClick={(event) => openResetConfirm(event.currentTarget)}
          >
            恢复默认
          </Button>
          <Button
            type="primary"
            loading={isBusy}
            disabled={isBusy}
            onClick={() => void runTask('保存', () => onSave(draft))}
          >
            保存设置
          </Button>
        </Space>
      </div>

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

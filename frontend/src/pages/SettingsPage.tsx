import { Alert, Button, Form, Input, InputNumber, Space, Switch, Tag } from 'antd';
import { useEffect, useState } from 'react';
import type { HotkeyState, SettingsDraft } from '../bridge';

interface SettingsPageProps {
  settings: SettingsDraft | null;
  hotkeyState: HotkeyState | null;
  onSave: (draft: SettingsDraft) => void;
  onReset: () => void;
}

export function SettingsPage({ settings, hotkeyState, onSave, onReset }: SettingsPageProps) {
  const [draft, setDraft] = useState<SettingsDraft | null>(settings);
  const [status, setStatus] = useState('');

  useEffect(() => setDraft(settings), [settings]);

  if (!draft) {
    return <Alert type="info" showIcon message="正在读取设置…" />;
  }

  const handleSave = () => {
    onSave(draft);
    setStatus('已提交设置草稿，等待实际状态回写。');
  };

  const handleReset = () => {
    onReset();
    setStatus('已请求恢复默认设置。');
  };

  return (
    <div className="settings-page">
      <Form layout="vertical" className="settings-form">
        <Form.Item label="截图热键">
          <Input
            value={draft.hotkey}
            onChange={(event) => setDraft({ ...draft, hotkey: event.target.value })}
          />
        </Form.Item>
        <Form.Item label="实际热键状态">
          {hotkeyState && (
            <Tag color={hotkeyState.conflict ? 'error' : 'success'}>
              {hotkeyState.conflict ? '注册冲突' : '已注册'} · {hotkeyState.effectiveHotkey}
            </Tag>
          )}
        </Form.Item>
        <Form.Item label="默认输出目录">
          <Input
            value={draft.outputDirectory}
            placeholder="未设置时使用系统图片目录"
            onChange={(event) => setDraft({ ...draft, outputDirectory: event.target.value })}
          />
        </Form.Item>
        <Form.Item label="启用历史记录">
          <Switch
            checked={draft.historyEnabled}
            onChange={(checked) => setDraft({ ...draft, historyEnabled: checked })}
          />
        </Form.Item>
        <Form.Item label="历史保留条数">
          <InputNumber
            min={1}
            max={10000}
            value={draft.maxHistoryItems}
            onChange={(value) => setDraft({ ...draft, maxHistoryItems: value ?? 100 })}
          />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" onClick={handleSave}>保存</Button>
            <Button onClick={handleReset}>恢复默认</Button>
          </Space>
        </Form.Item>
      </Form>
      {status && <Alert type="info" showIcon message={status} />}
    </div>
  );
}

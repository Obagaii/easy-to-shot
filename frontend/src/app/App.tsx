import { PictureOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import { Button, ConfigProvider, Layout, Menu } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useEffect, useMemo, useState } from 'react';
import { createBridge } from '../bridge';
import type {
  HistoryItem,
  HistoryList,
  HotkeyState,
  SettingsDraft,
  SettingsResult,
  TaskResult,
} from '../bridge';
import { createThemeConfig } from './theme';
import { useReducedMotion } from './useReducedMotion';
import { HistoryPage } from '../pages/HistoryPage';
import { SettingsPage } from '../pages/SettingsPage';

type PageKey = 'history' | 'settings';

const defaultSettings: SettingsDraft = {
  hotkey: 'Ctrl+Shift+F8',
  outputDirectory: '',
  historyEnabled: true,
  maxHistoryItems: 100,
  schemaVersion: 1,
};

const defaultHotkeyState: HotkeyState = {
  registered: false,
  conflict: false,
  effectiveHotkey: defaultSettings.hotkey,
};

function fallbackResult(): SettingsResult {
  return {
    settings: { ...defaultSettings },
    hotkeyState: { ...defaultHotkeyState },
    errorCode: null,
  };
}

function currentOrFallback(
  currentSettings: SettingsResult | null,
  currentHotkeyState: HotkeyState | null
): SettingsResult {
  return {
    settings: currentSettings?.settings ?? { ...defaultSettings },
    hotkeyState: currentHotkeyState ?? { ...defaultHotkeyState },
    errorCode: 'settings_unavailable',
  };
}

function noticeFor(draft: SettingsDraft): string {
  return draft.outputDirectory ? '' : '输出目录未设置，将使用系统图片目录。';
}

export function App() {
  const [activePage, setActivePage] = useState<PageKey>('history');
  const [settings, setSettings] = useState<SettingsResult | null>(null);
  const [hotkeyState, setHotkeyState] = useState<HotkeyState | null>(null);
  const [settingsNotice, setSettingsNotice] = useState('');
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const isMotionDisabled = useReducedMotion();
  const bridge = useMemo(() => createBridge(), []);

  useEffect(() => {
    let isActive = true;
    void (async () => {
      let result: SettingsResult;
      let list: HistoryList;
      try {
        result = await bridge.getSettings();
        list = await bridge.listHistory({ offset: 0, limit: 100 });
      } catch {
        if (!isActive) return;
        setSettings(fallbackResult());
        setHotkeyState({ ...defaultHotkeyState });
        setHistoryItems([]);
        setSettingsNotice('读取失败，使用默认设置。');
        setIsLoading(false);
        return;
      }
      if (!isActive) return;
      const isCorrupt = result.errorCode === 'settings_corrupt';
      const effective = isCorrupt ? fallbackResult() : result;
      setSettings(effective);
      setHotkeyState(effective.hotkeyState);
      setHistoryItems(list.items);
      setIsLoading(false);
      setSettingsNotice(
        isCorrupt ? '设置损坏，使用默认设置。' : noticeFor(effective.settings)
      );
    })();
    return () => {
      isActive = false;
    };
  }, [bridge]);

  const handleSaveSettings = async (draft: SettingsDraft): Promise<SettingsResult> => {
    try {
      const result = await bridge.saveSettings(draft);
      setHotkeyState(result.hotkeyState);
      if (!result.errorCode) {
        setSettings(result);
        setSettingsNotice(noticeFor(result.settings));
      }
      return result;
    } catch {
      return currentOrFallback(settings, hotkeyState);
    }
  };

  const handleResetSettings = async (): Promise<SettingsResult> => {
    try {
      const result = await bridge.resetSettings();
      setHotkeyState(result.hotkeyState);
      if (!result.errorCode) {
        setSettings(result);
        setSettingsNotice(noticeFor(result.settings));
      }
      return result;
    } catch {
      return currentOrFallback(settings, hotkeyState);
    }
  };

  const handleDelete = async (historyItemId: string): Promise<TaskResult> => {
    const result = await bridge.deleteHistoryItem(historyItemId);
    if (result.state === 'succeeded') {
      const list = await bridge.listHistory({ offset: 0, limit: 100 });
      setHistoryItems(list.items);
    }
    return result;
  };

  const handleClear = async (): Promise<TaskResult> => {
    const result = await bridge.clearHistory();
    if (result.state === 'succeeded') setHistoryItems([]);
    return result;
  };

  return (
    <ConfigProvider locale={zhCN} theme={createThemeConfig(isMotionDisabled)}>
      <Layout className="workbench">
        <Layout.Sider width={200} className="workbench-sider">
          <div className="workbench-brand">Easy to Shot</div>
          <Menu
            mode="inline"
            selectedKeys={[activePage]}
            items={[
              { key: 'history', icon: <PictureOutlined />, label: '历史' },
              { key: 'settings', icon: <SettingOutlined />, label: '设置' },
            ]}
            onClick={({ key }) => setActivePage(key as PageKey)}
          />
        </Layout.Sider>
        <Layout.Content className="workbench-content">
          <header className="workbench-header">
            <h1 className="workbench-title">
              {activePage === 'history' ? '历史' : '设置'}
            </h1>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => void bridge.startCapture({ triggerSource: 'workbench' })}
            >
              新建截图
            </Button>
          </header>
          {activePage === 'history' ? (
            <HistoryPage
              items={historyItems}
              isLoading={isLoading}
              onCopy={(id) => bridge.copyHistoryItem(id)}
              onSaveAs={(id) => bridge.saveHistoryItemAs(id)}
              onDelete={handleDelete}
              onClear={handleClear}
            />
          ) : (
            <SettingsPage
              settings={settings?.settings ?? null}
              hotkeyState={hotkeyState}
              notice={settingsNotice}
              onSave={handleSaveSettings}
              onReset={handleResetSettings}
            />
          )}
        </Layout.Content>
      </Layout>
    </ConfigProvider>
  );
}

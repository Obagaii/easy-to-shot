import {
  CameraFilled,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  Button,
  Card,
  ConfigProvider,
  Input,
  Layout,
  Menu,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
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

const pageMeta: Record<PageKey, { eyebrow: string; title: string; subtitle: string }> = {
  history: {
    eyebrow: '工作台 · WORKSPACE',
    title: '截图历史',
    subtitle: '查看截取的画面、复制结果或另存到本地。',
  },
  settings: {
    eyebrow: '工作台 · WORKSPACE',
    title: '设置',
    subtitle: '调整截图热键、输出目录与历史记录。',
  },
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
  const [isSiderCollapsed, setIsSiderCollapsed] = useState(false);
  const [query, setQuery] = useState('');
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

  const meta = pageMeta[activePage];

  return (
    <ConfigProvider locale={zhCN} theme={createThemeConfig(isMotionDisabled)}>
      <Layout className="workbench">
        <Layout.Sider
          className="workbench-sider"
          width={220}
          collapsedWidth={80}
          collapsible
          collapsed={isSiderCollapsed}
          trigger={null}
        >
          <div className="workbench-sider-inner">
            <div className="workbench-brand">
              <span className="workbench-brand-mark" aria-hidden="true">
                <CameraFilled />
              </span>
              {!isSiderCollapsed && (
                <span className="workbench-brand-name">Easy to Shot</span>
              )}
            </div>

            <div
              className={
                isSiderCollapsed
                  ? 'workbench-search workbench-search-collapsed'
                  : 'workbench-search'
              }
            >
              {isSiderCollapsed ? (
                <Tooltip title="展开侧栏搜索" placement="right">
                  <Button
                    type="text"
                    icon={<SearchOutlined />}
                    aria-label="展开侧栏搜索"
                    onClick={() => setIsSiderCollapsed(false)}
                  />
                </Tooltip>
              ) : (
                <Input
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder="搜索当前页面"
                  aria-label="搜索当前页面"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              )}
            </div>

            <Menu
              className="workbench-menu"
              mode="inline"
              selectedKeys={[activePage]}
              items={[
                {
                  type: 'group',
                  label: '工作台',
                  children: [
                    {
                      key: 'history',
                      icon: <HistoryOutlined />,
                      label: '截图历史',
                    },
                    {
                      key: 'settings',
                      icon: <SettingOutlined />,
                      label: '设置',
                    },
                  ],
                },
              ]}
              onClick={({ key }) => setActivePage(key as PageKey)}
            />

            <div className="workbench-sider-footer">
              <Button
                type="text"
                icon={isSiderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                aria-label={isSiderCollapsed ? '展开侧栏' : '折叠侧栏'}
                onClick={() => setIsSiderCollapsed((value) => !value)}
              />
              {!isSiderCollapsed && (
                <Typography.Text type="secondary" className="workbench-sider-version">
                  v1.0 · 本地版
                </Typography.Text>
              )}
            </div>
          </div>
        </Layout.Sider>

        <Layout.Content className="workbench-main">
          <header className="workbench-topbar">
            <div className="workbench-topbar-heading">
              <div className="workbench-eyebrow">{meta.eyebrow}</div>
              <h1 className="workbench-title">{meta.title}</h1>
              <Typography.Text type="secondary" className="workbench-subtitle">
                {meta.subtitle}
              </Typography.Text>
            </div>
            <Space size="small">
              <Tag className="workbench-local-tag">离线运行</Tag>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => void bridge.startCapture({ triggerSource: 'workbench' })}
              >
                新建截图
              </Button>
            </Space>
          </header>

          <Card className="workbench-content-card" variant="borderless">
            {activePage === 'history' ? (
              <HistoryPage
                items={historyItems}
                isLoading={isLoading}
                query={query}
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
                query={query}
                onSave={handleSaveSettings}
                onReset={handleResetSettings}
              />
            )}
          </Card>
        </Layout.Content>
      </Layout>
    </ConfigProvider>
  );
}

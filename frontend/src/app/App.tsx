import { Alert, Button, ConfigProvider, Layout, Menu, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useEffect, useMemo, useState } from 'react';
import { createBridge } from '../bridge';
import type { HistoryItem, SettingsDraft, SettingsResult } from '../bridge';
import { createThemeConfig } from './theme';
import { useReducedMotion } from './useReducedMotion';
import { HistoryPage } from '../pages/HistoryPage';
import { SettingsPage } from '../pages/SettingsPage';

type PageKey = 'history' | 'settings';

export function App() {
  const [activePage, setActivePage] = useState<PageKey>('history');
  const [settings, setSettings] = useState<SettingsResult | null>(null);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [taskMessage, setTaskMessage] = useState('');
  const isMotionDisabled = useReducedMotion();
  const bridge = useMemo(() => createBridge(), []);

  useEffect(() => {
    let isActive = true;
    void (async () => {
      const result = await bridge.getSettings();
      const list = await bridge.listHistory({ offset: 0, limit: 100 });
      if (!isActive) return;
      setSettings(result);
      setHistoryItems(list.items);
      setIsLoading(false);
    })();
    const unsubscribe = bridge.onTaskFinished((result) => {
      if (isActive) setTaskMessage(`任务 ${result.operationId}：${result.state}`);
    });
    return () => {
      isActive = false;
      unsubscribe();
    };
  }, [bridge]);

  const handleSaveSettings = (draft: SettingsDraft) => {
    void bridge.saveSettings(draft).then(setSettings);
  };

  const handleResetSettings = () => {
    void bridge.resetSettings().then(setSettings);
  };

  const handleDelete = (historyItemId: string) => {
    void bridge.deleteHistoryItem(historyItemId).then(() =>
      bridge.listHistory({ offset: 0, limit: 100 }).then((list) => setHistoryItems(list.items))
    );
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
              { key: 'history', label: '历史' },
              { key: 'settings', label: '设置' },
            ]}
            onClick={({ key }) => setActivePage(key as PageKey)}
          />
        </Layout.Sider>
        <Layout.Content className="workbench-content">
          <header className="workbench-header">
            <Typography.Title level={4}>
              {activePage === 'history' ? '历史' : '设置'}
            </Typography.Title>
            <Button
              type="primary"
              onClick={() => void bridge.startCapture({ triggerSource: 'workbench' })}
            >
              新建截图
            </Button>
          </header>
          {taskMessage && <Alert type="info" showIcon message={taskMessage} />}
          {activePage === 'history' ? (
            <HistoryPage
              items={historyItems}
              isLoading={isLoading}
              onCopy={(id) => void bridge.copyHistoryItem(id)}
              onSaveAs={(id) => void bridge.saveHistoryItemAs(id)}
              onDelete={handleDelete}
            />
          ) : (
            <SettingsPage
              settings={settings?.settings ?? null}
              hotkeyState={settings?.hotkeyState ?? null}
              onSave={handleSaveSettings}
              onReset={handleResetSettings}
            />
          )}
        </Layout.Content>
      </Layout>
    </ConfigProvider>
  );
}

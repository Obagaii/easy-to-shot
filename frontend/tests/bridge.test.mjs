import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMockBridge } from '../src/bridge/mock-client.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const typesSource = fs.readFileSync(path.join(here, '../src/bridge/types.ts'), 'utf8');

test('WebChannel 契约字段使用 camelCase，任务状态值稳定', () => {
  for (const field of ['operationId', 'historyItemId', 'widthPx', 'schemaVersion']) {
    assert.match(typesSource, new RegExp(`\\b${field}\\b`));
  }
  for (const state of ['pending', 'succeeded', 'failed', 'cancelled', 'busy']) {
    assert.match(typesSource, new RegExp(`'${state}'`));
  }
});

test('读取设置返回草稿与实际热键状态', async () => {
  const bridge = createMockBridge();
  const result = await bridge.getSettings();
  assert.equal(result.settings.schemaVersion, 1);
  assert.equal(result.settings.maxHistoryItems, 100);
  assert.equal(result.hotkeyState.registered, true);
  assert.equal(result.errorCode, null);
});

test('保存设置回写草稿，非法条数返回错误码而非写入', async () => {
  const bridge = createMockBridge();
  const current = await bridge.getSettings();
  const invalid = { ...current.settings, maxHistoryItems: 0 };
  assert.equal((await bridge.saveSettings(invalid)).errorCode, 'invalid_max_history_items');
  const updated = { ...current.settings, maxHistoryItems: 50 };
  const result = await bridge.saveSettings(updated);
  assert.equal(result.settings.maxHistoryItems, 50);
});

test('恢复默认设置清除上一次草稿', async () => {
  const bridge = createMockBridge();
  const current = await bridge.getSettings();
  await bridge.saveSettings({ ...current.settings, maxHistoryItems: 7 });
  const reset = await bridge.resetSettings();
  assert.equal(reset.settings.maxHistoryItems, 100);
});

test('历史查询按 offset 与 limit 分页并返回总数', async () => {
  const bridge = createMockBridge();
  const all = await bridge.listHistory({ offset: 0, limit: 100 });
  assert.equal(all.total, 3);
  assert.equal(all.items.length, 3);
  const page = await bridge.listHistory({ offset: 1, limit: 1 });
  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].historyItemId, 'h-002');
  assert.equal(page.total, 3);
});

test('删除不存在的记录返回失败状态且不改动列表', async () => {
  const bridge = createMockBridge();
  const result = await bridge.deleteHistoryItem('missing');
  assert.equal(result.state, 'failed');
  assert.equal(result.errorCode, 'not_found');
  assert.equal((await bridge.listHistory({ offset: 0, limit: 100 })).total, 3);
});

test('删除成功后列表更新，清空后为空', async () => {
  const bridge = createMockBridge();
  const result = await bridge.deleteHistoryItem('h-001');
  assert.equal(result.state, 'succeeded');
  assert.equal((await bridge.listHistory({ offset: 0, limit: 100 })).total, 2);
  await bridge.clearHistory();
  assert.equal((await bridge.listHistory({ offset: 0, limit: 100 })).total, 0);
});

test('任务结果按操作 ID 通知订阅者，取消订阅后不再收到', async () => {
  const bridge = createMockBridge();
  const received = [];
  const unsubscribe = bridge.onTaskFinished((result) => received.push(result.operationId));
  await bridge.startCapture({ triggerSource: 'workbench' });
  await bridge.copyHistoryItem('h-001');
  unsubscribe();
  await bridge.clearHistory();
  assert.equal(received.length, 2);
  assert.match(received[0], /^capture-workbench-/);
  assert.match(received[1], /^copy-h-001-/);
});

test('静态构建产物包含本地应用入口', () => {
  const html = fs.readFileSync(path.join(here, '../dist/index.html'), 'utf8');
  assert.match(html, /<div id="root"><\/div>/);
  assert.match(html, /lang="zh-CN"/);
});

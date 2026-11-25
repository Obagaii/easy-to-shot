import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Modal,
  Pagination,
  Skeleton,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { HistoryItem, TaskResult } from '../bridge';

interface HistoryPageProps {
  items: HistoryItem[];
  isLoading: boolean;
  query: string;
  onCopy: (historyItemId: string) => Promise<TaskResult>;
  onSaveAs: (historyItemId: string) => Promise<TaskResult>;
  onDelete: (historyItemId: string) => Promise<TaskResult>;
  onClear: () => Promise<TaskResult>;
}

type PreviewState = 'loading' | 'loaded' | 'failed';
type FeedbackState = 'idle' | 'busy' | 'succeeded' | 'failed' | 'cancelled';

interface TaskFeedback {
  state: FeedbackState;
  action: string;
  operationId: string | null;
  errorCode: string | null;
}

const idleFeedback: TaskFeedback = {
  state: 'idle',
  action: '',
  operationId: null,
  errorCode: null,
};

const sourceLabels: Record<string, string> = {
  capture: '截图',
  copy: '复制',
  save: '保存',
  pin: '贴图',
};

const errorMessages: Record<string, string> = {
  not_found: '记录不存在。',
  clipboard_write_failed: '剪贴板写入失败。',
  directory_not_writable: '输出目录不可写。',
  queue_full: '任务队列已满。',
};

const pageSize = 8;

function sourceLabel(source: string): string {
  return sourceLabels[source] ?? source;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}

function feedbackMessage(feedback: TaskFeedback): string {
  if (feedback.state === 'busy') return `${feedback.action}中`;
  if (feedback.state === 'succeeded') return `${feedback.action}完成`;
  if (feedback.state === 'cancelled') return `${feedback.action}已取消`;
  const detail = feedback.errorCode
    ? errorMessages[feedback.errorCode] ?? feedback.errorCode
    : '未完成';
  return `${feedback.action}失败：${detail}`;
}

interface PreviewImageProps {
  item: HistoryItem;
  variant: 'thumb' | 'full';
}

function PreviewImage({ item, variant }: PreviewImageProps) {
  const [state, setState] = useState<PreviewState>(
    item.previewUrl ? 'loading' : 'failed'
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setState(item.previewUrl ? 'loading' : 'failed');
    setAttempt(0);
  }, [item.historyItemId, item.previewUrl]);

  if (state === 'failed') {
    return (
      <div className={`preview-fallback preview-fallback-${variant}`} role="status">
        <span>预览不可用</span>
        <Button
          size="small"
          onClick={() => {
            setAttempt((count) => count + 1);
            setState('loading');
          }}
        >
          重试
        </Button>
      </div>
    );
  }

  return (
    <div className={`preview-frame preview-frame-${variant}`}>
      {state === 'loading' && <Spin size="small" />}
      <img
        key={`${item.historyItemId}-${attempt}`}
        className={`preview-image preview-image-${variant} ${
          state === 'loaded' ? 'is-visible' : ''
        }`}
        src={item.previewUrl}
        alt={`历史记录 ${item.historyItemId} 的预览`}
        loading="lazy"
        onLoad={() => setState('loaded')}
        onError={() => setState('failed')}
      />
    </div>
  );
}

export function HistoryPage({
  items,
  isLoading,
  query,
  onCopy,
  onSaveAs,
  onDelete,
  onClear,
}: HistoryPageProps) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [confirmItemId, setConfirmItemId] = useState<string | null>(null);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [isClearConfirmOpen, setIsClearConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<TaskFeedback>(idleFeedback);
  const [currentPage, setCurrentPage] = useState(1);
  const triggerRef = useRef<HTMLElement | null>(null);
  const pageRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const taskTokenRef = useRef(0);
  const isMountedRef = useRef(true);
  const selectedItem = items.find((item) => item.historyItemId === selectedItemId) ?? null;

  const normalizedQuery = query.trim().toLowerCase();
  const filteredItems = useMemo(
    () =>
      items.filter((item) => {
        if (!normalizedQuery) return true;
        const haystack = [
          formatTimestamp(item.createdAtUtc),
          sourceLabel(item.source),
          item.historyItemId,
          item.sessionId,
          `${item.widthPx} × ${item.heightPx}`,
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(normalizedQuery);
      }),
    [items, normalizedQuery]
  );
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const visibleItems = filteredItems.slice(
    (Math.min(currentPage, pageCount) - 1) * pageSize,
    Math.min(currentPage, pageCount) * pageSize
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => setCurrentPage(1), [normalizedQuery]);

  const openPreview = (historyItemId: string, trigger: HTMLElement) => {
    triggerRef.current = trigger;
    setSelectedItemId(historyItemId);
  };

  const closePreview = () => setSelectedItemId(null);

  const restoreFocus = (isOpen: boolean) => {
    if (isOpen) return;
    (triggerRef.current ?? pageRef.current)?.focus();
  };

  const runTask = async (action: string, call: () => Promise<TaskResult>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const token = ++taskTokenRef.current;
    setFeedback({ state: 'busy', action, operationId: null, errorCode: null });
    try {
      const result = await call();
      if (!isMountedRef.current || token !== taskTokenRef.current) return;
      const state: FeedbackState =
        result.state === 'succeeded' || result.state === 'cancelled'
          ? result.state
          : 'failed';
      setFeedback({
        state,
        action,
        operationId: result.operationId,
        errorCode: result.errorCode,
      });
      if (state === 'succeeded' && (action === '删除' || action === '清空')) {
        setIsConfirmOpen(false);
        setIsClearConfirmOpen(false);
        setConfirmItemId(null);
        closePreview();
        triggerRef.current = null;
      }
    } catch {
      if (isMountedRef.current && token === taskTokenRef.current) {
        setFeedback({ state: 'failed', action, operationId: null, errorCode: 'unexpected' });
      }
    } finally {
      busyRef.current = false;
    }
  };

  const isBusy = feedback.state === 'busy';
  const alertType =
    feedback.state === 'succeeded'
      ? 'success'
      : feedback.state === 'busy'
        ? 'info'
        : feedback.state === 'cancelled'
          ? 'warning'
          : 'error';

  if (isLoading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  return (
    <div className="history-page" ref={pageRef} tabIndex={-1}>
      <div className="history-page-head">
        <div>
          <Typography.Title level={5} className="history-page-title">
            历史记录
          </Typography.Title>
          <Typography.Text type="secondary">
            {items.length} 条记录
            {normalizedQuery && ` · 匹配 ${filteredItems.length} 条`}
          </Typography.Text>
        </div>
        <Button
          danger
          disabled={items.length === 0 || isBusy}
          onClick={() => setIsClearConfirmOpen(true)}
        >
          清空历史
        </Button>
      </div>

      {feedback.state !== 'idle' && (
        <Alert
          className="history-page-status"
          type={alertType}
          showIcon
          message={feedbackMessage(feedback)}
          description={
            feedback.operationId ? `操作 ${feedback.operationId}` : undefined
          }
        />
      )}

      {filteredItems.length === 0 ? (
        <div className="history-empty">
          <Empty description={items.length === 0 ? '暂无历史记录' : '没有匹配的历史记录'}>
            <Typography.Text type="secondary">
              {items.length === 0
                ? '完成截图、复制或另存后，结果会显示在这里。'
                : '试试其他关键词，或清空搜索条件。'}
            </Typography.Text>
          </Empty>
        </div>
      ) : (
        <>
          <div className="history-list">
            {visibleItems.map((item) => (
              <Card
                key={item.historyItemId}
                className="history-entry-card"
                variant="borderless"
                role="button"
                tabIndex={0}
                aria-label={`查看历史记录 ${item.historyItemId}`}
                onClick={(event) => openPreview(item.historyItemId, event.currentTarget)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    openPreview(item.historyItemId, event.currentTarget);
                  }
                }}
              >
                <div className="history-entry-body">
                  <div className="history-entry-detail">
                    <div className="history-entry-head">
                      <span className="history-entry-date">
                        {formatTimestamp(item.createdAtUtc)}
                      </span>
                      <Tag className="history-entry-source" bordered={false}>
                        {sourceLabel(item.source)}
                      </Tag>
                    </div>
                    <div className="history-entry-meta">
                      <span>{item.widthPx} × {item.heightPx}</span>
                      <span className="history-entry-dot">·</span>
                      <span>{formatBytes(item.byteSize)}</span>
                    </div>
                    <div className="history-entry-session">
                      会话 {item.sessionId.slice(0, 8)} · 修订 {item.revision}
                    </div>
                    <div className="history-entry-actions">
                      <Button
                        type="link"
                        size="small"
                        disabled={isBusy}
                        onClick={(event) => {
                          event.stopPropagation();
                          void runTask('复制', () => onCopy(item.historyItemId));
                        }}
                      >
                        复制
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        disabled={isBusy}
                        onClick={(event) => {
                          event.stopPropagation();
                          void runTask('另存', () => onSaveAs(item.historyItemId));
                        }}
                      >
                        另存
                      </Button>
                      <Button
                        type="link"
                        size="small"
                        danger
                        disabled={isBusy}
                        onClick={(event) => {
                          event.stopPropagation();
                          triggerRef.current = event.currentTarget;
                          setConfirmItemId(item.historyItemId);
                          setIsConfirmOpen(true);
                        }}
                      >
                        删除
                      </Button>
                    </div>
                  </div>
                  <div className="history-entry-preview">
                    <PreviewImage item={item} variant="thumb" />
                  </div>
                </div>
              </Card>
            ))}
          </div>
          {pageCount > 1 && (
            <div className="history-pagination">
              <Pagination
                current={Math.min(currentPage, pageCount)}
                pageSize={pageSize}
                total={filteredItems.length}
                showSizeChanger={false}
                onChange={setCurrentPage}
              />
            </div>
          )}
        </>
      )}

      <Drawer
        title="预览"
        open={selectedItem !== null}
        onClose={closePreview}
        afterOpenChange={restoreFocus}
        footer={
          <Space>
            <Button
              type="primary"
              disabled={isBusy}
              onClick={() =>
                selectedItem &&
                void runTask('复制', () => onCopy(selectedItem.historyItemId))
              }
            >
              复制
            </Button>
            <Button
              disabled={isBusy}
              onClick={() =>
                selectedItem &&
                void runTask('另存', () => onSaveAs(selectedItem.historyItemId))
              }
            >
              另存
            </Button>
            <Button
              danger
              disabled={isBusy}
              onClick={() => {
                if (!selectedItem) return;
                setConfirmItemId(selectedItem.historyItemId);
                setIsConfirmOpen(true);
              }}
            >
              删除
            </Button>
          </Space>
        }
      >
        {selectedItem && (
          <>
            <div className="preview-meta">
              <span>{formatTimestamp(selectedItem.createdAtUtc)}</span>
              <span>{selectedItem.widthPx} × {selectedItem.heightPx}</span>
              <span>{formatBytes(selectedItem.byteSize)}</span>
              <span>{sourceLabel(selectedItem.source)}</span>
            </div>
            <PreviewImage item={selectedItem} variant="full" />
          </>
        )}
      </Drawer>

      <Modal
        title="删除这条历史记录？"
        open={isConfirmOpen}
        okText="删除"
        okButtonProps={{ danger: true, disabled: isBusy }}
        cancelText="取消"
        onOk={() =>
          confirmItemId && void runTask('删除', () => onDelete(confirmItemId))
        }
        onCancel={() => setIsConfirmOpen(false)}
      >
        删除后无法恢复。
      </Modal>

      <Modal
        title="清空全部历史记录？"
        open={isClearConfirmOpen}
        okText="清空"
        okButtonProps={{ danger: true, disabled: isBusy }}
        cancelText="取消"
        onOk={() => void runTask('清空', onClear)}
        onCancel={() => setIsClearConfirmOpen(false)}
      >
        清空后无法恢复。
      </Modal>
    </div>
  );
}

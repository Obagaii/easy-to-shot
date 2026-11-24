import {
  Button,
  Card,
  Drawer,
  Empty,
  Modal,
  Skeleton,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { HistoryItem } from '../bridge';

interface HistoryPageProps {
  items: HistoryItem[];
  isLoading: boolean;
  onCopy: (historyItemId: string) => void;
  onSaveAs: (historyItemId: string) => void;
  onDelete: (historyItemId: string) => void;
}

type PreviewState = 'loading' | 'loaded' | 'failed';

const sourceLabels: Record<string, string> = {
  capture: '截图',
  copy: '复制',
  save: '保存',
  pin: '贴图',
};

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
        <Typography.Text type="secondary">预览不可用</Typography.Text>
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

export function HistoryPage({ items, isLoading, onCopy, onSaveAs, onDelete }: HistoryPageProps) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);
  const selectedItem = items.find((item) => item.historyItemId === selectedItemId) ?? null;

  const openPreview = (historyItemId: string, trigger: HTMLElement) => {
    triggerRef.current = trigger;
    setSelectedItemId(historyItemId);
  };

  const closePreview = () => setSelectedItemId(null);

  const restoreFocus = (isOpen: boolean) => {
    if (!isOpen) triggerRef.current?.focus();
  };

  const handleDelete = () => {
    if (selectedItem) onDelete(selectedItem.historyItemId);
    setIsConfirmOpen(false);
    closePreview();
  };

  if (isLoading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  return (
    <div className="history-page">
      <div className="history-toolbar">
        <Typography.Text type="secondary">共 {items.length} 条记录</Typography.Text>
      </div>

      {items.length === 0 ? (
        <Empty description="暂无历史记录" />
      ) : (
        <div className="history-grid">
          {items.map((item) => (
            <Card
              key={item.historyItemId}
              hoverable
              className="history-card"
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
              cover={<PreviewImage item={item} variant="thumb" />}
            >
              <Card.Meta
                title={formatTimestamp(item.createdAtUtc)}
                description={`${item.widthPx} × ${item.heightPx} · ${formatBytes(item.byteSize)}`}
              />
              <Tag className="history-source">{sourceLabel(item.source)}</Tag>
            </Card>
          ))}
        </div>
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
              onClick={() => selectedItem && onCopy(selectedItem.historyItemId)}
            >
              复制
            </Button>
            <Button onClick={() => selectedItem && onSaveAs(selectedItem.historyItemId)}>
              另存
            </Button>
            <Button danger onClick={() => setIsConfirmOpen(true)}>
              删除
            </Button>
          </Space>
        }
      >
        {selectedItem && (
          <>
            <PreviewImage item={selectedItem} variant="full" />
            <Typography.Paragraph>
              记录 {selectedItem.historyItemId}
              <br />
              时间 {formatTimestamp(selectedItem.createdAtUtc)}
              <br />
              像素 {selectedItem.widthPx} × {selectedItem.heightPx} · 大小{' '}
              {formatBytes(selectedItem.byteSize)}
              <br />
              来源 {sourceLabel(selectedItem.source)}
            </Typography.Paragraph>
          </>
        )}
      </Drawer>

      <Modal
        title="删除这条历史记录？"
        open={isConfirmOpen}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        onOk={handleDelete}
        onCancel={() => setIsConfirmOpen(false)}
      >
        删除后无法恢复，用户另存的文件不受影响。
      </Modal>
    </div>
  );
}

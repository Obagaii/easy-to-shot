import { Button, Card, Drawer, Empty, Modal, Skeleton, Space, Typography } from 'antd';
import { useState } from 'react';
import type { HistoryItem } from '../bridge';

interface HistoryPageProps {
  items: HistoryItem[];
  isLoading: boolean;
  onCopy: (historyItemId: string) => void;
  onSaveAs: (historyItemId: string) => void;
  onDelete: (historyItemId: string) => void;
}

export function HistoryPage({ items, isLoading, onCopy, onSaveAs, onDelete }: HistoryPageProps) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const selectedItem = items.find((item) => item.historyItemId === selectedItemId) ?? null;

  const handleDelete = () => {
    if (selectedItemId) onDelete(selectedItemId);
    setIsConfirmOpen(false);
    setSelectedItemId(null);
  };

  if (isLoading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  return (
    <div className="history-page">
      {items.length === 0 ? (
        <Empty description="暂无历史记录" />
      ) : (
        <div className="history-grid">
          {items.map((item) => (
            <Card
              key={item.historyItemId}
              hoverable
              className="history-card"
              onClick={() => setSelectedItemId(item.historyItemId)}
              cover={<div className="history-thumb" />}
            >
              <Card.Meta
                title={item.createdAtUtc}
                description={`${item.widthPx} × ${item.heightPx}`}
              />
            </Card>
          ))}
        </div>
      )}

      <Drawer
        title="预览"
        open={selectedItem !== null}
        onClose={() => setSelectedItemId(null)}
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
            <Button danger onClick={() => setIsConfirmOpen(true)}>删除</Button>
          </Space>
        }
      >
        <div className="history-preview" />
        {selectedItem && (
          <Typography.Paragraph>
            记录 {selectedItem.historyItemId} · {selectedItem.widthPx} × {selectedItem.heightPx}
            <br />
            预览来源：{selectedItem.previewUrl}
          </Typography.Paragraph>
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

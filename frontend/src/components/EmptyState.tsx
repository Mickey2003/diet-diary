import { Button, Typography, theme as antdTheme } from 'antd';

const { Text } = Typography;

interface EmptyStateProps {
  emoji?: string;
  hint: string;
  actionLabel?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
}

export default function EmptyState({ emoji = '🗂️', hint, actionLabel, onAction, actionDisabled }: EmptyStateProps) {
  const { token } = antdTheme.useToken();

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '60px 24px',
        gap: 12,
        color: token.colorTextTertiary,
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 40, lineHeight: 1 }}>{emoji}</div>
      <Text type="secondary" style={{ fontSize: 14 }}>{hint}</Text>
      {actionLabel && onAction && (
        <Button type="primary" size="small" onClick={onAction} style={{ marginTop: 4 }} disabled={actionDisabled}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}

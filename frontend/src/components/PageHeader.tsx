import { Typography, theme as antdTheme, Grid } from 'antd';
import type { ReactNode } from 'react';

const { Text } = Typography;
const { useBreakpoint } = Grid;

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  extra?: ReactNode;
}

export default function PageHeader({ title, subtitle, extra }: PageHeaderProps) {
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  // On mobile the top bar already shows the title; keep hidden
  if (isMobile) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 20,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 20,
            fontWeight: 700,
            color: token.colorText,
            lineHeight: 1.3,
          }}
        >
          {title}
        </div>
        {subtitle && (
          <Text type="secondary" style={{ fontSize: 13 }}>
            {subtitle}
          </Text>
        )}
      </div>
      {extra && <div>{extra}</div>}
    </div>
  );
}

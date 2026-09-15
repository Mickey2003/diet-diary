import { useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Tag,
  Typography,
  theme as antdTheme,
  message,
  Space,
} from 'antd';
import {
  ApiOutlined,
  BellOutlined,
  BulbOutlined,
  FileTextOutlined,
  RightOutlined,
  SafetyOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
  LogoutOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { logout } from '../api/auth';
import { useAuth } from '../auth/AuthContext';
import { APP_VERSION } from '../version';
import { UnreadContext } from '../context/UnreadContext';
import { OPEN_ONBOARDING_EVENT } from '../components/OnboardingTutorial';
import { getBatteryStatusNative, isNativeApp, requestIgnoreBatteryNative } from '../native/bridge';

const { Text, Title } = Typography;

interface MenuRow {
  label: string;
  icon: React.ReactNode;
  path?: string;
  action?: () => void;
  badge?: string;
  adminOnly?: boolean;
}

interface Props {
  onLoggedOut: () => void;
}

export default function MePage({ onLoggedOut }: Props) {
  const { token } = antdTheme.useToken();
  const { username, displayName, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [logoutLoading, setLogoutLoading] = useState(false);
  const unreadCtx = useContext(UnreadContext);
  const unread = unreadCtx?.unread ?? 0;
  const native = isNativeApp();
  const [batteryIgnoring, setBatteryIgnoring] = useState<boolean | null>(null);

  useEffect(() => {
    if (!native) return;
    const status = getBatteryStatusNative();
    if (status !== null) setBatteryIgnoring(status.ignoring);
  }, [native]);

  const avatarLetter = (displayName || username || '?')[0].toUpperCase();

  async function handleLogout() {
    setLogoutLoading(true);
    try {
      await logout();
      onLoggedOut();
    } catch {
      message.error('退出失败');
    } finally {
      setLogoutLoading(false);
    }
  }

  function nav(path: string) {
    navigate(path);
  }

  const sections: { title: string; rows: MenuRow[] }[] = [
    {
      title: '消息',
      rows: [
        {
          label: '消息中心',
          icon: <BellOutlined />,
          path: '/inbox',
          badge: unread > 0 ? String(unread) : undefined,
        },
      ],
    },
    {
      title: '记录与分析',
      rows: [
        { label: '自然语言查询', icon: <SearchOutlined />, path: '/query' },
        { label: '阶段总结', icon: <FileTextOutlined />, path: '/reports' },
        { label: 'AI 记忆', icon: <BulbOutlined />, path: '/memory' },
      ],
    },
    {
      title: '通知与集成',
      rows: [
        { label: '通知推送', icon: <BellOutlined />, path: '/notify' },
        { label: '数据与集成', icon: <ApiOutlined />, path: '/integrations' },
      ],
    },
    {
      title: '设置',
      rows: [
        { label: '新手教程', icon: <RocketOutlined />, action: () => window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT)) },
        { label: '模型设置', icon: <SettingOutlined />, path: '/settings' },
        { label: '账户与安全', icon: <SafetyOutlined />, path: '/account' },
      ],
    },
    ...(isAdmin
      ? [
          {
            title: '管理',
            rows: [
              { label: '用户管理', icon: <TeamOutlined />, path: '/admin/users', adminOnly: true },
            ],
          },
        ]
      : []),
  ];

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      {/* Battery optimization banner (compact) */}
      {native && batteryIgnoring === false && (
        <Alert
          type="warning"
          showIcon
          message="后台通知可能被系统限制"
          description={
            <Space wrap>
              <span style={{ fontSize: 12 }}>建议关闭电池优化以确保通知及时送达</span>
              <Button
                size="small"
                onClick={() => requestIgnoreBatteryNative()}
              >
                去关闭电池优化
              </Button>
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Header card with gradient tint */}
      <Card
        style={{
          marginBottom: 16,
          borderRadius: 12,
          background: `linear-gradient(135deg, ${token.colorPrimaryBg} 0%, ${token.colorBgContainer} 100%)`,
          boxShadow: 'var(--dd-shadow, 0 1px 2px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.04))',
        }}
        bodyStyle={{ padding: '20px 20px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <Avatar
            size={56}
            style={{
              background: token.colorPrimary,
              fontSize: 22,
              fontWeight: 700,
              color: '#fff',
              flexShrink: 0,
            }}
          >
            {avatarLetter}
          </Avatar>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600, color: token.colorText, marginBottom: 4 }}>
              {displayName || username}
            </div>
            {displayName && displayName !== username && (
              <Text type="secondary" style={{ fontSize: 12 }}>@{username}</Text>
            )}
            <div style={{ marginTop: 4 }}>
              {isAdmin ? (
                <Tag color="red">管理员</Tag>
              ) : (
                <Tag>普通用户</Tag>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* Grouped sections */}
      {sections.map((section) => (
        <div key={section.title} style={{ marginBottom: 16 }}>
          <Text
            type="secondary"
            style={{
              fontSize: 11,
              display: 'block',
              marginBottom: 6,
              paddingLeft: 4,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
            }}
          >
            {section.title}
          </Text>
          <Card
            bodyStyle={{ padding: 0 }}
            style={{
              borderRadius: 12,
              overflow: 'hidden',
              boxShadow: 'var(--dd-shadow, 0 1px 2px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.04))',
            }}
          >
            {section.rows.map((row, idx) => (
              <div
                key={row.label}
                onClick={() => {
                  if (row.path) nav(row.path);
                  else if (row.action) row.action();
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '0 16px',
                  cursor: 'pointer',
                  borderBottom:
                    idx < section.rows.length - 1
                      ? `1px solid ${token.colorBorderSecondary}`
                      : 'none',
                  minHeight: 48,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background =
                    token.colorFillAlter)
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background = '')
                }
              >
                {/* Icon in tinted circle */}
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: '50%',
                    background: token.colorPrimaryBg,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: token.colorPrimary,
                    fontSize: 15,
                    flexShrink: 0,
                  }}
                >
                  {row.icon}
                </div>
                <Text style={{ flex: 1, fontSize: 15 }}>{row.label}</Text>
                {row.badge && (
                  <Badge count={Number(row.badge)} size="small" style={{ marginRight: 4 }} />
                )}
                <RightOutlined style={{ color: token.colorTextTertiary, fontSize: 12 }} />
              </div>
            ))}
          </Card>
        </div>
      ))}

      {/* Footer */}
      <div
        style={{
          textAlign: 'center',
          marginTop: 8,
          marginBottom: 8,
          padding: '0 16px',
        }}
      >
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          {`今天吃得怎么样 v${APP_VERSION}`}
        </Text>
        <Button
          danger
          ghost
          icon={<LogoutOutlined />}
          loading={logoutLoading}
          onClick={handleLogout}
          block
        >
          退出登录
        </Button>
      </div>

    </div>
  );
}

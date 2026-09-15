import { useCallback, useEffect, useState, Suspense, lazy, useContext } from 'react';
import React from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import {
  ConfigProvider,
  App as AntdApp,
  Layout,
  Menu,
  Tag,
  Typography,
  Spin,
  theme as antdTheme,
  Grid,
  Button,
  Segmented,
  ColorPicker,
  Switch,
  Drawer as AntdDrawer,
  Divider,
  Space,
  Popover,
  Badge,
} from 'antd';
import { StyleProvider, legacyLogicalPropertiesTransformer } from '@ant-design/cssinjs';
import zhCN from 'antd/locale/zh_CN';
import {
  CameraOutlined,
  HistoryOutlined,
  BarChartOutlined,
  SearchOutlined,
  FileTextOutlined,
  SettingOutlined,
  BellOutlined,
  BgColorsOutlined,
  SunOutlined,
  MoonOutlined,
  DesktopOutlined,
  TeamOutlined,
  ApiOutlined,
  HeartOutlined,
  BulbOutlined,
  UserOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';

// Eager imports (small or critical)
import LoginPage from './pages/Login';
import MePage from './pages/MePage';
import ErrorBoundary from './components/ErrorBoundary';

// Lazy imports for code splitting
const Upload = lazy(() => import('./pages/Upload'));
const Timeline = lazy(() => import('./pages/Timeline'));
const Stats = lazy(() => import('./pages/Stats'));
const Query = lazy(() => import('./pages/Query'));
const Reports = lazy(() => import('./pages/Reports'));
const Settings = lazy(() => import('./pages/Settings'));
const Notify = lazy(() => import('./pages/Notify'));
const Health = lazy(() => import('./pages/Health'));
const Memory = lazy(() => import('./pages/Memory'));
const AdminUsers = lazy(() => import('./pages/AdminUsers'));
const Integrations = lazy(() => import('./pages/Integrations'));
const AccountPage = lazy(() => import('./pages/AccountPage'));
const Inbox = lazy(() => import('./pages/Inbox'));

import { getSettings } from './api/endpoints';
import { getAuthStatus } from './api/auth';
import { UNAUTHORIZED_EVENT } from './api/client';
import { ThemeProvider, useAppTheme } from './theme/ThemeContext';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { registerDeviceNative, setBadgeNative } from './native/bridge';
import { useUnread } from './hooks/useUnread';
import { useMealAlerts } from './hooks/useMealAlerts';
import { UnreadContext } from './context/UnreadContext';
import OnboardingTutorial from './components/OnboardingTutorial';
import type { SettingsOut } from './api/types';
import type { ThemeMode } from './theme/ThemeContext';
import { APP_VERSION } from './version';

const { Sider, Header, Content } = Layout;
const { Text } = Typography;
const { useBreakpoint } = Grid;

// Color presets for picker
const COLOR_PRESETS = [
  { label: '主题色', colors: ['#f5a623', '#52c41a', '#1677ff', '#eb2f96', '#722ed1', '#13c2c2'] },
];

/** Syncs CSS variables on <html> from current antd token */
function CssVarSync() {
  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();

  useEffect(() => {
    const s = document.documentElement.style;
    s.setProperty('--dd-bg-container', token.colorBgContainer);
    s.setProperty('--dd-bg-layout', token.colorBgLayout);
    s.setProperty('--dd-border', token.colorBorderSecondary);
    s.setProperty('--dd-text', token.colorText);
    s.setProperty('--dd-text-secondary', token.colorTextSecondary);
    s.setProperty('--dd-text-tertiary', token.colorTextTertiary);
    s.setProperty('--dd-primary', token.colorPrimary);
    s.setProperty('--dd-primary-bg', token.colorPrimaryBg);
    s.setProperty('--dd-fill-alter', token.colorFillAlter);
    s.setProperty('--dd-bg-elevated', token.colorBgElevated ?? token.colorBgContainer);
    // Shadow: light = subtle card, dark = flat with border
    if (resolved === 'dark') {
      s.setProperty('--dd-shadow', 'none');
    } else {
      s.setProperty('--dd-shadow', '0 1px 2px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.04)');
    }
    // Update theme-color meta
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', token.colorPrimary);
  }, [token, resolved]);

  return null;
}

/** Theme controls: mode segmented + color picker + compact switch */
function ThemeControls({ vertical = false }: { vertical?: boolean }) {
  const { mode, primary, compact, setMode, setPrimary, setCompact } = useAppTheme();
  const { token } = antdTheme.useToken();

  const modeOptions = [
    { label: <SunOutlined title="浅色" />, value: 'light' },
    { label: <MoonOutlined title="深色" />, value: 'dark' },
    { label: <DesktopOutlined title="跟随系统" />, value: 'system' },
  ];

  if (vertical) {
    return (
      <div style={{ padding: '8px 0' }}>
        <div style={{ marginBottom: 10 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>显示模式</Text>
          <Segmented
            options={[
              { label: '浅色', value: 'light' },
              { label: '深色', value: 'dark' },
              { label: '跟随系统', value: 'system' },
            ]}
            value={mode}
            onChange={(v) => setMode(v as ThemeMode)}
            size="small"
          />
        </div>
        <div style={{ marginBottom: 10 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>主题色</Text>
          <ColorPicker
            value={primary}
            presets={COLOR_PRESETS}
            onChange={(_, hex) => setPrimary(hex)}
            size="small"
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Switch size="small" checked={compact} onChange={setCompact} />
          <Text type="secondary" style={{ fontSize: 12 }}>紧凑模式</Text>
        </div>
      </div>
    );
  }

  return (
    <Space size={8} align="center">
      <Segmented
        options={modeOptions}
        value={mode}
        onChange={(v) => setMode(v as ThemeMode)}
        size="small"
      />
      <ColorPicker
        value={primary}
        presets={COLOR_PRESETS}
        onChange={(_, hex) => setPrimary(hex)}
        size="small"
        style={{ border: `1px solid ${token.colorBorder}` }}
      />
      <Space size={4} align="center">
        <Switch size="small" checked={compact} onChange={setCompact} />
        <Text type="secondary" style={{ fontSize: 11 }}>紧凑</Text>
      </Space>
    </Space>
  );
}

/** Page title mapping for mobile top bar */
const PAGE_TITLES: Record<string, string> = {
  '/': '记录一餐',
  '/timeline': '饮食时间线',
  '/stats': '统计图表',
  '/query': '自然语言查询',
  '/reports': '阶段总结',
  '/health': '健康档案',
  '/memory': 'AI 记忆',
  '/notify': '通知推送',
  '/integrations': '数据与集成',
  '/settings': '模型设置',
  '/admin/users': '用户管理',
  '/me': '我的',
  '/account': '账户与安全',
  '/inbox': '消息中心',
};

function getPageTitle(pathname: string): string {
  if (pathname === '/') return '记录一餐';
  for (const [key, label] of Object.entries(PAGE_TITLES)) {
    if (key !== '/' && pathname.startsWith(key)) return label;
  }
  return '今天吃得怎么样';
}

/** Tab root paths - when we are NOT on these, show back button */
const TAB_ROOTS = ['/', '/timeline', '/stats', '/health', '/me'];

function isTabRoot(pathname: string): boolean {
  return TAB_ROOTS.some(
    (root) => pathname === root || (root !== '/' && pathname.startsWith(root + '/') === false && pathname === root)
  );
}

/** Selected tab for mobile bottom bar */
function getMobileTab(pathname: string): string {
  if (pathname === '/') return '/';
  if (pathname.startsWith('/timeline')) return '/timeline';
  if (pathname.startsWith('/stats')) return '/stats';
  if (pathname.startsWith('/health')) return '/health';
  return '/me';
}

interface ShellProps {
  onLoggedOut: () => void;
}

/** Mobile bottom tab bar */
function MobileTabBar({ selected }: { selected: string }) {
  const { token } = antdTheme.useToken();
  const navigate = useNavigate();
  const unreadCtx = useContext(UnreadContext);
  const unread = unreadCtx?.unread ?? 0;

  const tabs = [
    { key: '/', icon: <CameraOutlined />, label: '记录' },
    { key: '/timeline', icon: <HistoryOutlined />, label: '时间线' },
    { key: '/stats', icon: <BarChartOutlined />, label: '统计' },
    { key: '/health', icon: <HeartOutlined />, label: '健康' },
    {
      key: '/me',
      icon: (
        <Badge dot={unread > 0} offset={[2, -2]}>
          <UserOutlined />
        </Badge>
      ),
      label: '我的',
    },
  ];

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: 'calc(56px + env(safe-area-inset-bottom))',
        background: token.colorBgElevated ?? token.colorBgContainer,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        alignItems: 'stretch',
        zIndex: 200,
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      {tabs.map((tab) => {
        const isActive = selected === tab.key;
        return (
          <button
            key={tab.key}
            onClick={() => navigate(tab.key)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 3,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '6px 0',
              color: isActive ? token.colorPrimary : token.colorTextTertiary,
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <span style={{ fontSize: isActive ? 22 : 20, transition: 'font-size .15s' }}>{tab.icon}</span>
            <span style={{ fontSize: 11, lineHeight: 1, fontWeight: isActive ? 600 : 400 }}>{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function AppShell({ onLoggedOut }: ShellProps) {
  const { username, displayName, isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const unreadCtx = useContext(UnreadContext);
  const unread = unreadCtx?.unread ?? 0;

  // Fetch settings once on mount only
  useEffect(() => {
    getSettings().then(setSettings).catch(() => {/* 忽略设置加载失败 */});
  }, []);

  // Build menu items dynamically based on role
  const menuItems = [
    { key: '/', icon: <CameraOutlined />, label: '记录一餐' },
    { key: '/timeline', icon: <HistoryOutlined />, label: '饮食时间线' },
    { key: '/stats', icon: <BarChartOutlined />, label: '统计图表' },
    { key: '/query', icon: <SearchOutlined />, label: '自然语言查询' },
    { key: '/reports', icon: <FileTextOutlined />, label: '阶段总结' },
    { key: '/health', icon: <HeartOutlined />, label: '健康档案' },
    { key: '/memory', icon: <BulbOutlined />, label: 'AI 记忆' },
    { key: '/notify', icon: <BellOutlined />, label: '通知推送' },
    { key: '/integrations', icon: <ApiOutlined />, label: '数据与集成' },
    { key: '/settings', icon: <SettingOutlined />, label: '模型设置' },
    ...(isAdmin ? [{ key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' }] : []),
    { key: '/me', icon: <UserOutlined />, label: '我的' },
  ];

  const selectedKey = menuItems.find((m) => location.pathname.startsWith(m.key) && m.key !== '/')
    ? menuItems.find((m) => location.pathname.startsWith(m.key) && m.key !== '/')!.key
    : location.pathname === '/'
    ? '/'
    : '';

  const providerLabel =
    settings?.presets?.[settings.provider]?.label ?? settings?.provider ?? '';
  const isMock = settings?.provider === 'mock';

  const siderTheme = resolved === 'dark' ? 'dark' : 'light';

  const menuEl = (
    <Menu
      mode="inline"
      selectedKeys={[selectedKey]}
      items={menuItems}
      onClick={({ key }) => { navigate(key); }}
      style={{ border: 'none', flex: 1 }}
      theme={siderTheme}
    />
  );

  const logoEl = (showFull: boolean) => (
    <div
      style={{
        padding: showFull ? '16px 20px' : '16px 8px',
        userSelect: 'none',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}
    >
      {showFull ? (
        <>
          <div style={{ fontWeight: 700, fontSize: 15, color: token.colorPrimary, letterSpacing: 1 }}>
            今天吃得怎么样
          </div>
          <div style={{ fontSize: 11, color: token.colorTextTertiary, marginTop: 2 }}>
            AI 饮食观察日记
          </div>
        </>
      ) : (
        <div style={{ fontSize: 20, textAlign: 'center' }}>🍱</div>
      )}
    </div>
  );

  const headerName = displayName || username;
  const mobileTab = getMobileTab(location.pathname);
  const pageTitle = getPageTitle(location.pathname);
  const isOnTabRoot = isTabRoot(location.pathname);

  // Bottom tab bar height for content padding
  const tabBarHeight = isMobile ? 'calc(56px + env(safe-area-inset-bottom))' : '0px';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* Desktop Sider */}
      {!isMobile && (
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme={siderTheme}
          style={{
            borderRight: `1px solid ${token.colorBorderSecondary}`,
            background: token.colorBgContainer,
          }}
          width={200}
        >
          {logoEl(!collapsed)}
          {menuEl}
          {/* Footer version */}
          <div
            style={{
              padding: collapsed ? '8px 0' : '8px 16px',
              borderTop: `1px solid ${token.colorBorderSecondary}`,
              color: token.colorTextTertiary,
              fontSize: 11,
              textAlign: 'center',
              flexShrink: 0,
            }}
          >
            {!collapsed && `v${APP_VERSION}`}
          </div>
        </Sider>
      )}

      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            padding: '0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: isMobile ? 'space-between' : 'flex-end',
            height: 48,
            position: 'sticky',
            top: 0,
            zIndex: 100,
          }}
        >
          {/* Mobile: 3-column grid: 44px | 1fr | 44px+ */}
          {isMobile ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '44px 1fr 44px',
                alignItems: 'center',
                width: '100%',
                padding: '0 4px',
                gap: 0,
              }}
            >
              {/* Left: back button or spacer */}
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                {!isOnTabRoot ? (
                  <Button
                    type="text"
                    icon={<ArrowLeftOutlined />}
                    size="small"
                    onClick={() => {
                      if (window.history.length > 1) {
                        navigate(-1);
                      } else {
                        navigate('/me');
                      }
                    }}
                  />
                ) : null}
              </div>

              {/* Center: page title */}
              <div
                style={{
                  fontWeight: 600,
                  fontSize: 15,
                  color: token.colorText,
                  textAlign: 'center',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {pageTitle}
              </div>

              {/* Right: bell + theme */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0 }}>
                {isMock && <Tag color="orange" style={{ margin: 0, fontSize: 10 }}>演示</Tag>}
                <Badge count={unread} size="small" offset={[-2, 4]}>
                  <Button
                    type="text"
                    icon={<BellOutlined />}
                    size="small"
                    onClick={() => navigate('/inbox')}
                  />
                </Badge>
                <Popover
                  content={<ThemeControls vertical />}
                  title="外观设置"
                  trigger="click"
                  placement="bottomRight"
                >
                  <Button type="text" icon={<BgColorsOutlined />} size="small" />
                </Popover>
              </div>
            </div>
          ) : (
            /* Desktop: model info + theme controls + username + bell */
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingRight: 24 }}>
              {settings && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  当前模型：{providerLabel || settings.text_model || '未配置'}
                </Text>
              )}
              {settings === null && <Spin size="small" />}
              {isMock && <Tag color="orange">离线演示</Tag>}
              <Divider type="vertical" style={{ height: 20 }} />
              <ThemeControls />
              <Divider type="vertical" style={{ height: 20 }} />
              <Badge count={unread} size="small">
                <Button
                  type="text"
                  icon={<BellOutlined />}
                  size="small"
                  onClick={() => navigate('/inbox')}
                />
              </Badge>
              <Divider type="vertical" style={{ height: 20 }} />
              <Space size={4} align="center">
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {headerName}
                </Text>
                {isAdmin && <Tag color="red" style={{ fontSize: 10, marginLeft: 0 }}>管理员</Tag>}
              </Space>
            </div>
          )}
        </Header>

        <Content
          className={isMobile ? 'is-mobile' : ''}
          style={{
            padding: isMobile ? 12 : 24,
            paddingBottom: isMobile ? `calc(12px + ${tabBarHeight})` : 24,
            background: token.colorBgLayout,
            minHeight: 'calc(100vh - 48px)',
            overscrollBehavior: isMobile ? 'none' : undefined,
          }}
        >
          <ErrorBoundary resetKey={location.pathname}>
            <Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spin size="large" /></div>}>
              <Routes>
                <Route path="/" element={<Upload />} />
                <Route path="/timeline" element={<Timeline />} />
                <Route path="/stats" element={<Stats />} />
                <Route path="/query" element={<Query />} />
                <Route path="/reports" element={<Reports />} />
                <Route path="/health" element={<Health />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/notify" element={<Notify />} />
                <Route path="/integrations" element={<Integrations />} />
                <Route path="/settings" element={<Settings onLoggedOut={onLoggedOut} />} />
                <Route path="/admin/users" element={<AdminUsers />} />
                <Route path="/me" element={<MePage onLoggedOut={onLoggedOut} />} />
                <Route path="/account" element={<AccountPage onLoggedOut={onLoggedOut} />} />
                <Route path="/inbox" element={<Inbox />} />
                <Route path="/inbox/:id" element={<Inbox />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </Content>

        {/* Mobile bottom tab bar */}
        {isMobile && <MobileTabBar selected={mobileTab} />}
      </Layout>

      {/* 首次使用新手教程（仅未标记过的新用户弹出） */}
      <OnboardingTutorial />
    </Layout>
  );
}

interface AuthState {
  status: 'checking' | 'anonymous' | 'authed';
  username: string;
  displayName: string;
  isAdmin: boolean;
}

/** 登录门卫：未登录显示登录页，登录后进入应用；任何接口返回 401 都会回到登录页。 */
function AuthGate() {
  const [state, setState] = useState<AuthState>({
    status: 'checking',
    username: '',
    displayName: '',
    isAdmin: false,
  });

  const check = useCallback(() => {
    getAuthStatus()
      .then((s) => {
        if (s.authenticated && s.username) {
          setState({
            status: 'authed',
            username: s.username,
            displayName: s.display_name ?? s.username,
            isAdmin: !!s.is_admin,
          });
        } else {
          setState((p) => ({ ...p, status: 'anonymous' }));
        }
      })
      .catch(() => setState((p) => ({ ...p, status: 'anonymous' })));
  }, []);

  useEffect(() => {
    check();
    const onUnauthorized = () => setState((p) => ({ ...p, status: 'anonymous' }));
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [check]);

  if (state.status === 'checking') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }
  if (state.status === 'anonymous') {
    return (
      <LoginPage
        onSuccess={(u, displayName, isAdm) => {
          setState({ status: 'authed', username: u, displayName: displayName ?? u, isAdmin: !!isAdm });
          // Register device on login success
          try { registerDeviceNative(); } catch {/* ignore */}
        }}
      />
    );
  }
  return (
    <BrowserRouter>
      <CssVarSync />
      <AuthProvider
        initialUsername={state.username}
        initialDisplayName={state.displayName}
        initialIsAdmin={state.isAdmin}
      >
        <UnreadProvider>
          <AppShell
            onLoggedOut={() => setState((p) => ({ ...p, status: 'anonymous' }))}
          />
        </UnreadProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

/** Foreground meal-alert scheduler — mounts inside AntdApp so notification API works */
function MealAlertScheduler() {
  const { notification } = AntdApp.useApp();
  const navigate = useNavigate();
  useMealAlerts(notification, navigate);
  return null;
}

/** Provides unread count via context, also syncs badge */
function UnreadProvider({ children }: { children: React.ReactNode }) {
  const { unread, refresh } = useUnread();

  useEffect(() => {
    setBadgeNative(unread);
  }, [unread]);

  return (
    <UnreadContext.Provider value={{ unread, refresh }}>
      <MealAlertScheduler />
      {children}
    </UnreadContext.Provider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AppWrapper />
    </ThemeProvider>
  );
}

function AppWrapper() {
  const { resolved, primary, compact } = useAppTheme();

  const algorithms = [
    resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    ...(compact ? [antdTheme.compactAlgorithm] : []),
  ];

  return (
    <StyleProvider
      hashPriority="high"
      transformers={[legacyLogicalPropertiesTransformer]}
    >
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: algorithms,
          token: {
            colorPrimary: primary,
            borderRadius: 8,
            fontFamily:
              '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
          },
        }}
      >
        <AntdApp>
          <CssVarSync />
          <AuthGate />
        </AntdApp>
      </ConfigProvider>
    </StyleProvider>
  );
}

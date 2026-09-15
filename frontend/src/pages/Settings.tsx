import { useEffect, useState, useCallback } from 'react';
import {
  Select,
  Input,
  Button,
  Alert,
  Form,
  Skeleton,
  Spin,
  Tag,
  Typography,
  Divider,
  message,
  Card,
  Switch,
  Segmented,
  ColorPicker,
  Grid,
  Space,
  theme as antdTheme,
  Statistic,
  Table,
  Collapse,
  InputNumber,
  Tooltip,
  Checkbox,
} from 'antd';
import { SaveOutlined, ApiOutlined, ReloadOutlined, WalletOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
import {
  getSettings,
  updateSettings,
  testConnection,
  testImageConnection,
  getNetProxyStatus,
} from '../api/endpoints';
import type { NetProxyStatus } from '../api/endpoints';
import type { SettingsOut, ConnectionTestOut } from '../api/types';
import PageHeader from '../components/PageHeader';
import { useAppTheme } from '../theme/ThemeContext';
import { useAuth } from '../auth/AuthContext';
import type { ThemeMode } from '../theme/ThemeContext';
import {
  getUsageSummary,
  getUsageBalance,
  updateUsagePrice,
  TASK_LABELS,
  type UsageSummary,
  type BalanceInfo,
} from '../api/usage';

const { Text } = Typography;
const { useBreakpoint } = Grid;

const COLOR_PRESETS = [
  { label: '主题色',
    colors: ['#f5a623', '#52c41a', '#1677ff', '#eb2f96', '#722ed1', '#13c2c2'] },
];

const COLOR_NAMES: Record<string, string> = {
  '#f5a623': '暖橙',
  '#52c41a': '抹茶绿',
  '#1677ff': '湖蓝',
  '#eb2f96': '莓红',
  '#722ed1': '葡萄紫',
  '#13c2c2': '深青',
};

interface Props {
  onLoggedOut: () => void;
}

// ---- AI 用量卡片 ----
function UsageCard() {
  const { isAdmin } = useAuth();
  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [balance, setBalance] = useState<BalanceInfo | null>(null);
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [priceForm] = Form.useForm<{ input_per_1k: number; output_per_1k: number; currency: string }>();
  const [priceSaving, setPriceSaving] = useState(false);
  const [recentOpen, setRecentOpen] = useState(false);

  const loadUsage = useCallback(() => {
    setUsageLoading(true);
    getUsageSummary()
      .then((d) => {
        setUsage(d);
        priceForm.setFieldsValue({
          input_per_1k: d.price.input_per_1k,
          output_per_1k: d.price.output_per_1k,
          currency: d.price.currency,
        });
      })
      .catch(() => {/* ignore */})
      .finally(() => setUsageLoading(false));
  }, [priceForm]);

  useEffect(() => { loadUsage(); }, [loadUsage]);

  async function handleRefreshBalance() {
    setBalanceLoading(true);
    try {
      const b = await getUsageBalance();
      setBalance(b);
    } catch {
      /* error shown by interceptor */
    } finally {
      setBalanceLoading(false);
    }
  }

  async function handleSavePrice(values: { input_per_1k: number; output_per_1k: number; currency: string }) {
    setPriceSaving(true);
    try {
      await updateUsagePrice({
        input_per_1k: values.input_per_1k,
        output_per_1k: values.output_per_1k,
        currency: values.currency,
      });
      message.success('单价已更新');
      loadUsage();
    } catch {
      /* error shown by interceptor */
    } finally {
      setPriceSaving(false);
    }
  }

  if (usageLoading) {
    return (
      <Card title="AI 用量" size="small" style={{ marginBottom: 20 }}>
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
    );
  }

  if (!usage) return null;

  const showCost = !(usage.price.input_per_1k === 0 && usage.price.output_per_1k === 0);
  const statsData = usage.scope === 'all' ? usage.month : usage.mine_month;
  const todayData = usage.today;
  const currency = usage.price.currency || 'USD';

  // ECharts daily bar
  const dailyDates = usage.daily.slice(-30).map((d) => d.date.slice(5)); // MM-DD
  const dailyCalls = usage.daily.slice(-30).map((d) => d.calls);

  const chartOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { show: false },
    xAxis: {
      type: 'category',
      data: dailyDates,
      axisLabel: {
        color: token.colorTextTertiary,
        fontSize: 10,
        interval: 0,
        rotate: dailyDates.length > 14 ? 40 : 0,
        hideOverlap: true,
      },
      axisLine: { lineStyle: { color: token.colorBorderSecondary } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: token.colorTextTertiary, fontSize: 10 },
      splitLine: { lineStyle: { color: token.colorBorderSecondary } },
    },
    series: [
      {
        type: 'bar',
        data: dailyCalls,
        itemStyle: { color: token.colorPrimary, borderRadius: [3, 3, 0, 0] },
        name: '调用次数',
      },
    ],
    grid: { left: 8, right: 8, top: 12, bottom: 44, containLabel: true },
  };

  const taskColumns = [
    {
      title: '任务',
      key: 'task',
      render: (_: unknown, r: { task: string; calls: number; tokens: number }) =>
        TASK_LABELS[r.task] ?? r.task,
    },
    { title: '调用', dataIndex: 'calls', key: 'calls', width: 70 },
    { title: 'Tokens', dataIndex: 'tokens', key: 'tokens', width: 90 },
  ];

  const userColumns = [
    { title: '用户', dataIndex: 'username', key: 'username' },
    { title: '调用', dataIndex: 'calls', key: 'calls', width: 70 },
    { title: 'Tokens', dataIndex: 'tokens', key: 'tokens', width: 90 },
  ];

  const recentColumns = [
    {
      title: '时间', key: 'ts', width: 90,
      render: (_: unknown, r: { created_at: string }) => dayjs(r.created_at).format('MM-DD HH:mm'),
    },
    {
      title: '任务', key: 'task', width: 90,
      render: (_: unknown, r: { task: string }) => TASK_LABELS[r.task] ?? r.task,
    },
    { title: '模型', dataIndex: 'model', key: 'model', ellipsis: true },
    { title: 'Prompt', dataIndex: 'prompt_tokens', key: 'pt', width: 70 },
    { title: 'Compl', dataIndex: 'completion_tokens', key: 'ct', width: 70 },
    { title: '耗时', key: 'lat', width: 70, render: (_: unknown, r: { latency_ms: number }) => `${r.latency_ms} ms` },
    {
      title: '状态', key: 'ok', width: 60,
      render: (_: unknown, r: { ok: boolean; error: string | null }) =>
        r.ok ? <Tag color="green">成功</Tag> : <Tooltip title={r.error}><Tag color="red">失败</Tag></Tooltip>,
    },
  ];

  return (
    <Card
      title="AI 用量"
      size="small"
      style={{ marginBottom: 20 }}
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={loadUsage} loading={usageLoading}>
          刷新
        </Button>
      }
    >
      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Statistic title="今日调用" value={todayData.calls} />
        <Statistic title="本月调用" value={statsData.calls} />
        <Statistic
          title="本月 Tokens"
          value={statsData.total_tokens}
          formatter={(v) => Number(v).toLocaleString()}
        />
        {showCost ? (
          <Statistic
            title={`本月估算费用 (${currency})`}
            value={statsData.est_cost}
            precision={4}
            prefix={currency === 'CNY' ? '¥' : '$'}
          />
        ) : (
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>本月估算费用</Text>
            <div style={{ fontSize: 12, color: token.colorTextTertiary, marginTop: 4 }}>
              管理员可在下方设置单价
            </div>
          </div>
        )}
      </div>

      {/* Daily bar */}
      {usage.daily.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>近 30 天调用量</Text>
          <ReactECharts
            option={chartOption}
            style={{ height: 120 }}
            theme={resolved === 'dark' ? 'dark' : undefined}
          />
        </div>
      )}

      {/* By task */}
      {usage.by_task.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>按任务类型</Text>
          <Table
            dataSource={usage.by_task}
            columns={taskColumns}
            rowKey="task"
            size="small"
            pagination={false}
            style={{ fontSize: 12 }}
          />
        </div>
      )}

      {/* Admin: by user */}
      {isAdmin && usage.by_user && usage.by_user.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>按用户</Text>
          <Table
            dataSource={usage.by_user}
            columns={userColumns}
            rowKey="username"
            size="small"
            pagination={false}
            style={{ fontSize: 12 }}
          />
        </div>
      )}

      {/* Admin: balance */}
      {isAdmin && (
        <div style={{ marginBottom: 16 }}>
          <Button
            size="small"
            icon={<WalletOutlined />}
            loading={balanceLoading}
            onClick={handleRefreshBalance}
          >
            刷新余额
          </Button>
          {balance && (
            <div style={{ marginTop: 8 }}>
              {balance.ok && balance.balances ? (
                balance.balances.map((b) => (
                  <Tag key={b.currency} style={{ margin: '2px 4px 2px 0' }}>
                    {b.currency}: 总 {b.total} | 赠 {b.granted} | 充 {b.topped_up}
                  </Tag>
                ))
              ) : (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>{balance.message ?? '余额查询不可用'}</Text>
                  {balance.console_url && (
                    <Button
                      type="link"
                      size="small"
                      href={balance.console_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ padding: '0 4px' }}
                    >
                      在控制台查看
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Admin: price editor */}
      {isAdmin && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>AI 单价设置（用于估算费用）</Text>
          <Form form={priceForm} layout="inline" onFinish={handleSavePrice} size="small">
            <Form.Item name="input_per_1k" label="输入 /1K tokens">
              <InputNumber min={0} step={0.0001} precision={4} style={{ width: 110 }} />
            </Form.Item>
            <Form.Item name="output_per_1k" label="输出 /1K tokens">
              <InputNumber min={0} step={0.0001} precision={4} style={{ width: 110 }} />
            </Form.Item>
            <Form.Item name="currency" label="货币">
              <Input style={{ width: 60 }} placeholder="USD" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={priceSaving}>保存单价</Button>
            </Form.Item>
          </Form>
        </div>
      )}

      {/* Recent calls */}
      {usage.recent.length > 0 && (
        <Collapse
          ghost
          size="small"
          items={[{
            key: 'recent',
            label: <Text type="secondary" style={{ fontSize: 12 }}>最近调用记录（{usage.recent.length} 条）</Text>,
            children: (
              <Table
                dataSource={usage.recent}
                columns={recentColumns}
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ x: true }}
                style={{ fontSize: 12 }}
              />
            ),
          }]}
        />
      )}
    </Card>
  );
}

export default function SettingsPage({ onLoggedOut }: Props) {
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestOut | null>(null);
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const { mode, primary, compact, setMode, setPrimary, setCompact } = useAppTheme();

  // 表单字段
  const [provider, setProvider] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [textModel, setTextModel] = useState('');
  const [fastModel, setFastModel] = useState('');
  const [visionModel, setVisionModel] = useState('');
  const [imageModel, setImageModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [visionAsync, setVisionAsync] = useState(false);
  const [netProxyMode, setNetProxyMode] = useState<'auto' | 'on' | 'off'>('auto');
  const [proxyStatus, setProxyStatus] = useState<NetProxyStatus | null>(null);
  const [proxyChecking, setProxyChecking] = useState(false);
  const [barcodeSources, setBarcodeSources] = useState<string[]>([]);
  const [dishAiImages, setDishAiImages] = useState(false);
  // 生图专用 API（v0.8.6）
  const [imageProvider, setImageProvider] = useState('senseaudio');
  const [imageBaseUrl, setImageBaseUrl] = useState('');
  const [imageModelId, setImageModelId] = useState('');
  const [imageApiKey, setImageApiKey] = useState('');
  const [imageSize, setImageSize] = useState('1024x1024');
  const [imageEmojiFallback, setImageEmojiFallback] = useState(true);
  const [imageTesting, setImageTesting] = useState(false);
  const [imageTestResult, setImageTestResult] = useState<ConnectionTestOut | null>(null);
  const [imageSaving, setImageSaving] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  async function loadSettings() {
    setLoading(true);
    try {
      const s = await getSettings();
      setSettings(s);
      setProvider(s.provider);
      setBaseUrl(s.base_url);
      setTextModel(s.text_model);
      setFastModel(s.fast_model ?? '');
      setVisionModel(s.vision_model);
      setImageModel(s.image_model ?? '');
      setVisionAsync(Boolean(s.vision_async));
      setNetProxyMode(((s.net_proxy_mode as 'auto' | 'on' | 'off') ?? 'auto'));
      const opts = Object.keys(s.barcode_source_options ?? {});
      const chosen = (s.barcode_sources || '').split(',').map((x) => x.trim()).filter(Boolean);
      setBarcodeSources(chosen.length ? chosen : opts);
      setDishAiImages(Boolean(s.dish_ai_images));
      // 生图专用 API
      setImageProvider(s.image_provider || 'senseaudio');
      setImageBaseUrl(s.image_base_url || '');
      setImageModelId(s.image_model_id || '');
      setImageSize(s.image_size || '1024x1024');
      setImageEmojiFallback(s.image_emoji_fallback !== false);
      setImageApiKey('');
    } finally {
      setLoading(false);
    }
  }

  /** 从 settings.image_providers 数组里取当前提供方 */
  function currentProviderInfo(list: SettingsOut | null, id: string) {
    return (list?.image_providers ?? []).find((p) => p.id === id);
  }

  /** 切换生图提供商：带出 base_url 与首个模型、该模型的默认尺寸 */
  function handleImageProviderChange(v: string) {
    setImageProvider(v);
    const p = currentProviderInfo(settings, v);
    if (p) {
      setImageBaseUrl(p.base_url);
      const m = p.models?.[0];
      setImageModelId(m?.id ?? '');
      setImageSize(m?.sizes?.[0] ?? '1024x1024');
    }
    setImageTestResult(null);
  }

  /** 切换生图模型：同步其支持的尺寸清单 */
  function handleImageModelChange(modelId: string) {
    setImageModelId(modelId);
    const p = currentProviderInfo(settings, imageProvider);
    const m = p?.models?.find((x) => x.id === modelId);
    if (m?.sizes?.length) setImageSize(m.sizes[0]);
    setImageTestResult(null);
  }

  async function handleSaveImageApi() {
    setImageSaving(true);
    try {
      const updated = await updateSettings({
        image_provider: imageProvider,
        image_base_url: imageBaseUrl,
        image_model_id: imageModelId,
        image_size: imageSize,
        image_emoji_fallback: imageEmojiFallback,
        image_api_key: imageApiKey || undefined,
      });
      setSettings(updated);
      setImageApiKey('');
      message.success('生图 API 已保存');
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setImageSaving(false);
    }
  }

  async function handleClearImageKey() {
    setImageSaving(true);
    try {
      const updated = await updateSettings({ image_api_key: '__clear__' });
      setSettings(updated);
      message.success('生图密钥已清除');
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setImageSaving(false);
    }
  }

  async function handleTestImage() {
    setImageTesting(true);
    setImageTestResult(null);
    try {
      setImageTestResult(await testImageConnection());
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setImageTesting(false);
    }
  }

  function handleProviderChange(v: string) {
    setProvider(v);
    if (settings?.presets?.[v]) {
      const preset = settings.presets[v];
      setBaseUrl(preset.base_url);
      setTextModel(preset.text_model);
      setFastModel(preset.fast_model ?? '');
      setVisionModel(preset.vision_model);
    }
    setTestResult(null);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await updateSettings({
        provider,
        base_url: baseUrl,
        text_model: textModel,
        fast_model: fastModel || undefined,
        vision_model: visionModel,
        image_model: imageModel || undefined,
        vision_async: visionAsync,
        net_proxy_mode: netProxyMode,
        barcode_sources: barcodeSources.join(','),
        dish_ai_images: dishAiImages,
        api_key: apiKey || undefined,
      });
      setSettings(updated);
      setApiKey('');
      message.success('设置已保存');
    } finally {
      setSaving(false);
    }
  }

  async function handleClearKey() {
    setSaving(true);
    try {
      const updated = await updateSettings({ api_key: '__clear__' });
      setSettings(updated);
      message.success('密钥已清除');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testConnection();
      setTestResult(res);
    } finally {
      setTesting(false);
    }
  }

  async function handleCheckProxy() {
    setProxyChecking(true);
    try {
      setProxyStatus(await getNetProxyStatus(true));
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setProxyChecking(false);
    }
  }

  if (loading) {
    return (
      <div>
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
        <Skeleton active paragraph={{ rows: 3 }} />
      </div>
    );
  }

  if (!settings) return null;

  const canEdit = settings.can_edit;
  const isMock = provider === 'mock';
  // 生图提供方 / 模型派生（供下拉与尺寸联动）
  const imageProviderInfo = currentProviderInfo(settings, imageProvider);
  const currentModelInfo = (imageProviderInfo?.models ?? []).find((m) => m.id === imageModelId);
  const providerOptions = Object.entries(settings.presets).map(([key, val]) => ({
    label: val.label,
    value: key,
  }));

  const sourceLabel =
    settings.source === 'env'
      ? '来自环境变量'
      : settings.source === 'db'
      ? '来自数据库'
      : '混合（env + db）';

  return (
    <div>
      <PageHeader title="模型设置" subtitle="模型配置与 AI 用量" />
      <div className="page-title">模型设置</div>

      {/* AI 用量卡片 */}
      <UsageCard />

      {/* 外观设置卡片 */}
      <Card
        title="外观"
        size="small"
        style={{ marginBottom: 20, maxWidth: 600 }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              显示模式
            </Text>
            <Segmented
              options={[
                { label: '☀️ 浅色', value: 'light' },
                { label: '🌙 深色', value: 'dark' },
                { label: '🖥 跟随系统', value: 'system' },
              ]}
              value={mode}
              onChange={(v) => setMode(v as ThemeMode)}
              block={isMobile}
            />
          </div>

          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              主题色
            </Text>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              {Object.entries(COLOR_NAMES).map(([hex, name]) => (
                <div
                  key={hex}
                  onClick={() => setPrimary(hex)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    cursor: 'pointer',
                    padding: '4px 8px',
                    borderRadius: 6,
                    border: `2px solid ${primary === hex ? token.colorPrimary : token.colorBorderSecondary}`,
                    background: primary === hex ? token.colorPrimaryBg : token.colorBgContainer,
                    fontSize: 12,
                  }}
                >
                  <div style={{
                    width: 14,
                    height: 14,
                    borderRadius: '50%',
                    background: hex,
                    flexShrink: 0,
                  }} />
                  {name}
                </div>
              ))}
              <ColorPicker
                value={primary}
                presets={COLOR_PRESETS}
                onChange={(_, hex) => setPrimary(hex)}
                size="small"
              />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Switch
              size="small"
              checked={compact}
              onChange={setCompact}
            />
            <Text style={{ fontSize: 13 }}>紧凑模式</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>（减小间距，显示更多内容）</Text>
          </div>
        </div>
      </Card>

      {/* 网络加速（海外请求代理） */}
      <Card title="网络加速" size="small" style={{ marginBottom: 20, maxWidth: 600 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          服务器位于中国大陆时，维基百科等海外图片/数据请求可能无法直连。开启后将自动为这些请求加前缀代理
          （{settings.net_proxy_url}）。
        </Text>
        <Segmented
          options={[
            { label: '自动检测', value: 'auto' },
            { label: '强制开启', value: 'on' },
            { label: '关闭', value: 'off' },
          ]}
          value={netProxyMode}
          onChange={(v) => setNetProxyMode(v as 'auto' | 'on' | 'off')}
          disabled={!canEdit}
          block={isMobile}
        />
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Button size="small" onClick={handleCheckProxy} loading={proxyChecking} disabled={!canEdit}>
            检测是否位于大陆
          </Button>
          {proxyStatus && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {proxyStatus.detected === null
                ? '未探测到结果'
                : proxyStatus.detected
                ? '疑似位于中国大陆，加速已生效'
                : '可直连海外，未启用加速'}
              （当前：{proxyStatus.enabled ? '已启用' : '未启用'}）
            </Text>
          )}
        </div>
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
          仅管理员可修改；选择“自动检测”时，系统会在首次需要时探测一次并缓存 10 分钟。
        </Text>
      </Card>

      {/* 条码数据源（并行查询） */}
      <Card title="条码数据源" size="small" style={{ marginBottom: 20, maxWidth: 600 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          扫码后会【并行】查询所有勾选的数据源，并按名称/品牌/营养/图片的完整度自动选最贴切的结果；
          未命中的数据源不会展示。内置常见商品表始终参与。
        </Text>
        <Checkbox.Group
          options={Object.entries(settings.barcode_source_options ?? {}).map(([k, label]) => ({
            label,
            value: k,
          }))}
          value={barcodeSources}
          onChange={(vals) => setBarcodeSources(vals as string[])}
          disabled={!canEdit}
          style={{ display: 'grid', gap: 6 }}
        />
      </Card>

      {/* 菜品配图 */}
      <Card title="菜品配图" size="small" style={{ marginBottom: 20, maxWidth: 640 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Switch
            size="small"
            checked={dishAiImages}
            onChange={setDishAiImages}
            disabled={!canEdit}
          />
          <Text style={{ fontSize: 13 }}>启用 AI 生图</Text>
          <Tag color={settings.image_ready ? 'green' : 'default'}>
            {settings.image_ready ? '配置就绪' : '未配置'}
          </Tag>
        </div>
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
          开启后，生成餐单时优先用生图模型为每道菜生成统一风格的配图（中餐识别更准）；
          生图失败的菜品退回 emoji 兜底，不会出现空白。关闭时依次使用
          网络图库（维基百科 / 维基共享 / 百度百科等）与 emoji 兜底。
        </Text>

        <Divider style={{ margin: '14px 0 12px' }} />

        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>
          生图 API（可独立于文字 / 识图模型配置）
        </div>

        <Form layout="vertical" size="small">
          <Form.Item label="生图服务提供方">
            <Select
              value={imageProvider}
              onChange={handleImageProviderChange}
              disabled={!canEdit}
              options={(settings.image_providers ?? []).map((p) => ({
                label: p.label,
                value: p.id,
              }))}
            />
          </Form.Item>

          <Form.Item
            label="生图 API 基础地址"
            help="商汤 SenseAudio 填 https://api.senseaudio.cn；OpenAI 兼容接口填 /v1 结尾的地址"
          >
            <Input
              value={imageBaseUrl}
              onChange={(e) => setImageBaseUrl(e.target.value)}
              placeholder="https://api.senseaudio.cn"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item
            label="生图模型"
            help={
              (imageProviderInfo?.models ?? []).length
                ? undefined
                : '自定义接口无预设模型，请手动填写模型 id'
            }
          >
            {(imageProviderInfo?.models ?? []).length ? (
              <Select
                value={imageModelId || undefined}
                onChange={handleImageModelChange}
                disabled={!canEdit}
                placeholder="请选择生图模型"
                options={(imageProviderInfo?.models ?? []).map((m) => ({
                  label: m.label,
                  value: m.id,
                }))}
              />
            ) : (
              <Input
                value={imageModelId}
                onChange={(e) => setImageModelId(e.target.value)}
                placeholder="如 dall-e-3 / flux-schnell"
                disabled={!canEdit}
              />
            )}
          </Form.Item>

          <Form.Item
            label="生成尺寸"
            help="尺寸越大约耗时越贵；菜品缩略图场景 1024×1024 已足够"
          >
            {(currentModelInfo?.sizes ?? []).length ? (
              <Select
                value={imageSize}
                onChange={setImageSize}
                disabled={!canEdit}
                showSearch
                options={(currentModelInfo?.sizes ?? []).map((s) => ({ label: s, value: s }))}
              />
            ) : (
              <Input
                value={imageSize}
                onChange={(e) => setImageSize(e.target.value)}
                placeholder="1024x1024"
                disabled={!canEdit}
              />
            )}
          </Form.Item>

          {canEdit && (
            <Form.Item
              label={
                <span>
                  生图 API 密钥
                  {settings.has_image_key && (
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                      当前：{settings.image_key_masked}
                    </Text>
                  )}
                </span>
              }
            >
              <Input.Password
                value={imageApiKey}
                onChange={(e) => setImageApiKey(e.target.value)}
                placeholder={settings.has_image_key ? '留空表示不修改' : '请输入生图 API 密钥'}
                visibilityToggle
              />
              {settings.has_image_key && (
                <Button
                  size="small"
                  danger
                  style={{ marginTop: 6 }}
                  onClick={handleClearImageKey}
                  loading={imageSaving}
                >
                  清除生图密钥
                </Button>
              )}
            </Form.Item>
          )}

          <Form.Item
            label="无图时用 Emoji 兜底"
            help="推荐开启：生图未配置 / 已关闭 / 触发限流时，菜品卡片显示语义贴切的 emoji（Twemoji 渲染，跨端风格统一），永不空白。"
          >
            <Switch
              size="small"
              checked={imageEmojiFallback}
              onChange={setImageEmojiFallback}
              disabled={!canEdit}
            />
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              {imageEmojiFallback ? '已开启' : '已关闭'}
            </Text>
          </Form.Item>

          {canEdit && (
            <Form.Item>
              <Space wrap>
                <Button
                  type="primary"
                  size="small"
                  icon={<SaveOutlined />}
                  onClick={handleSaveImageApi}
                  loading={imageSaving}
                >
                  保存生图 API
                </Button>
                <Button
                  size="small"
                  icon={<ApiOutlined />}
                  onClick={handleTestImage}
                  loading={imageTesting}
                  disabled={!settings.image_ready}
                >
                  测试生图
                </Button>
              </Space>
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 6 }}>
                测试会真实生成一张小图，约 5~30 秒；未保存的密钥需先保存再测试。
              </Text>
            </Form.Item>
          )}
        </Form>

        {imageTestResult && (
          <Alert
            type={imageTestResult.ok ? 'success' : 'error'}
            showIcon
            message={imageTestResult.ok ? '生图 API 可用' : '生图 API 不可用'}
            description={
              <div>
                {imageTestResult.message}
                {imageTestResult.latency_ms !== undefined && (
                  <span style={{ marginLeft: 12, fontSize: 12, color: token.colorTextSecondary }}>
                    耗时 {imageTestResult.latency_ms} ms
                  </span>
                )}
                {imageTestResult.model && (
                  <span style={{ marginLeft: 12, fontSize: 12, color: token.colorTextSecondary }}>
                    模型: {imageTestResult.model}
                  </span>
                )}
              </div>
            }
            style={{ marginTop: 8 }}
          />
        )}
      </Card>

      <div className="content-card settings-form">
        {!canEdit && (
          <Alert
            type="info"
            showIcon
            message="模型 API 由管理员统一配置"
            description="当前账号无权修改模型设置，如需调整请联系管理员。外观和账户安全仍可自行设置。"
            style={{ marginBottom: 20 }}
          />
        )}

        {isMock && (
          <Alert
            type="info"
            showIcon
            message="离线演示模式"
            description="当前使用 mock 模型，识别结果为示例数据，与照片内容无关。配置真实 API 密钥后切换 provider 即可使用 AI 识别。"
            style={{ marginBottom: 20 }}
          />
        )}

        <div style={{ marginBottom: 8, fontSize: 12, color: token.colorTextSecondary }}>
          配置来源：<Tag>{sourceLabel}</Tag>
          密钥只保存在后端 SQLite / .env 中，前端仅显示掩码。
        </div>

        <Divider />

        <Form layout="vertical">
          <Form.Item label="服务提供方">
            <Select
              value={provider}
              onChange={handleProviderChange}
              options={providerOptions}
              style={{ width: '100%' }}
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item label="API 基础地址 (base_url)">
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item
            label="文字模型（质量优先：周报、餐单）(text_model)"
          >
            <Input
              value={textModel}
              onChange={(e) => setTextModel(e.target.value)}
              placeholder="gpt-4o-mini"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item
            label="快速模型 (fast_model)"
            help="用于查询规划、结果解释、记忆抽取、分享文案等短任务；留空则与文字模型相同"
          >
            <Input
              value={fastModel}
              onChange={(e) => setFastModel(e.target.value)}
              placeholder="留空则与文字模型相同"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item label="视觉模型 (vision_model)">
            <Input
              value={visionModel}
              onChange={(e) => setVisionModel(e.target.value)}
              placeholder="gpt-4o"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item
            label="菜品配图模型 (image_model)"
            help="旧配置项，保留兼容：走主 API 的 images.generate。新部署请改用下方「菜品配图 → 生图 API」，可独立配置提供方与密钥。留空则本项不生效。"
          >
            <Input
              value={imageModel}
              onChange={(e) => setImageModel(e.target.value)}
              placeholder="留空则不生成配图"
              disabled={!canEdit}
            />
          </Form.Item>

          <Form.Item label="图片分析后台异步处理" help="默认关闭；开启后图片识别会在后台处理并在完成后通知，适合识图耗时较长的模型。">
            <Switch checked={visionAsync} onChange={setVisionAsync} disabled={!canEdit} />
            <Text type="secondary" style={{ marginLeft: 8 }}>{visionAsync ? '已开启' : '默认关闭'}</Text>
          </Form.Item>

          {canEdit && (
            <Form.Item
              label={
                <span>
                  API 密钥
                  {settings.has_api_key && (
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                      当前：{settings.api_key_masked}
                    </Text>
                  )}
                </span>
              }
            >
              <Input.Password
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={settings.has_api_key ? '留空表示不修改' : '请输入 API 密钥'}
                visibilityToggle
              />
              {settings.has_api_key && (
                <Button
                  size="small"
                  danger
                  style={{ marginTop: 6 }}
                  onClick={handleClearKey}
                  loading={saving}
                >
                  清除密钥
                </Button>
              )}
            </Form.Item>
          )}

          {canEdit && (
            <Form.Item>
              <Space wrap>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={handleSave}
                  loading={saving}
                >
                  保存设置
                </Button>
                <Button
                  icon={<ApiOutlined />}
                  onClick={handleTest}
                  loading={testing}
                >
                  测试连接
                </Button>
              </Space>
            </Form.Item>
          )}
        </Form>
        {testResult && (
          <Alert
            type={testResult.ok ? 'success' : 'error'}
            showIcon
            message={testResult.ok ? '连接成功' : '连接失败'}
            description={
              <div>
                {testResult.message}
                {testResult.latency_ms !== undefined && (
                  <span style={{ marginLeft: 12, fontSize: 12, color: token.colorTextSecondary }}>
                    耗时 {testResult.latency_ms} ms
                  </span>
                )}
                {testResult.model && (
                  <span style={{ marginLeft: 12, fontSize: 12, color: token.colorTextSecondary }}>
                    模型: {testResult.model}
                  </span>
                )}
              </div>
            }
            style={{ marginTop: 8 }}
          />
        )}
      </div>
    </div>
  );
}

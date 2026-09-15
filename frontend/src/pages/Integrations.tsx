import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
  theme as antdTheme,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  InboxOutlined,
  KeyOutlined,
  PlusOutlined,
  ReloadOutlined,
  MobileOutlined,
  BellOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { UploadFile } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import { getDataSummary, importData } from '../api/data';
import type { DataSummary, ImportResult } from '../api/data';
import { listTokens, createToken, revokeToken } from '../api/tokens';
import type { TokenOut, TokenCreated } from '../api/tokens';
import client from '../api/client';
import { isNativeApp, nativeInfo, registerDeviceNative, getBatteryStatusNative, requestIgnoreBatteryNative } from '../native/bridge';
import PageHeader from '../components/PageHeader';

const { Text, Paragraph } = Typography;
const { Dragger } = Upload;

// ---- Tab 1: 数据导入导出 ----
function DataTab() {
  const { token } = antdTheme.useToken();
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null]>([null, null]);
  const [importMode, setImportMode] = useState<'merge' | 'replace'>('merge');
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [confirmText, setConfirmText] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    getDataSummary().then(setSummary).catch(() => {/* ignore */}).finally(() => setSummaryLoading(false));
  }, []);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  function buildExportUrl(format: string) {
    const params = new URLSearchParams({ format });
    if (dateRange[0]) params.set('from', dateRange[0].format('YYYY-MM-DD'));
    if (dateRange[1]) params.set('to', dateRange[1].format('YYYY-MM-DD'));
    return `/api/data/export?${params.toString()}`;
  }

  async function doImport() {
    const file = fileList[0]?.originFileObj as File | undefined;
    if (!file) { message.warning('请选择文件'); return; }
    setImporting(true);
    setImportResult(null);
    try {
      const result = await importData(file, importMode);
      setImportResult(result);
      message.success(`导入完成：${result.imported} 条已导入`);
      setFileList([]);
      loadSummary();
    } catch {
      /* error shown by interceptor */
    } finally {
      setImporting(false);
      setShowConfirm(false);
      setConfirmText('');
    }
  }

  function handleImportClick() {
    if (importMode === 'replace') {
      setShowConfirm(true);
    } else {
      doImport();
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {/* Summary */}
      <Card size="small" title="数据概览" extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadSummary} loading={summaryLoading}>刷新</Button>}>
        {summary ? (
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="餐食记录">{summary.meals} 条</Descriptions.Item>
            <Descriptions.Item label="菜品明细">{summary.items} 条</Descriptions.Item>
            <Descriptions.Item label="标签数">{summary.tags} 个</Descriptions.Item>
            <Descriptions.Item label="报告数">{summary.reports} 份</Descriptions.Item>
          </Descriptions>
        ) : <Spin size="small" />}
      </Card>

      {/* Export */}
      <Card size="small" title="导出数据">
        <Space wrap>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(v) => setDateRange(v ? [v[0], v[1]] : [null, null])}
            format="YYYY-MM-DD"
            placeholder={['开始日期（可选）', '结束日期（可选）']}
          />
        </Space>
        <div style={{ marginTop: 12, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <a href={buildExportUrl('json')} download>
            <Button icon={<DownloadOutlined />}>导出 JSON</Button>
          </a>
          <a href={buildExportUrl('csv')} download>
            <Button icon={<DownloadOutlined />}>导出 CSV</Button>
          </a>
          <a href={buildExportUrl('zip')} download>
            <Button icon={<DownloadOutlined />}>导出 ZIP（含图片）</Button>
          </a>
          <a href="/api/data/template.csv" download>
            <Button size="small">下载 CSV 模板</Button>
          </a>
        </div>
      </Card>

      {/* Import */}
      <Card size="small" title="导入数据">
        <Alert
          type="info"
          showIcon
          message="支持 .json、.csv、.zip 格式，文件不超过 50MB"
          style={{ marginBottom: 12 }}
        />
        <Dragger
          accept=".json,.csv,.zip"
          multiple={false}
          fileList={fileList}
          beforeUpload={() => false}
          onChange={({ fileList: fl }) => setFileList(fl.slice(-1))}
          style={{ marginBottom: 12 }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p>点击或拖拽文件到此处</p>
        </Dragger>

        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            导入模式
          </Text>
          <Radio.Group value={importMode} onChange={(e) => setImportMode(e.target.value)}>
            <Radio value="merge">合并（跳过重复）</Radio>
            <Radio value="replace">替换（清空所有数据后导入）</Radio>
          </Radio.Group>
        </div>

        <Button
          type="primary"
          onClick={handleImportClick}
          loading={importing}
          disabled={fileList.length === 0}
        >
          开始导入
        </Button>

        {importResult && (
          <Alert
            type={importResult.errors.length > 0 ? 'warning' : 'success'}
            showIcon
            style={{ marginTop: 12 }}
            message={`已导入 ${importResult.imported} 条，跳过 ${importResult.skipped} 条`}
            description={
              importResult.errors.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {importResult.errors.slice(0, 5).map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              ) : undefined
            }
          />
        )}
      </Card>

      {/* Replace confirm modal */}
      <Modal
        open={showConfirm}
        title="确认替换导入"
        onCancel={() => { setShowConfirm(false); setConfirmText(''); }}
        onOk={doImport}
        okButtonProps={{ danger: true, disabled: confirmText !== '确认' }}
        okText="确认替换"
        confirmLoading={importing}
      >
        <Alert
          type="error"
          showIcon
          message="替换模式将清空您当前所有餐食数据，此操作不可恢复。"
          style={{ marginBottom: 12 }}
        />
        <Text>请输入「确认」以继续：</Text>
        <Input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder="确认"
          style={{ marginTop: 8 }}
        />
      </Modal>
    </Space>
  );
}

// ---- Tab 2: 访问令牌 ----
function TokensTab() {
  const { token } = antdTheme.useToken();
  const [tokens, setTokens] = useState<TokenOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newToken, setNewToken] = useState<TokenCreated | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(() => {
    setLoading(true);
    listTokens().then(setTokens).catch(() => {/* ignore */}).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate(values: { name: string; scopes: string; expires_days?: number }) {
    try {
      const created = await createToken({
        name: values.name.trim(),
        scopes: values.scopes as 'all' | 'read' | 'mcp' | 'app',
        expires_days: values.expires_days || undefined,
      });
      setNewToken(created);
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleRevoke(id: number) {
    try {
      await revokeToken(id);
      message.success('令牌已撤销');
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  const columns: ColumnsType<TokenOut> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '前缀', dataIndex: 'prefix', key: 'prefix', width: 110,
      render: (v: string) => <code>{v}…</code>,
    },
    {
      title: '权限', dataIndex: 'scopes', key: 'scopes', width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '最近使用', key: 'last_used_at', width: 130,
      render: (_, t) => t.last_used_at ? dayjs(t.last_used_at).format('MM-DD HH:mm') : '—',
    },
    {
      title: '过期时间', key: 'expires_at', width: 130,
      render: (_, t) => t.expires_at ? dayjs(t.expires_at).format('YYYY-MM-DD') : '永不过期',
    },
    {
      title: '创建时间', key: 'created_at', width: 110,
      render: (_, t) => dayjs(t.created_at).format('MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, t) => (
        <Popconfirm title="确定撤销此令牌？" onConfirm={() => handleRevoke(t.id)}>
          <Button size="small" danger icon={<DeleteOutlined />}>撤销</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建令牌
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={tokens}
        rowKey="id"
        loading={loading}
        size="small"
        scroll={{ x: true }}
        pagination={{ pageSize: 10 }}
      />

      {/* Create token modal */}
      <Modal
        open={createOpen}
        title="新建访问令牌"
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        onOk={() => form.submit()}
        okText="创建"
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="令牌名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：Claude Desktop" />
          </Form.Item>
          <Form.Item name="scopes" label="权限范围" initialValue="all">
            <Select
              options={[
                { label: '全部（all）', value: 'all' },
                { label: '只读（read）', value: 'read' },
                { label: 'MCP 用（mcp）', value: 'mcp' },
                { label: 'App 用（app）', value: 'app' },
              ]}
            />
          </Form.Item>
          <Form.Item name="expires_days" label="有效期（天，留空表示永不过期）">
            <InputNumber min={1} max={3650} style={{ width: 180 }} placeholder="留空" />
          </Form.Item>
        </Form>
      </Modal>

      {/* New token display */}
      <Modal
        open={!!newToken}
        title="令牌已创建（请妥善保存，只显示这一次）"
        onOk={() => setNewToken(null)}
        onCancel={() => setNewToken(null)}
        cancelButtonProps={{ style: { display: 'none' } }}
        okText="我已保存"
        destroyOnClose
      >
        {newToken && (
          <div>
            <Alert
              type="warning"
              showIcon
              message="此令牌只显示一次，关闭后无法找回！"
              style={{ marginBottom: 12 }}
            />
            <Paragraph
              copyable={{ text: newToken.token }}
              style={{ fontFamily: 'monospace', wordBreak: 'break-all', background: token.colorFillAlter, padding: 12, borderRadius: 6 }}
            >
              {newToken.token}
            </Paragraph>
          </div>
        )}
      </Modal>
    </Space>
  );
}

// ---- Tab 3: MCP 接入 ----
function McpTab() {
  const { token } = antdTheme.useToken();
  const [info, setInfo] = useState<{
    endpoint: string;
    transport: string;
    tools: { name: string; title: string; description: string }[];
    claude_desktop_example: unknown;
    curl_example: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.get('/api/mcp/info')
      .then((r) => setInfo(r.data as typeof info))
      .catch(() => {/* ignore */})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  if (!info) return <Alert type="error" message="加载 MCP 信息失败" />;

  const claudeJson = JSON.stringify(info.claude_desktop_example, null, 2);

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="什么是 MCP？"
        description="MCP（Model Context Protocol）是 Anthropic 提出的开放协议，让 AI 助手（如 Claude Desktop、Cursor）直接操作你的饮食日记。你需要先在「访问令牌」标签页创建一个令牌（scopes 选 mcp），然后按以下说明配置。"
      />

      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="端点地址">{info.endpoint}</Descriptions.Item>
        <Descriptions.Item label="传输协议">{info.transport}</Descriptions.Item>
      </Descriptions>

      <Divider orientation="left">Claude Desktop 配置示例</Divider>
      <div style={{ position: 'relative' }}>
        <pre style={{
          background: token.colorFillAlter,
          padding: 12,
          borderRadius: 6,
          fontSize: 11,
          overflow: 'auto',
          maxHeight: 240,
        }}>
          {claudeJson}
        </pre>
        <Button
          size="small"
          icon={<CopyOutlined />}
          style={{ position: 'absolute', top: 8, right: 8 }}
          onClick={() => {
            navigator.clipboard.writeText(claudeJson).then(() => message.success('已复制')).catch(() => {/* ignore */});
          }}
        >
          复制
        </Button>
      </div>

      <Divider orientation="left">curl 示例</Divider>
      <div style={{ position: 'relative' }}>
        <pre style={{
          background: token.colorFillAlter,
          padding: 12,
          borderRadius: 6,
          fontSize: 11,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}>
          {info.curl_example}
        </pre>
        <Button
          size="small"
          icon={<CopyOutlined />}
          style={{ position: 'absolute', top: 8, right: 8 }}
          onClick={() => {
            navigator.clipboard.writeText(info.curl_example).then(() => message.success('已复制')).catch(() => {/* ignore */});
          }}
        >
          复制
        </Button>
      </div>

      <Divider orientation="left">支持的工具（{info.tools.length} 个）</Divider>
      <Table
        dataSource={info.tools}
        rowKey="name"
        size="small"
        pagination={false}
        columns={[
          { title: '工具名', dataIndex: 'name', key: 'name', width: 160, render: (v: string) => <code>{v}</code> },
          { title: '标题', dataIndex: 'title', key: 'title', width: 120 },
          { title: '说明', dataIndex: 'description', key: 'description', ellipsis: true },
        ]}
      />
    </Space>
  );
}

// ---- Tab 4: App 与通知收件箱 ----
function AppTab() {
  const { token } = antdTheme.useToken();
  const navigate = useNavigate();
  const native = isNativeApp();
  const info = nativeInfo();
  const hasRealtimeNotify = native && typeof window.DietDiaryNative?.getRealtimeNotifications === 'function';
  const [realtimeEnabled, setRealtimeEnabled] = useState(false);
  const [realtimeLoading, setRealtimeLoading] = useState(false);
  const [batteryIgnoring, setBatteryIgnoring] = useState<boolean | null>(null);

  useEffect(() => {
    if (!hasRealtimeNotify) return;
    try {
      const raw = window.DietDiaryNative!.getRealtimeNotifications!();
      const parsed = JSON.parse(raw) as { enabled: boolean };
      setRealtimeEnabled(!!parsed.enabled);
    } catch {/* ignore */}
  }, [hasRealtimeNotify]);

  useEffect(() => {
    if (!native) return;
    const status = getBatteryStatusNative();
    if (status !== null) {
      setBatteryIgnoring(status.ignoring);
    }
  }, [native]);

  function handleRealtimeToggle(checked: boolean) {
    setRealtimeLoading(true);
    try {
      window.DietDiaryNative?.setRealtimeNotifications?.(checked);
      setRealtimeEnabled(checked);
    } catch {/* ignore */}
    setRealtimeLoading(false);
  }

  const [devices, setDevices] = useState<{
    id: number;
    device_id: string;
    name: string | null;
    platform: string;
    app_version: string | null;
    last_seen_at: string;
  }[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [registerBusy, setRegisterBusy] = useState(false);
  const [sendTestBusy, setSendTestBusy] = useState(false);

  const loadDevices = useCallback(() => {
    setDevicesLoading(true);
    client.get('/api/notify/devices')
      .then((r) => setDevices(r.data as typeof devices))
      .catch(() => {/* ignore */})
      .finally(() => setDevicesLoading(false));
  }, []);

  useEffect(() => { loadDevices(); }, [loadDevices]);

  async function handleRegisterDevice() {
    setRegisterBusy(true);
    try {
      registerDeviceNative();
      message.success('已向 App 发送注册请求');
    } finally {
      setRegisterBusy(false);
    }
  }

  async function handleDeleteDevice(id: number) {
    try {
      await client.delete(`/api/notify/devices/${id}`);
      message.success('设备已删除');
      loadDevices();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleSendTest() {
    setSendTestBusy(true);
    try {
      await client.post('/api/notify/test', { channel: 'inbox', kind: 'test' });
      message.success('测试通知已发送到收件箱');
    } catch {
      /* error shown by interceptor */
    } finally {
      setSendTestBusy(false);
    }
  }

  const deviceColumns: ColumnsType<typeof devices[0]> = [
    { title: '设备 ID', dataIndex: 'device_id', key: 'device_id', ellipsis: true },
    { title: '名称', dataIndex: 'name', key: 'name', render: (v) => v ?? '—' },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 80 },
    { title: '版本', dataIndex: 'app_version', key: 'app_version', width: 80, render: (v) => v ?? '—' },
    {
      title: '最近活跃', key: 'last_seen_at', width: 130,
      render: (_, d) => dayjs(d.last_seen_at).format('MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, d) => (
        <Popconfirm title="确定删除此设备？" onConfirm={() => handleDeleteDevice(d.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {/* Battery optimization banner */}
      {native && batteryIgnoring === false && (
        <Alert
          type="warning"
          showIcon
          message="后台通知可能被系统限制"
          description={
            <div>
              <div style={{ marginBottom: 8 }}>
                当前 App 受电池优化限制，后台推送可能无法及时送达。建议关闭电池优化，并在系统设置中允许 App 自启动/后台运行（MIUI / EMUI / ColorOS 等国产 ROM 请到「权限管理」手动开启）。
              </div>
              <Button
                size="small"
                type="primary"
                onClick={() => {
                  requestIgnoreBatteryNative();
                }}
              >
                去关闭电池优化
              </Button>
            </div>
          }
        />
      )}

      {/* Realtime notification switch */}
      {hasRealtimeNotify && (
        <Card size="small" title={<><BellOutlined /> 实时通知</>}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <Switch
              checked={realtimeEnabled}
              loading={realtimeLoading}
              onChange={handleRealtimeToggle}
            />
            <Text strong>实时通知（前台服务）</Text>
          </div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            开启后 App 将在后台保持一个低优先级的持久通知（前台服务），使通知可以立即送达。
            关闭时推送依赖系统轮询，可能延迟约 15 分钟。
          </Text>
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            message={'如遇通知不送达，请将 App 加入系统省电白名单（「不受限制」/「不优化」），以防被系统杀掉后台服务。部分国产 ROM（MIUI / EMUI / ColorOS 等）需在系统设置中手动允许后台自启动。'}
          />
        </Card>
      )}

      {/* App status */}
      <Card size="small" title={<><MobileOutlined /> App 状态</>}>
        {native ? (
          <Space wrap>
            <Tag color="green">运行在 Android App 内</Tag>
            {info && (
              <>
                <Tag>平台：{info.platform}</Tag>
                <Tag>版本：{info.appVersion}</Tag>
              </>
            )}
          </Space>
        ) : (
          <Tag color="default">浏览器访问（非 App 环境）</Tag>
        )}
        <div style={{ marginTop: 12 }}>
          <Space wrap>
            <Button
              icon={<MobileOutlined />}
              loading={registerBusy}
              disabled={!native}
              onClick={handleRegisterDevice}
            >
              注册本设备
            </Button>
            <Button
              loading={sendTestBusy}
              onClick={handleSendTest}
              title="发送测试消息到收件箱"
            >
              发送测试消息
            </Button>
            {native && (
              <Button
                onClick={() => {
                  try {
                    window.DietDiaryNative?.notify('测试通知', '来自饮食日记的测试推送');
                    message.success('本机通知已发送');
                  } catch {
                    message.error('发送失败');
                  }
                }}
              >
                本机测试通知
              </Button>
            )}
            {!native && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                在 App 内访问此页面才能注册设备
              </Text>
            )}
          </Space>
        </div>
        <Divider plain>如何安装 App</Divider>
        <Text type="secondary" style={{ fontSize: 12 }}>
          App 以 Android APK 形式通过 GitHub Actions 构建产物分发。
          请前往项目仓库的 Actions 页面，下载最新 workflow run 的 APK artifact 安装即可。
          安装后用同一账号登录，即可在 App 内扫码记餐、接收推送通知。
        </Text>
      </Card>

      {/* Devices table */}
      <Card
        size="small"
        title="已注册设备"
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadDevices} loading={devicesLoading}>刷新</Button>}
      >
        <Table
          columns={deviceColumns}
          dataSource={devices}
          rowKey="id"
          loading={devicesLoading}
          size="small"
          pagination={false}
          scroll={{ x: true }}
        />
      </Card>

      {/* Inbox link */}
      <Card
        size="small"
        title={<><BellOutlined /> 通知收件箱</>}
      >
        <div
          onClick={() => navigate('/inbox')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            cursor: 'pointer',
            padding: '8px 0',
          }}
        >
          <Text style={{ flex: 1 }}>前往消息中心查看所有通知</Text>
          <RightOutlined style={{ color: token.colorTextTertiary }} />
        </div>
      </Card>
    </Space>
  );
}

// ---- Main Integrations Page ----
export default function IntegrationsPage() {
  const tabItems = [
    { key: 'data', label: '数据导入导出', children: <DataTab /> },
    { key: 'tokens', label: '访问令牌', children: <TokensTab /> },
    { key: 'mcp', label: 'MCP 接入', children: <McpTab /> },
    { key: 'app', label: 'App 与通知收件箱', children: <AppTab /> },
  ];

  return (
    <div>
      <PageHeader title="数据与集成" subtitle="导入导出、令牌、MCP、App" />
      <div className="page-title">数据与集成</div>
      <Tabs items={tabItems} />
    </div>
  );
}

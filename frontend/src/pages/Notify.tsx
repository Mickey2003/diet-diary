import { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Switch,
  Input,
  InputNumber,
  Select,
  Button,
  Tag,
  Alert,
  Skeleton,
  Spin,
  Typography,
  TimePicker,
  Modal,
  Table,
  message,
  Tooltip,
  Tabs,
  Collapse,
  Space,
  Divider,
  Grid,
  theme as antdTheme,
} from 'antd';
import PageHeader from '../components/PageHeader';
import MealAlertSettings from '../components/MealAlertSettings';
import { ReloadOutlined, SendOutlined, EyeOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import MarkdownLite from '../components/MarkdownLite';
import {
  getNotifySettings,
  putNotifySettings,
  testNotifyChannel,
  sendNotifyNow,
  previewNotify,
  getNotifyLogs,
} from '../api/notify';
import type {
  NotifySettingsOut,
  NotifyConfig,
  NotifyLogItem,
  ChannelField,
  NotifySendResult,
} from '../api/notify';

const { Text, Title } = Typography;
const { TextArea } = Input;
const { useBreakpoint } = Grid;

// Kind labels
const KIND_LABELS: Record<string, string> = {
  daily_reminder: '每日记录提醒',
  daily_summary: '每日小结',
  weekly_report: '周报推送',
};

const WEEKDAY_OPTIONS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 },
];

export default function NotifyPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState<NotifySettingsOut | null>(null);
  const [config, setConfig] = useState<NotifyConfig | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [testingChannels, setTestingChannels] = useState<Record<string, boolean>>({});
  const [sendingKinds, setSendingKinds] = useState<Record<string, boolean>>({});
  const [logs, setLogs] = useState<NotifyLogItem[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [previewModal, setPreviewModal] = useState<{ visible: boolean; kind: string; data: unknown }>({
    visible: false,
    kind: '',
    data: null,
  });
  const [previewLoading, setPreviewLoading] = useState(false);
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const s = await getNotifySettings();
      setSettings(s);
      setConfig(JSON.parse(JSON.stringify(s.config)) as NotifyConfig);
    } catch {
      message.error('加载设置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const l = await getNotifyLogs(50);
      setLogs(l);
    } finally {
      setLogsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadLogs();
  }, [loadSettings, loadLogs]);

  function updateChannelField(channelKey: string, fieldName: string, value: unknown) {
    if (!config) return;
    setConfig({
      ...config,
      channels: {
        ...config.channels,
        [channelKey]: {
          ...config.channels[channelKey],
          [fieldName]: value,
        },
      },
    });
  }

  function updateScheduleField<T extends keyof NotifyConfig['schedules']>(
    schedKey: T,
    field: string,
    value: unknown
  ) {
    if (!config) return;
    setConfig({
      ...config,
      schedules: {
        ...config.schedules,
        [schedKey]: {
          ...config.schedules[schedKey],
          [field]: value,
        },
      },
    });
  }

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    try {
      const s = await putNotifySettings(config);
      setSettings(s);
      setConfig(JSON.parse(JSON.stringify(s.config)) as NotifyConfig);
      message.success('设置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(channelKey: string) {
    setTestingChannels((p) => ({ ...p, [channelKey]: true }));
    try {
      const res = await testNotifyChannel(channelKey);
      setTestResults((p) => ({ ...p, [channelKey]: { ok: res.ok, detail: res.detail } }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '请求失败';
      setTestResults((p) => ({ ...p, [channelKey]: { ok: false, detail: msg } }));
    } finally {
      setTestingChannels((p) => ({ ...p, [channelKey]: false }));
    }
  }

  async function handleSendNow(kind: string) {
    setSendingKinds((p) => ({ ...p, [kind]: true }));
    try {
      const res = await sendNotifyNow(kind);
      if (res.sent) {
        const okCount = res.results.filter((r: NotifySendResult) => r.ok).length;
        message.success(`已发送至 ${okCount} 个渠道`);
      } else {
        message.warning(res.reason ?? '未发送');
      }
      await loadLogs();
    } catch {
      message.error('发送失败');
    } finally {
      setSendingKinds((p) => ({ ...p, [kind]: false }));
    }
  }

  async function handlePreview(kind: string) {
    setPreviewLoading(true);
    setPreviewModal({ visible: true, kind, data: null });
    try {
      const res = await previewNotify(kind);
      setPreviewModal({ visible: true, kind, data: res });
    } catch {
      message.error('预览失败');
      setPreviewModal((p) => ({ ...p, visible: false }));
    } finally {
      setPreviewLoading(false);
    }
  }

  if (loading || !settings || !config) {
    return (
      <div>
        <PageHeader title="通知推送" subtitle="多渠道提醒与定时任务" />
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
        <Skeleton active paragraph={{ rows: 3 }} />
      </div>
    );
  }

  const mask = settings.mask;

  // ---- Channel Cards ----
  function renderFieldInput(channelKey: string, field: ChannelField) {
    const rawVal = config!.channels[channelKey]?.[field.name];
    const strVal = rawVal !== undefined && rawVal !== null ? String(rawVal) : '';

    if (field.type === 'boolean') {
      return (
        <Switch
          size="small"
          checked={!!rawVal}
          onChange={(v) => updateChannelField(channelKey, field.name, v)}
        />
      );
    }
    if (field.type === 'select') {
      return (
        <Select
          size="small"
          value={strVal || undefined}
          options={field.options ?? []}
          onChange={(v) => updateChannelField(channelKey, field.name, v)}
          style={{ minWidth: 120 }}
        />
      );
    }
    if (field.type === 'number') {
      return (
        <InputNumber
          size="small"
          value={rawVal !== undefined && rawVal !== null ? Number(rawVal) : undefined}
          onChange={(v) => updateChannelField(channelKey, field.name, v ?? '')}
          style={{ width: 100 }}
        />
      );
    }
    if (field.type === 'password') {
      const isSet = strVal === mask;
      const isClear = strVal === '__clear__';
      return (
        <Space wrap>
          <Input.Password
            size="small"
            value={isClear ? '' : (isSet ? '' : strVal)}
            placeholder={isSet ? '已保存，留空不修改' : (field.placeholder ?? '')}
            onChange={(e) => {
              const v = e.target.value;
              updateChannelField(channelKey, field.name, v || (isSet ? mask : ''));
            }}
            style={{ width: '100%', minWidth: 160 }}
          />
          {(isSet || isClear) ? (
            isClear ? (
              <Button size="small" onClick={() => updateChannelField(channelKey, field.name, mask)}>
                恢复
              </Button>
            ) : (
              <Button
                size="small"
                danger
                onClick={() => updateChannelField(channelKey, field.name, '__clear__')}
              >
                清除
              </Button>
            )
          ) : null}
        </Space>
      );
    }
    // text
    return (
      <Input
        size="small"
        value={strVal}
        placeholder={field.placeholder ?? ''}
        onChange={(e) => updateChannelField(channelKey, field.name, e.target.value)}
        style={{ width: '100%' }}
      />
    );
  }

  const channelCards = settings.channel_meta.map((ch) => {
    const chConfig = config.channels[ch.key] ?? {};
    const enabled = !!chConfig.enabled;
    const testResult = testResults[ch.key];

    return {
      key: ch.key,
      label: (
        <Space>
          {ch.label}
          {enabled && <Tag color="green" style={{ fontSize: 10 }}>已启用</Tag>}
        </Space>
      ),
      children: (
        <div>
          {ch.help && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              {ch.help}
            </Text>
          )}

          <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Switch
              checked={enabled}
              onChange={(v) => updateChannelField(ch.key, 'enabled', v)}
              size="small"
            />
            <Text>{enabled ? '已启用' : '未启用'}</Text>
          </div>

          {ch.fields.length > 0 && (
            <div style={{ display: 'grid', gap: 10 }}>
              {ch.fields.map((field) => (
                <div key={field.name} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <Text
                    type="secondary"
                    style={{ fontSize: 12, wordBreak: 'break-word' }}
                  >
                    {field.label}
                  </Text>
                  <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
                    {renderFieldInput(ch.key, field)}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <Space wrap>
              <Button
                size="small"
                onClick={() => handleTest(ch.key)}
                loading={testingChannels[ch.key]}
              >
                发送测试
              </Button>
              {testResult && (
                <Tag color={testResult.ok ? 'green' : 'red'} style={{ wordBreak: 'break-word', whiteSpace: 'normal' }}>
                  {testResult.ok ? '成功' : '失败'}：{testResult.detail.slice(0, 60)}
                </Tag>
              )}
            </Space>
          </div>
        </div>
      ),
    };
  });

  // ---- Schedule Section ----
  const schedules = config.schedules;

  const scheduleSection = (
    <Card title="定时任务" size="small" style={{ marginBottom: 16 }}>
      {/* daily_reminder */}
      <div style={{ marginBottom: 16 }}>
        <Text strong>每日记录提醒</Text>
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <Space>
            <Switch
              size="small"
              checked={schedules.daily_reminder.enabled}
              onChange={(v) => updateScheduleField('daily_reminder', 'enabled', v)}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>启用</Text>
          </Space>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>时间</Text>
            <TimePicker
              size="small"
              format="HH:mm"
              value={dayjs(schedules.daily_reminder.time, 'HH:mm')}
              onChange={(val) =>
                updateScheduleField('daily_reminder', 'time', val ? val.format('HH:mm') : '20:30')
              }
              allowClear={false}
            />
          </Space>
          <Space>
            <Switch
              size="small"
              checked={schedules.daily_reminder.only_if_no_meals}
              onChange={(v) => updateScheduleField('daily_reminder', 'only_if_no_meals', v)}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>仅当天无记录时发送</Text>
          </Space>
        </div>
      </div>

      <Divider style={{ margin: '12px 0' }} />

      {/* daily_summary */}
      <div style={{ marginBottom: 16 }}>
        <Text strong>每日小结</Text>
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <Space>
            <Switch
              size="small"
              checked={schedules.daily_summary.enabled}
              onChange={(v) => updateScheduleField('daily_summary', 'enabled', v)}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>启用</Text>
          </Space>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>时间</Text>
            <TimePicker
              size="small"
              format="HH:mm"
              value={dayjs(schedules.daily_summary.time, 'HH:mm')}
              onChange={(val) =>
                updateScheduleField('daily_summary', 'time', val ? val.format('HH:mm') : '21:30')
              }
              allowClear={false}
            />
          </Space>
        </div>
      </div>

      <Divider style={{ margin: '12px 0' }} />

      {/* weekly_report */}
      <div>
        <Text strong>周报推送</Text>
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <Space>
            <Switch
              size="small"
              checked={schedules.weekly_report.enabled}
              onChange={(v) => updateScheduleField('weekly_report', 'enabled', v)}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>启用</Text>
          </Space>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>每周</Text>
            <Select
              size="small"
              value={schedules.weekly_report.weekday}
              options={WEEKDAY_OPTIONS}
              onChange={(v) => updateScheduleField('weekly_report', 'weekday', v)}
              style={{ width: 80 }}
            />
          </Space>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>时间</Text>
            <TimePicker
              size="small"
              format="HH:mm"
              value={dayjs(schedules.weekly_report.time, 'HH:mm')}
              onChange={(val) =>
                updateScheduleField('weekly_report', 'time', val ? val.format('HH:mm') : '09:00')
              }
              allowClear={false}
            />
          </Space>
        </div>
      </div>
    </Card>
  );

  // ---- Send Now Section ----
  const sendNowSection = (
    <Card title="立即发送" size="small" style={{ marginBottom: 16 }}>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 10 }}>
        向所有已启用渠道立即发送
      </Text>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {Object.entries(KIND_LABELS).map(([kind, label]) => (
          <Space key={kind}>
            <Button
              icon={<SendOutlined />}
              loading={sendingKinds[kind]}
              onClick={() => handleSendNow(kind)}
              size="small"
            >
              {label}
            </Button>
            <Button
              icon={<EyeOutlined />}
              onClick={() => handlePreview(kind)}
              size="small"
              type="text"
            >
              预览
            </Button>
          </Space>
        ))}
      </div>
    </Card>
  );

  // ---- Logs Table ----
  const logColumns: ColumnsType<NotifyLogItem> = [
    {
      title: '类型',
      dataIndex: 'kind_label',
      key: 'kind_label',
      width: 100,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      key: 'channel',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'ok',
      key: 'ok',
      width: 70,
      render: (ok: boolean) => (
        <Tag color={ok ? 'green' : 'red'}>{ok ? '成功' : '失败'}</Tag>
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      key: 'detail',
      ellipsis: true,
      render: (detail: string) => (
        <Tooltip title={detail}>
          <span>{detail}</span>
        </Tooltip>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 130,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
  ];

  const logsSection = (
    <Card
      title="发送记录"
      size="small"
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={loadLogs}
          loading={logsLoading}
        >
          刷新
        </Button>
      }
    >
      <Table
        dataSource={logs}
        columns={logColumns}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 20 }}
        scroll={{ x: true }}
        loading={logsLoading}
      />
    </Card>
  );

  // ---- Preview Modal ----
  type PreviewData = {
    skipped?: boolean;
    reason?: string;
    title?: string;
    text?: string;
    markdown?: string;
  };
  const previewData = previewModal.data as PreviewData | null;

  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      <PageHeader title="通知推送" subtitle="多渠道提醒与定时任务" />
      <div className="page-title">通知推送</div>

      {/* Channel Tabs / Collapse */}
      <Card
        title="通知渠道"
        size="small"
        style={{
          marginBottom: 16,
          background: token.colorBgContainer,
          maxWidth: '100%',
          overflowX: 'hidden',
        }}
      >
        {isMobile ? (
          <Collapse
            accordion
            items={channelCards.map((c) => ({
              key: c.key,
              label: c.label,
              children: c.children,
            }))}
            size="small"
          />
        ) : (
          <Tabs
            items={channelCards}
            tabPosition="left"
            size="small"
            style={{ minHeight: 200 }}
          />
        )}
      </Card>

      {scheduleSection}
      {sendNowSection}

      {/* 就餐提醒音效 */}
      <MealAlertSettings />

      {/* Save Button */}
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={handleSave} loading={saving} size="large">
          保存设置
        </Button>
      </div>

      {logsSection}

      {/* Preview Modal */}
      <Modal
        open={previewModal.visible}
        title={`预览：${KIND_LABELS[previewModal.kind] ?? previewModal.kind}`}
        onCancel={() => setPreviewModal((p) => ({ ...p, visible: false }))}
        footer={
          <Button onClick={() => setPreviewModal((p) => ({ ...p, visible: false }))}>
            关闭
          </Button>
        }
        width={600}
      >
        {previewLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : previewData ? (
          previewData.skipped ? (
            <Alert
              type="info"
              showIcon
              message="此消息将被跳过"
              description={previewData.reason ?? '条件不满足'}
            />
          ) : (
            <div>
              {previewData.title && (
                <Title level={5} style={{ marginBottom: 8 }}>{previewData.title}</Title>
              )}
              {previewData.markdown ? (
                <MarkdownLite>{previewData.markdown}</MarkdownLite>
              ) : (
                <TextArea
                  value={previewData.text ?? ''}
                  readOnly
                  rows={6}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
              )}
            </div>
          )
        ) : null}
      </Modal>
    </div>
  );
}

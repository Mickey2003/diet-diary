import { useEffect, useRef, useState } from 'react';
import ShareCard from '../components/ShareCard';
import {
  Button,
  DatePicker,
  Alert,
  Spin,
  Tag,
  Collapse,
  Popconfirm,
  Typography,
  message,
  Segmented,
  Divider,
  Grid,
  Select,
  Space,
  Skeleton,
  theme as antdTheme,
} from 'antd';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import { PlusOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import MarkdownLite from '../components/MarkdownLite';
import Disclaimer from '../components/Disclaimer';
import { createReport, listReports, deleteReport, getReportGenerating } from '../api/endpoints';
import type { ReportOut } from '../api/types';

const { Text, Title } = Typography;
const { useBreakpoint } = Grid;

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportOut[]>([]);
  const [selected, setSelected] = useState<ReportOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [polling, setPolling] = useState(false);
  const [periodType, setPeriodType] = useState<'week' | 'month'>('week');
  const [anchor, setAnchor] = useState<Dayjs>(dayjs());
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isBusy = generating || polling;

  useEffect(() => {
    loadReports();
    // 刷新后若服务端仍在生成报告，则恢复“生成中”状态，避免重复点击
    getReportGenerating()
      .then((s) => { if (s.generating) startPolling(); })
      .catch(() => { /* ignore */ });
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPolling() {
    if (pollRef.current) return;
    setPolling(true);
    pollRef.current = setInterval(async () => {
      try {
        const s = await getReportGenerating();
        if (!s.generating) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setPolling(false);
          const list = await loadReports();
          if (list.length > 0) setSelected(list[0]);
          message.success('报告已生成');
        }
      } catch {
        /* ignore */
      }
    }, 4000);
  }

  async function loadReports(): Promise<ReportOut[]> {
    setLoading(true);
    try {
      const list = await listReports();
      setReports(list);
      if (list.length > 0 && !selected) {
        setSelected(list[0]);
      }
      return list;
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    try {
      const report = await createReport(periodType, anchor.format('YYYY-MM-DD'));
      message.success('报告生成成功！');
      await loadReports();
      setSelected(report);
    } catch (err: unknown) {
      // 409：服务端已在生成中 → 轮询等待结果
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 409) startPolling();
    } finally {
      setGenerating(false);
    }
  }

  async function handleDelete(id: number) {
    await deleteReport(id);
    message.success('已删除');
    if (selected?.id === id) setSelected(null);
    await loadReports();
  }

  return (
    <div>
      <PageHeader title="阶段总结" subtitle="AI 基于统计事实撰写的周报 / 月报" />
      <div className="page-title">阶段总结</div>

      {/* 生成操作区 */}
      <div
        style={{
          background: token.colorBgContainer,
          borderRadius: 10,
          padding: '16px 20px',
          marginBottom: 20,
          boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          flexWrap: 'wrap',
        }}
      >
        <Segmented
          options={[
            { label: '周报', value: 'week' },
            { label: '月报', value: 'month' },
          ]}
          value={periodType}
          onChange={(v) => setPeriodType(v as 'week' | 'month')}
        />
        <DatePicker
          picker={periodType === 'week' ? 'week' : 'month'}
          value={anchor}
          onChange={(d) => d && setAnchor(d)}
          allowClear={false}
          format={periodType === 'week' ? 'YYYY 年第 w 周' : 'YYYY-MM'}
          placeholder="选择时段"
          style={{ flex: isMobile ? 1 : undefined }}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          loading={isBusy}
          disabled={isBusy}
          onClick={handleGenerate}
          style={isMobile ? { flex: 1 } : undefined}
        >
          {isBusy ? '生成中…' : `生成${periodType === 'week' ? '周' : '月'}报告`}
        </Button>
        {isBusy && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            AI 正在整理数据和撰写总结，通常 10~60 秒，请勿刷新或重复点击…
          </Text>
        )}
      </div>

      {loading ? (
        <div>
          <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
          <Skeleton active paragraph={{ rows: 2 }} />
        </div>
      ) : isMobile ? (
        /* Mobile: Select + detail below */
        <div>
          {reports.length === 0 ? (
            <EmptyState
              emoji="📋"
              hint="还没有报告，选择时段生成第一份吧"
            />
          ) : (
            <>
              <Select
                value={selected?.id}
                onChange={(id) => {
                  const r = reports.find((x) => x.id === id);
                  if (r) setSelected(r);
                }}
                style={{ width: '100%', marginBottom: 16 }}
                options={reports.map((r) => ({
                  label: `${r.period_type === 'week' ? '周报' : '月报'} ${dayjs(r.period_start).format('M/D')}~${dayjs(r.period_end).format('M/D')}`,
                  value: r.id,
                }))}
              />
              {selected && <ReportDetail report={selected} onDelete={handleDelete} token={token} />}
            </>
          )}
        </div>
      ) : (
        /* Desktop: sidebar + detail */
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 20 }}>
          {/* 左侧列表 */}
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 10 }}>
              已生成报告（{reports.length} 份）
            </Text>
            {reports.length === 0 ? (
              <EmptyState
                emoji="📋"
                hint="还没有报告，选择时段生成第一份吧"
              />
            ) : (
              reports.map((r) => (
                <div
                  key={r.id}
                  onClick={() => setSelected(r)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    cursor: 'pointer',
                    marginBottom: 8,
                    background: selected?.id === r.id ? token.colorPrimaryBg : token.colorBgContainer,
                    border:
                      selected?.id === r.id
                        ? `1px solid ${token.colorPrimary}`
                        : `1px solid ${token.colorBorderSecondary}`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <Tag color={r.period_type === 'week' ? 'blue' : 'green'} style={{ marginBottom: 2 }}>
                      {r.period_type === 'week' ? '周报' : '月报'}
                    </Tag>
                    <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                      {dayjs(r.period_start).format('M/D')} ~{' '}
                      {dayjs(r.period_end).format('M/D')}
                    </div>
                    <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                      {dayjs(r.created_at).format('MM-DD HH:mm')}
                    </div>
                  </div>
                  <Popconfirm
                    title="确定删除此报告？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      handleDelete(r.id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      size="small"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              ))
            )}
          </div>

          {/* 右侧详情 */}
          <div>
            {!selected ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: '80px 20px',
                  color: token.colorTextTertiary,
                  background: token.colorBgContainer,
                  borderRadius: 10,
                }}
              >
                <FileTextOutlined style={{ fontSize: 40, marginBottom: 12 }} />
                <div>选择左侧报告查看内容，或点击生成新报告</div>
              </div>
            ) : (
              <ReportDetail report={selected} onDelete={handleDelete} token={token} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface TokenLike {
  colorTextTertiary: string;
  colorPrimary: string;
  colorBorderSecondary: string;
  colorBgContainer: string;
}

function ReportDetail({
  report,
  onDelete,
  token,
}: {
  report: ReportOut;
  onDelete: (id: number) => void;
  token: TokenLike;
}) {
  return (
    <div className="content-card">
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <Tag color={report.period_type === 'week' ? 'blue' : 'green'}>
              {report.period_type === 'week' ? '周报' : '月报'}
            </Tag>
            <Title level={4} style={{ display: 'inline', marginLeft: 8 }}>
              {dayjs(report.period_start).format('YYYY 年 M 月 D 日')} ~{' '}
              {dayjs(report.period_end).format('M 月 D 日')}
            </Title>
            {typeof report.facts?.kcal_avg_per_day === 'number' && (report.facts.kcal_avg_per_day as number) > 0 && (
              <Tag style={{ marginLeft: 8, fontSize: 12 }} color="orange">
                日均估算 ≈ {Math.round(report.facts.kcal_avg_per_day as number)} kcal
              </Tag>
            )}
          </div>
          <Space>
            <ShareCard
              kind={report.period_type === 'week' ? 'weekly' : 'monthly'}
              anchor={report.period_start}
              label="生成分享卡片"
            />
            <Popconfirm title="确定删除此报告？" onConfirm={() => onDelete(report.id)}>
              <Button danger icon={<DeleteOutlined />} size="small">删除</Button>
            </Popconfirm>
          </Space>
        </div>
        <div style={{ fontSize: 12, color: token.colorTextTertiary, marginTop: 4 }}>
          生成时间：{dayjs(report.created_at).format('YYYY-MM-DD HH:mm')} ·
          模型：{report.model ?? '—'}
        </div>
      </div>

      <Divider />

      {report.unverified_numbers.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="以下数字在统计数据中找不到对应来源，请核对"
          description={
            <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
              {report.unverified_numbers.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          }
        />
      )}

      {/* 正文（AI 撰写的阶段总结） */}
      <div
        style={{
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: 10,
          padding: '14px 16px',
          background: token.colorBgContainer,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, color: token.colorPrimary }}>
          本期总结
        </div>
        {report.summary_md && report.summary_md.trim() ? (
          <MarkdownLite style={{ fontSize: 14 }}>{report.summary_md}</MarkdownLite>
        ) : (
          <Alert
            type="info"
            showIcon
            message="本期暂无正文内容"
            description="可展开下方“统计事实”查看数据，或重新生成一次。"
          />
        )}
      </div>

      <Collapse
        ghost
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'facts',
            label: '查看统计事实（JSON，用于核对）',
            children: (
              <pre
                style={{
                  background: 'var(--dd-fill-alter, #f8f8f8)',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 11,
                  overflow: 'auto',
                  maxHeight: 400,
                }}
              >
                {JSON.stringify(report.facts, null, 2)}
              </pre>
            ),
          },
        ]}
      />

      <Disclaimer />
    </div>
  );
}

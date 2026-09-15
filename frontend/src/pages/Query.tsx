import { useEffect, useState } from 'react';
import {
  Input,
  Alert,
  Collapse,
  Table,
  Tag,
  Typography,
  Spin,
  Descriptions,
  Divider,
  Button,
  Grid,
  theme as antdTheme,
} from 'antd';
import PageHeader from '../components/PageHeader';
import type { ColumnsType } from 'antd/es/table';
import { HistoryOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import MarkdownLite from '../components/MarkdownLite';
import Disclaimer from '../components/Disclaimer';
import { runQuery, getQueryHistory } from '../api/endpoints';
import { usePendingTasks, pollUntilDone } from '../hooks/usePendingTasks';
import type { QueryOut, QueryHistoryItem } from '../api/types';

const { Search } = Input;
const { Text, Title } = Typography;
const { useBreakpoint } = Grid;

const EXAMPLE_QUESTIONS = [
  '这周喝过几次含糖饮料',
  '这个月各类食物占比',
  '最近 30 天最常吃的菜',
  '上周每天记录了几餐',
  '深夜吃过几次东西',
];

const TIME_PRESET_LABELS: Record<string, string> = {
  today: '今天',
  yesterday: '昨天',
  this_week: '本周',
  last_week: '上周',
  last_7d: '近 7 天',
  last_30d: '近 30 天',
  this_month: '本月',
  last_month: '上月',
  all: '全部',
  custom: '自定义',
};

const METRIC_LABELS: Record<string, string> = {
  count_meals: '统计餐次数量',
  count_items: '统计菜品数量',
  count_tag: '统计标签次数',
  ratio_category: '分类占比',
  list_meals: '列举餐食',
  avg_meals_per_day: '日均餐数',
  top_items: '常吃食物 Top N',
};

const GROUP_LABELS: Record<string, string> = {
  none: '不分组',
  day: '按天',
  meal_type: '按餐次',
  category: '按分类',
  tag: '按标签',
  weekday: '按星期',
};

export default function QueryPage() {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryOut | null>(null);
  const [history, setHistory] = useState<QueryHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyView, setHistoryView] = useState<QueryHistoryItem | null>(null);
  const pending = usePendingTasks();
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  useEffect(() => {
    loadHistory();
  }, []);

  // 刷新后若服务端仍在查询，则恢复加载态并等待，避免重复提问
  useEffect(() => {
    if (!pending.query) return;
    setLoading(true);
    const stop = pollUntilDone('query', () => {
      setLoading(false);
      loadHistory();
    });
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.query]);

  async function loadHistory() {
    setHistoryLoading(true);
    try {
      const h = await getQueryHistory(20);
      setHistory(h);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function handleQuery(q: string) {
    if (!q.trim()) return;
    setQuestion(q);
    setLoading(true);
    setResult(null);
    setHistoryView(null);
    try {
      const res = await runQuery(q.trim());
      setResult(res);
      await loadHistory();
    } finally {
      setLoading(false);
    }
  }

  /** 点击历史记录：直接展示当时保存的回答，不再向 AI 重复提问 */
  function viewHistoryAnswer(h: QueryHistoryItem) {
    setHistoryView(h);
    setQuestion(h.question);
    setResult({
      id: h.id,
      question: h.question,
      status: h.status,
      rows: [],
      answer: h.answer || '（该次查询没有保存回答内容）',
      warnings: [],
      disclaimer: '',
      model: h.model,
    });
  }

  function buildColumns(rows: Record<string, unknown>[]): ColumnsType<Record<string, unknown>> {
    if (rows.length === 0) return [];
    const keys = Object.keys(rows[0]);
    return keys.map((k) => ({
      title: k,
      dataIndex: k,
      key: k,
      render: (v: unknown) => {
        if (v === null || v === undefined) return '—';
        if (typeof v === 'number') return String(v);
        if (typeof v === 'boolean') return v ? '是' : '否';
        return String(v);
      },
    }));
  }

  return (
    <div>
      <PageHeader title="自然语言查询" subtitle="用一句话查询你的饮食记录" />
      <div className="page-title">自然语言查询</div>

      {/* 搜索框 */}
      <div className="content-card">
        <Search
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onSearch={handleQuery}
          placeholder="用中文提问，例如：这周记录了几餐？"
          enterButton="查询"
          size="large"
          loading={loading}
          style={{ marginBottom: 16 }}
        />

        {/* 示例问题 - prominent chips */}
        <div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            试试这些问题：
          </Text>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {EXAMPLE_QUESTIONS.map((q) => (
              <Tag
                key={q}
                color="blue"
                style={{
                  cursor: 'pointer',
                  padding: '4px 10px',
                  fontSize: 13,
                  borderRadius: 20,
                  marginBottom: 0,
                }}
                onClick={() => handleQuery(q)}
              >
                {q}
              </Tag>
            ))}
          </div>
        </div>
      </div>

      {/* 加载中 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="AI 正在分析你的问题…" />
        </div>
      )}

      {/* 结果 */}
      {result && !loading && (
        <div>
          {historyView && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="正在查看历史回答"
              description={`提问时间：${dayjs(historyView.created_at).format('YYYY-MM-DD HH:mm')}`}
            />
          )}
          {result.status === 'unsupported' && (
            <Alert
              type="warning"
              showIcon
              message="不支持的查询"
              description={result.plan?.unsupported_reason ?? '此问题超出了支持的查询范围。'}
              style={{ marginBottom: 16 }}
            />
          )}
          {result.status === 'error' && (
            <Alert
              type="error"
              showIcon
              message="查询出错"
              description={result.answer}
              style={{ marginBottom: 16 }}
            />
          )}

          {result.warnings?.map((w, i) => (
            <Alert key={i} type="warning" message={w} showIcon style={{ marginBottom: 8 }} />
          ))}

          {result.status === 'ok' && (
            <div className="query-answer">
              <Title level={5} style={{ marginTop: 0 }}>
                查询结果
              </Title>
              <MarkdownLite>{result.answer}</MarkdownLite>
            </div>
          )}

          <Collapse
            style={{ marginBottom: 16 }}
            items={[
              {
                key: 'plan',
                label: '查询计划（AI 生成，程序校验）',
                children: result.plan ? (
                  <div>
                    <Descriptions column={isMobile ? 1 : 2} size="small" bordered>
                      <Descriptions.Item label="指标">
                        {METRIC_LABELS[result.plan.metric] ?? result.plan.metric}
                      </Descriptions.Item>
                      <Descriptions.Item label="时间范围">
                        {TIME_PRESET_LABELS[result.plan.time_range.preset] ?? result.plan.time_range.preset}
                        {result.plan.time_range.start && ` (${result.plan.time_range.start} ~ ${result.plan.time_range.end})`}
                      </Descriptions.Item>
                      <Descriptions.Item label="分组方式">
                        {GROUP_LABELS[result.plan.group_by] ?? result.plan.group_by}
                      </Descriptions.Item>
                      <Descriptions.Item label="限制条数">
                        {result.plan.limit}
                      </Descriptions.Item>
                      {result.plan.filters.tags.length > 0 && (
                        <Descriptions.Item label="标签过滤">
                          {result.plan.filters.tags.join(', ')}
                        </Descriptions.Item>
                      )}
                      {result.plan.filters.categories.length > 0 && (
                        <Descriptions.Item label="分类过滤">
                          {result.plan.filters.categories.join(', ')}
                        </Descriptions.Item>
                      )}
                      {result.plan.filters.name_contains && (
                        <Descriptions.Item label="关键词">
                          {result.plan.filters.name_contains}
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                    <Divider style={{ margin: '12px 0' }} />
                    <Text type="secondary" style={{ fontSize: 11 }}>原始 JSON：</Text>
                    <pre style={{
                      background: 'var(--dd-fill-alter, #f8f8f8)',
                      padding: 10,
                      borderRadius: 6,
                      fontSize: 11,
                      overflow: 'auto',
                    }}>
                      {JSON.stringify(result.plan, null, 2)}
                    </pre>
                  </div>
                ) : (
                  <Text type="secondary">无查询计划</Text>
                ),
              },
              ...(result.rows.length > 0
                ? [
                    {
                      key: 'rows',
                      label: `查询结果（${result.rows.length} 行）`,
                      children: (
                        <Table
                          dataSource={result.rows}
                          columns={buildColumns(result.rows)}
                          size="small"
                          rowKey={(_, idx) => String(idx ?? 0)}
                          pagination={{ pageSize: 20 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                  ]
                : []),
              ...(result.sql
                ? [
                    {
                      key: 'sql',
                      label: 'SQL（程序生成）',
                      children: (
                        <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 14, borderRadius: 6, fontSize: 12, overflow: 'auto' }}>
                          {result.sql}
                        </pre>
                      ),
                    },
                  ]
                : []),
            ]}
          />

          <Disclaimer text={result.disclaimer} />
        </div>
      )}

      {/* 查询历史 */}
      <Divider />
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <HistoryOutlined />
          <Text strong>历史查询</Text>
          <Button size="small" onClick={loadHistory} loading={historyLoading}>
            刷新
          </Button>
        </div>
        {historyLoading ? (
          <Spin />
        ) : history.length === 0 ? (
          <Text type="secondary">暂无查询历史</Text>
        ) : (
          <div>
            {history.map((h) => (
              <div
                key={h.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 12px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  marginBottom: 6,
                  background: token.colorBgContainer,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  gap: 8,
                }}
                onClick={() => viewHistoryAnswer(h)}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Tag
                    color={h.status === 'ok' ? 'green' : h.status === 'unsupported' ? 'orange' : 'red'}
                    style={{ fontSize: 10, marginRight: 8 }}
                  >
                    {h.status}
                  </Tag>
                  <Text style={{ wordBreak: 'break-word' }}>{h.question}</Text>
                </div>
                <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'nowrap', flexShrink: 0 }}>
                  {dayjs(h.created_at).format('MM-DD HH:mm')}
                </Text>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

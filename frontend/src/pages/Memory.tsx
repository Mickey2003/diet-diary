import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Collapse,
  Form,
  Grid,
  Input,
  message,
  Modal,
  Popconfirm,
  Rate,
  Select,
  Segmented,
  Space,
  Skeleton,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  theme as antdTheme,
} from 'antd';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import { usePendingTasks, pollUntilDone } from '../hooks/usePendingTasks';
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  listMemories,
  createMemory,
  updateMemory,
  deleteMemory,
  extractMemories,
  rebuildMemories,
  getMemorySummary,
  CATEGORY_LABELS,
  CATEGORY_COLORS,
  VALID_CATEGORIES,
} from '../api/memory';
import type { MemoryItem, MemorySummary } from '../api/memory';

const { Text, Paragraph } = Typography;
const { Search } = Input;
const { useBreakpoint } = Grid;

const ALL_CATEGORY_OPTIONS = [
  { label: '全部', value: '' },
  ...VALID_CATEGORIES.map((k) => ({
    label: CATEGORY_LABELS[k] ?? k,
    value: k,
  })),
];

function SourceTag({ source }: { source: string }) {
  if (source === 'user') return <Tag color="default">手动</Tag>;
  if (source === 'ai' || source === 'auto') return <Tag color="blue">自动</Tag>;
  return <Tag color="cyan">{source}</Tag>;
}

export default function MemoryPage() {
  const [summary, setSummary] = useState<MemorySummary | null>(null);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [extractText, setExtractText] = useState('');
  const [extracting, setExtracting] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  // 手动添加 Modal
  const [addOpen, setAddOpen] = useState(false);
  const [addContent, setAddContent] = useState('');
  const [addCategory, setAddCategory] = useState('preference');
  const [addImportance, setAddImportance] = useState(3);
  const [adding, setAdding] = useState(false);

  // 编辑内联
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');

  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const s = await getMemorySummary();
      setSummary(s);
    } catch {
      /* 忽略 */
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const loadMemories = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listMemories({
        category: categoryFilter || undefined,
        include_inactive: includeInactive || undefined,
      });
      setMemories(list);
    } catch {
      /* 忽略 */
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, includeInactive]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadMemories();
  }, [loadMemories]);

  // 刷新后恢复“重建中”状态：若服务端仍在重建，禁用按钮并轮询至完成
  const pendingTasks = usePendingTasks();
  useEffect(() => {
    if (!pendingTasks.memory) return;
    setRebuilding(true);
    const stop = pollUntilDone('memory', () => {
      setRebuilding(false);
      message.success('记忆重建已完成');
      Promise.all([loadMemories(), loadSummary()]);
    });
    return stop;
  }, [pendingTasks.memory, loadMemories, loadSummary]);

  async function handleExtract() {
    if (!extractText.trim()) {
      message.warning('请输入要提取记忆的文本');
      return;
    }
    setExtracting(true);
    try {
      const result = await extractMemories(extractText);
      message.success(`从文本中提取了 ${result.length} 条记忆`);
      setExtractText('');
      await Promise.all([loadMemories(), loadSummary()]);
    } catch {
      /* 错误已显示 */
    } finally {
      setExtracting(false);
    }
  }

  async function handleRebuild() {
    setRebuilding(true);
    try {
      const r = await rebuildMemories();
      message.success(
        `重建完成：扫描 ${r.scanned_meals} 餐，新增 ${r.new_memories} 条记忆`,
      );
      await Promise.all([loadMemories(), loadSummary()]);
    } catch {
      /* 错误已显示 */
    } finally {
      setRebuilding(false);
    }
  }

  async function handleAdd() {
    if (!addContent.trim()) {
      message.warning('请填写记忆内容');
      return;
    }
    setAdding(true);
    try {
      await createMemory({
        content: addContent.trim(),
        category: addCategory,
        importance: addImportance,
      });
      message.success('记忆已添加');
      setAddOpen(false);
      setAddContent('');
      setAddCategory('preference');
      setAddImportance(3);
      await Promise.all([loadMemories(), loadSummary()]);
    } catch {
      /* 错误已显示 */
    } finally {
      setAdding(false);
    }
  }

  async function handleToggleActive(id: number, val: boolean) {
    try {
      await updateMemory(id, { is_active: val });
      setMemories((prev) =>
        prev.map((m) => (m.id === id ? { ...m, is_active: val } : m)),
      );
      await loadSummary();
    } catch {
      /* 错误已显示 */
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
      await loadSummary();
      message.success('已删除');
    } catch {
      /* 错误已显示 */
    }
  }

  async function handleEditSave(id: number) {
    if (!editContent.trim()) return;
    try {
      const updated = await updateMemory(id, { content: editContent.trim() });
      setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
      setEditingId(null);
      message.success('已更新');
    } catch {
      /* 错误已显示 */
    }
  }

  // Build table columns for desktop
  const columns = [
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      render: (text: string, record: MemoryItem) => {
        if (editingId === record.id) {
          return (
            <Space>
              <Input
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                style={{ minWidth: 200 }}
                onPressEnter={() => handleEditSave(record.id)}
              />
              <Button size="small" type="primary" onClick={() => handleEditSave(record.id)}>
                保存
              </Button>
              <Button size="small" onClick={() => setEditingId(null)}>
                取消
              </Button>
            </Space>
          );
        }
        return (
          <div
            style={{
              cursor: 'pointer',
              opacity: record.is_active ? 1 : 0.45,
            }}
            onClick={() => {
              setEditingId(record.id);
              setEditContent(record.content);
            }}
            title="点击编辑"
          >
            {text}
          </div>
        );
      },
    },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      width: 80,
      render: (cat: string) => (
        <Tag color={CATEGORY_COLORS[cat] ?? 'default'}>
          {CATEGORY_LABELS[cat] ?? cat}
        </Tag>
      ),
    },
    {
      title: '重要度',
      dataIndex: 'importance',
      key: 'importance',
      width: 120,
      render: (val: number) => <Rate disabled defaultValue={val} count={5} style={{ fontSize: 12 }} />,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 70,
      render: (src: string) => <SourceTag source={src} />,
    },
    {
      title: '证据',
      dataIndex: 'evidence',
      key: 'evidence',
      width: 60,
      render: (ev: string | undefined) =>
        ev ? (
          <Tooltip title={ev}>
            <Text type="secondary" style={{ fontSize: 11, cursor: 'help' }}>查看</Text>
          </Tooltip>
        ) : null,
    },
    {
      title: '最近使用',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      width: 90,
      render: (t: string | undefined) =>
        t ? (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {dayjs(t).format('MM-DD')}
          </Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 11 }}>—</Text>
        ),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 70,
      render: (val: boolean, record: MemoryItem) => (
        <Switch
          size="small"
          checked={val}
          onChange={(v) => handleToggleActive(record.id, v)}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 60,
      render: (_: unknown, record: MemoryItem) => (
        <Popconfirm
          title="确定删除这条记忆吗？"
          onConfirm={() => handleDelete(record.id)}
        >
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            type="text"
          />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="AI 记忆" subtitle="AI 记住的偏好与习惯，可随时修改" />
      <div className="page-title">AI 记忆</div>

      {/* 摘要区 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        {summaryLoading ? (
          <Spin size="small" />
        ) : summary ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <Text strong>
                共 {summary.count} 条活跃记忆
              </Text>
              {Object.entries(summary.by_category).map(([cat, cnt]) => (
                <Tag key={cat} color={CATEGORY_COLORS[cat] ?? 'default'}>
                  {CATEGORY_LABELS[cat] ?? cat} {cnt}
                </Tag>
              ))}
            </div>
            {summary.prompt_preview && (
              <Collapse
                ghost
                size="small"
                items={[
                  {
                    key: 'preview',
                    label: 'AI 会看到的记忆摘要',
                    children: (
                      <Paragraph
                        style={{
                          background: token.colorFillAlter,
                          borderRadius: 6,
                          padding: 10,
                          fontSize: 12,
                          margin: 0,
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {summary.prompt_preview}
                      </Paragraph>
                    ),
                  },
                ]}
              />
            )}
          </div>
        ) : (
          <Text type="secondary">暂无记忆数据</Text>
        )}
      </Card>

      {/* 工具栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 10,
            alignItems: 'center',
          }}
        >
          {/* 类别过滤 */}
          <Segmented
            options={ALL_CATEGORY_OPTIONS}
            value={categoryFilter}
            onChange={(v) => setCategoryFilter(v as string)}
            size="small"
          />

          {/* 包含已停用 */}
          <Space size="small">
            <Text type="secondary" style={{ fontSize: 12 }}>
              含已停用
            </Text>
            <Switch
              size="small"
              checked={includeInactive}
              onChange={setIncludeInactive}
            />
          </Space>

          {/* 记住这个 */}
          <Search
            placeholder="记住这个：粘贴文字提取记忆"
            value={extractText}
            onChange={(e) => setExtractText(e.target.value)}
            onSearch={handleExtract}
            enterButton={extracting ? <Spin size="small" /> : '提取'}
            loading={extracting}
            style={{ minWidth: isMobile ? '100%' : 280 }}
          />

          {/* 从记录重建 */}
          <Popconfirm
            title="将扫描近30天餐食记录重建记忆，已有记忆不重复添加，继续？"
            onConfirm={handleRebuild}
          >
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={rebuilding}
              disabled={rebuilding}
            >
              {rebuilding ? '重建中…' : '从最近记录重建'}
            </Button>
          </Popconfirm>

          {/* 手动添加 */}
          <Button
            size="small"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setAddOpen(true)}
          >
            手动添加
          </Button>
        </div>
      </Card>

      {/* 记忆列表 */}
      {loading ? (
        <div>
          <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 10 }} />
          <Skeleton active paragraph={{ rows: 3 }} />
        </div>
      ) : memories.length === 0 ? (
        <EmptyState
          emoji="🤖"
          hint="暂无记忆，上传一张餐食图片或点击「手动添加」来创建第一条记忆"
        />
      ) : isMobile ? (
        /* 移动端卡片列表 */
        <div>
          {memories.map((m) => (
            <Card
              key={m.id}
              size="small"
              style={{
                marginBottom: 8,
                opacity: m.is_active ? 1 : 0.55,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, marginRight: 8 }}>
                  {editingId === m.id ? (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Input
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        onPressEnter={() => handleEditSave(m.id)}
                      />
                      <Space>
                        <Button size="small" type="primary" onClick={() => handleEditSave(m.id)}>
                          保存
                        </Button>
                        <Button size="small" onClick={() => setEditingId(null)}>
                          取消
                        </Button>
                      </Space>
                    </Space>
                  ) : (
                    <div
                      style={{ cursor: 'pointer', marginBottom: 6 }}
                      onClick={() => {
                        setEditingId(m.id);
                        setEditContent(m.content);
                      }}
                    >
                      {m.content}
                    </div>
                  )}
                  <Space size={4} wrap>
                    <Tag color={CATEGORY_COLORS[m.category] ?? 'default'} style={{ fontSize: 11 }}>
                      {CATEGORY_LABELS[m.category] ?? m.category}
                    </Tag>
                    <SourceTag source={m.source} />
                    <Rate disabled defaultValue={m.importance} count={5} style={{ fontSize: 10 }} />
                  </Space>
                </div>
                <Space direction="vertical" size={4} style={{ alignItems: 'flex-end' }}>
                  <Switch
                    size="small"
                    checked={m.is_active}
                    onChange={(v) => handleToggleActive(m.id, v)}
                  />
                  <Popconfirm
                    title="确定删除？"
                    onConfirm={() => handleDelete(m.id)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} type="text" />
                  </Popconfirm>
                </Space>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        /* 桌面端表格 */
        <Table
          dataSource={memories}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
          rowClassName={(r) => (r.is_active ? '' : 'opacity-50')}
        />
      )}

      {/* 手动添加 Modal */}
      <Modal
        title="手动添加记忆"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        confirmLoading={adding}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <Form layout="vertical" size="small">
          <Form.Item label="内容" required>
            <Input.TextArea
              value={addContent}
              onChange={(e) => setAddContent(e.target.value)}
              rows={3}
              placeholder="如：我不吃辣，偏好清淡饮食"
              maxLength={300}
              showCount
            />
          </Form.Item>
          <Form.Item label="类别">
            <Select
              value={addCategory}
              onChange={setAddCategory}
              options={VALID_CATEGORIES.map((k) => ({
                label: `${CATEGORY_LABELS[k]} (${k})`,
                value: k,
              }))}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item label="重要程度">
            <Rate
              value={addImportance}
              onChange={setAddImportance}
              count={5}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 说明 & 声明 */}
      {memories.length > 0 && summary?.disclaimer && (
        <Alert
          type="info"
          showIcon
          message={summary.disclaimer}
          style={{ marginTop: 16, fontSize: 12 }}
        />
      )}

      {memories.length === 0 && (
        <Alert
          type="info"
          showIcon
          message="关于 AI 记忆"
          description="记忆只保存在你的账号下，用于让 AI 的解释、周报和餐单更贴合你；可随时关闭或删除。系统会在你上传餐食照片时自动学习你的偏好。"
          style={{ marginTop: 16 }}
        />
      )}
    </div>
  );
}

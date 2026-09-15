import { useEffect, useState, useCallback } from 'react';
import {
  Button,
  DatePicker,
  Select,
  Input,
  Drawer,
  Popconfirm,
  Tag,
  Image,
  Pagination,
  Spin,
  message,
  Collapse,
  Divider,
  Typography,
  Segmented,
  Grid,
  Space,
  Skeleton,
  theme as antdTheme,
} from 'antd';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import ShareCard from '../components/ShareCard';
import dayjs, { type Dayjs } from 'dayjs';
import type { RangePickerProps } from 'antd/es/date-picker';
import MealItemsEditor, { nextKey } from '../components/MealItemsEditor';
import TagChip from '../components/TagChip';
import { listMeals, deleteMeal, updateMeal, getTags, getMeta } from '../api/endpoints';
import { categoryColor } from '../utils/categoryColors';
import type { MealOut, TagOut, EditableItem, MetaOut } from '../api/types';

const { RangePicker } = DatePicker;
const { Search } = Input;
const { Text } = Typography;
const { useBreakpoint } = Grid;

const MEAL_TYPE_COLORS: Record<string, string> = {
  早餐: 'gold',
  午餐: 'green',
  晚餐: 'blue',
  加餐: 'cyan',
  饮品: 'purple',
};

export default function TimelinePage() {
  const [meals, setMeals] = useState<MealOut[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [allTags, setAllTags] = useState<TagOut[]>([]);
  const [meta, setMeta] = useState<MetaOut | null>(null);
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  // 过滤器
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null]>([null, null]);
  const [filterMealType, setFilterMealType] = useState<string | undefined>();
  const [filterTag, setFilterTag] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');

  // 抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedMeal, setSelectedMeal] = useState<MealOut | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editItems, setEditItems] = useState<EditableItem[]>([]);
  const [editMealType, setEditMealType] = useState('早餐');
  const [editEatenAt, setEditEatenAt] = useState<Dayjs>(dayjs());
  const [editNote, setEditNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getTags().then(setAllTags).catch(() => {/* 忽略 */});
    getMeta().then(setMeta).catch(() => {/* 忽略 */});
  }, []);

  const loadMeals = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number | undefined> = {
        page,
        page_size: 20,
        meal_type: filterMealType,
        tag: filterTag,
        keyword: keyword || undefined,
        from: dateRange[0]?.format('YYYY-MM-DD'),
        to: dateRange[1]?.format('YYYY-MM-DD'),
      };
      const res = await listMeals(params);
      setMeals(res.items);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  }, [page, filterMealType, filterTag, keyword, dateRange]);

  useEffect(() => {
    loadMeals();
  }, [loadMeals]);

  // 按日期分组
  const grouped: Record<string, MealOut[]> = {};
  for (const meal of meals) {
    const d = dayjs(meal.eaten_at).format('YYYY-MM-DD');
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(meal);
  }
  const sortedDates = Object.keys(grouped).sort().reverse();

  function openDrawer(meal: MealOut) {
    setSelectedMeal(meal);
    setEditMode(false);
    setDrawerOpen(true);
  }

  function startEdit(meal: MealOut) {
    setEditItems(
      meal.items.map((item) => ({
        _key: String(item.id),
        name: item.name,
        category: item.category,
        portion: item.portion,
        tags: item.tags.map((t) => t.code),
        confidence: item.confidence ?? undefined,
        source: item.source as 'ai' | 'ai_edited' | 'user',
        kcal: item.kcal ?? undefined,
        kcal_source: item.kcal_source ?? undefined,
      }))
    );
    setEditMealType(meal.meal_type);
    setEditEatenAt(dayjs(meal.eaten_at));
    setEditNote(meal.note ?? '');
    setEditMode(true);
  }

  async function handleSaveEdit() {
    if (!selectedMeal) return;
    if (editItems.length === 0) {
      message.warning('至少保留一条菜品记录');
      return;
    }
    setSaving(true);
    try {
      await updateMeal(selectedMeal.id, {
        eaten_at: editEatenAt.format('YYYY-MM-DDTHH:mm:ss'),
        meal_type: editMealType,
        note: editNote || undefined,
        items: editItems.map((item) => ({
          name: item.name.trim(),
          category: item.category,
          portion: item.portion,
          tags: item.tags,
          confidence: item.confidence,
          source: item.source,
          kcal: item.kcal ?? undefined,
          kcal_source: item.kcal_source ?? undefined,
        })),
      });
      message.success('已更新');
      setEditMode(false);
      await loadMeals();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    await deleteMeal(id);
    message.success('已删除');
    setDrawerOpen(false);
    await loadMeals();
  }

  async function handleAddEmptyItem() {
    setEditItems((prev) => [
      ...prev,
      { _key: nextKey(), name: '', category: '其他', portion: '中', tags: [], source: 'user' },
    ]);
  }
  void handleAddEmptyItem;

  const handleRangeChange: RangePickerProps['onChange'] = (vals) => {
    setDateRange(vals ? [vals[0], vals[1]] : [null, null]);
  };

  return (
    <div>
      <PageHeader title="饮食时间线" subtitle="按日期浏览你的每一餐" />
      <div className="page-title">饮食时间线</div>

      {/* 过滤器 */}
      <div
        style={{
          background: token.colorBgContainer,
          borderRadius: 10,
          padding: '14px 16px',
          marginBottom: 20,
          display: 'flex',
          gap: 10,
          flexWrap: 'wrap',
          alignItems: 'center',
          boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
        }}
      >
        <RangePicker
          value={dateRange}
          onChange={handleRangeChange}
          format="MM-DD"
          placeholder={['开始日期', '结束日期']}
          style={{ minWidth: isMobile ? '100%' : 200 }}
        />
        <Select
          allowClear
          placeholder="餐次"
          value={filterMealType}
          onChange={(v) => { setFilterMealType(v); setPage(1); }}
          style={{ minWidth: 90 }}
          options={['早餐', '午餐', '晚餐', '加餐', '饮品'].map((t) => ({
            label: t,
            value: t,
          }))}
        />
        <Select
          allowClear
          placeholder="标签"
          value={filterTag}
          onChange={(v) => { setFilterTag(v); setPage(1); }}
          style={{ minWidth: 110 }}
          options={allTags.map((t) => ({ label: t.name_zh, value: t.code }))}
        />
        <Search
          placeholder="关键词"
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={() => { setPage(1); loadMeals(); }}
          style={{ minWidth: 140, flex: isMobile ? 1 : undefined }}
        />
        <Button onClick={() => { setPage(1); loadMeals(); }}>查询</Button>
      </div>

      {/* 时间线 */}
      {loading && meals.length === 0 ? (
        <div>
          <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 16 }} />
          <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 16 }} />
        </div>
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: 20 }}><Spin size="small" /></div>
      ) : meals.length === 0 ? (
        <EmptyState
          emoji="🍽️"
          hint="还没有饮食记录，去记录第一餐吧"
          actionLabel="去记录第一餐"
          onAction={() => window.location.href = '/'}
        />
      ) : (
        <>
          {sortedDates.map((date) => (
            <div key={date}>
              <div className="date-group-header">
                <span>{dayjs(date).format('YYYY 年 M 月 D 日')}</span>
                <span style={{ fontSize: 12, color: token.colorTextTertiary, fontWeight: 400 }}>
                  周{['一', '二', '三', '四', '五', '六', '日'][dayjs(date).day() === 0 ? 6 : dayjs(date).day() - 1]}
                </span>
              </div>
              {grouped[date].map((meal) => (
                <MealCard
                  key={meal.id}
                  meal={meal}
                  onClick={() => openDrawer(meal)}
                  isMobile={isMobile}
                  token={token}
                />
              ))}
            </div>
          ))}

          <div style={{ textAlign: 'right', marginTop: 24 }}>
            <Pagination
              current={page}
              total={total}
              pageSize={20}
              onChange={(p) => setPage(p)}
              showTotal={(t) => `共 ${t} 条`}
              size={isMobile ? 'small' : 'default'}
            />
          </div>
        </>
      )}

      {/* 详情抽屉 */}
      <Drawer
        title={
          selectedMeal ? (
            <span>
              <Tag color={MEAL_TYPE_COLORS[selectedMeal.meal_type] ?? 'default'}>
                {selectedMeal.meal_type}
              </Tag>
              {dayjs(selectedMeal.eaten_at).format('MM-DD HH:mm')}
            </span>
          ) : null
        }
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setEditMode(false); }}
        width={isMobile ? '100%' : 520}
        extra={
          selectedMeal && !editMode ? (
            <Space>
              <ShareCard kind="meal" mealId={selectedMeal.id} />
              <Button
                icon={<EditOutlined />}
                onClick={() => startEdit(selectedMeal)}
                size="small"
              >
                编辑
              </Button>
              <Popconfirm
                title="确定删除这顿饭吗？"
                onConfirm={() => handleDelete(selectedMeal.id)}
              >
                <Button danger icon={<DeleteOutlined />} size="small">
                  删除
                </Button>
              </Popconfirm>
            </Space>
          ) : editMode ? (
            <Space>
              <Button type="primary" loading={saving} onClick={handleSaveEdit} size="small">
                保存
              </Button>
              <Button onClick={() => setEditMode(false)} size="small">取消</Button>
            </Space>
          ) : null
        }
      >
        {selectedMeal && !editMode && (
          <DrawerView meal={selectedMeal} token={token} />
        )}
        {selectedMeal && editMode && (
          <div>
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>用餐时间</Text>
              <DatePicker
                showTime
                value={editEatenAt}
                onChange={(d) => d && setEditEatenAt(d)}
                style={{ width: '100%', marginTop: 4 }}
                format="YYYY-MM-DD HH:mm"
              />
            </div>
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>餐次类型</Text>
              <br />
              <Segmented
                options={meta?.meal_types ?? ['早餐', '午餐', '晚餐', '加餐', '饮品']}
                value={editMealType}
                onChange={(v) => setEditMealType(v as string)}
                block
                style={{ marginTop: 4 }}
              />
            </div>
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>备注</Text>
              <Input.TextArea
                value={editNote}
                onChange={(e) => setEditNote(e.target.value)}
                rows={2}
                style={{ marginTop: 4 }}
              />
            </div>
            <Divider>菜品明细</Divider>
            <MealItemsEditor
              items={editItems}
              onChange={setEditItems}
              tags={allTags}
              categories={meta?.categories ?? []}
              portions={meta?.portions ?? []}
            />
          </div>
        )}
      </Drawer>
    </div>
  );
}

interface TokenLike {
  colorBgContainer: string;
  colorTextTertiary: string;
  colorTextSecondary: string;
  colorFillAlter: string;
  colorBorderSecondary: string;
}

function MealCard({
  meal,
  onClick,
  isMobile,
  token,
}: {
  meal: MealOut;
  onClick: () => void;
  isMobile: boolean;
  token: TokenLike;
}) {
  const thumbSize = isMobile ? 72 : 80;
  return (
    <div
      className="meal-card"
      onClick={onClick}
      style={{
        display: 'flex',
        gap: 12,
        padding: isMobile ? '10px 12px' : '14px 16px',
        cursor: 'pointer',
        transition: 'box-shadow 0.2s',
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.1)')
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.boxShadow = '0 1px 6px rgba(0,0,0,0.06)')
      }
    >
      {/* 缩略图 */}
      <div style={{ flexShrink: 0 }}>
        {meal.image_url ? (
          <Image
            src={meal.thumb_url ?? meal.image_url}
            width={thumbSize}
            height={thumbSize}
            style={{ objectFit: 'cover', borderRadius: 10 }}
            preview={{ src: meal.image_url }}
            onClick={(e) => e.stopPropagation()}
            loading="lazy"
            decoding="async"
          />
        ) : (
          <div
            style={{
              width: thumbSize,
              height: thumbSize,
              borderRadius: 10,
              background: token.colorFillAlter,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 24,
            }}
          >
            🍽️
          </div>
        )}
      </div>

      {/* 内容 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: token.colorTextTertiary }}>
            {dayjs(meal.eaten_at).format('HH:mm')}
          </span>
          <Tag
            color={MEAL_TYPE_COLORS[meal.meal_type] ?? 'default'}
            style={{ margin: 0 }}
          >
            {meal.meal_type}
          </Tag>
          {meal.kcal_total != null && meal.kcal_total > 0 && (
            <span style={{
              fontSize: 11,
              color: token.colorTextSecondary,
              background: token.colorFillAlter,
              borderRadius: 10,
              padding: '1px 7px',
              border: `1px solid ${token.colorBorderSecondary}`,
              whiteSpace: 'nowrap',
            }}>
              ≈ {meal.kcal_total} kcal
            </span>
          )}
          {meal.note && (
            <span style={{
              fontSize: 12,
              color: token.colorTextTertiary,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: isMobile ? 100 : undefined,
            }}>
              {meal.note}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {meal.items.slice(0, isMobile ? 5 : 8).map((item) => (
            <span key={item.id}>
              <Tag
                color={categoryColor(item.category)}
                style={{ marginBottom: 2, cursor: 'default' }}
              >
                {item.name}
              </Tag>
              {item.tags
                .filter((t) => t.is_watch)
                .map((t) => (
                  <TagChip key={t.code} tag={t} />
                ))}
            </span>
          ))}
          {meal.items.length > (isMobile ? 5 : 8) && (
            <Tag color="default">+{meal.items.length - (isMobile ? 5 : 8)}</Tag>
          )}
        </div>
      </div>
    </div>
  );
}

function DrawerView({ meal, token }: { meal: MealOut; token: TokenLike }) {
  return (
    <div>
      {meal.image_url && (
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <Image
            src={meal.image_url}
            style={{ maxHeight: 260, maxWidth: '100%', borderRadius: 10, objectFit: 'contain' }}
          />
        </div>
      )}

      {meal.note && (
        <div style={{ marginBottom: 16, color: token.colorTextTertiary, fontStyle: 'italic' }}>
          "{meal.note}"
        </div>
      )}

      <Divider>菜品明细</Divider>

      {meal.items.map((item) => (
        <div
          key={item.id}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            padding: '8px 0',
            borderBottom: `1px solid var(--dd-border, #f5f5f5)`,
          }}
        >
          <div>
            <Tag color={categoryColor(item.category)} style={{ marginBottom: 4 }}>
              {item.category}
            </Tag>
            <strong>{item.name}</strong>
            <span style={{ fontSize: 12, color: token.colorTextTertiary, marginLeft: 8 }}>
              {item.portion}量
            </span>
            <div style={{ marginTop: 4 }}>
              {item.tags.map((t) => (
                <TagChip key={t.code} tag={t} />
              ))}
            </div>
          </div>
          <div style={{ textAlign: 'right', minWidth: 60 }}>
            {item.source === 'ai' && <Tag color="blue" style={{ fontSize: 10 }}>AI</Tag>}
            {item.source === 'ai_edited' && <Tag color="orange" style={{ fontSize: 10 }}>已改</Tag>}
            {item.source === 'user' && <Tag color="default" style={{ fontSize: 10 }}>手动</Tag>}
            {item.kcal != null && item.kcal > 0 && (
              <div style={{ fontSize: 11, color: token.colorTextTertiary, marginTop: 4 }}>
                ≈{item.kcal} kcal
              </div>
            )}
          </div>
        </div>
      ))}

      {meal.ai_raw_json && (
        <div style={{ marginTop: 20 }}>
          <Collapse
            ghost
            items={[
              {
                key: '1',
                label: '查看 AI 原始返回',
                children: (
                  <pre
                    style={{
                      background: 'var(--dd-fill-alter, #f8f8f8)',
                      padding: 12,
                      borderRadius: 6,
                      fontSize: 11,
                      overflow: 'auto',
                      maxHeight: 300,
                    }}
                  >
                    {(() => {
                      try {
                        return JSON.stringify(JSON.parse(meal.ai_raw_json ?? ''), null, 2);
                      } catch {
                        return meal.ai_raw_json;
                      }
                    })()}
                  </pre>
                ),
              },
            ]}
          />
        </div>
      )}

      {meal.kcal_total != null && meal.kcal_total > 0 && (
        <div style={{ marginTop: 12, fontSize: 13, color: 'var(--dd-text-secondary)', padding: '8px 0', borderTop: '1px solid var(--dd-border)' }}>
          本餐估算热量：<strong>≈ {meal.kcal_total} kcal</strong>
          <span style={{ fontSize: 11, color: 'var(--dd-text-tertiary)', marginLeft: 8 }}>仅供参考</span>
        </div>
      )}
      <div style={{ marginTop: 16, fontSize: 12, color: token.colorTextTertiary }}>
        AI 模型：{meal.ai_model ?? '—'} · 耗时：{meal.ai_latency_ms ?? '—'} ms
        <br />
        创建于 {dayjs(meal.created_at).format('YYYY-MM-DD HH:mm')}
      </div>
    </div>
  );
}

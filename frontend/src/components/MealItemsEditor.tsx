import { Button, Input, InputNumber, Progress, Select, Segmented, Tag, Space, Typography } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import type { TagOut, EditableItem, ItemSource, KcalSource } from '../api/types';
import { categoryColor } from '../utils/categoryColors';

const { Text } = Typography;

interface Props {
  items: EditableItem[];
  onChange: (items: EditableItem[]) => void;
  tags: TagOut[];
  categories: string[];
  portions: string[];
}

let _keyCounter = 0;
export function nextKey(): string {
  return `item-${++_keyCounter}`;
}

function sourceLabel(source: ItemSource) {
  if (source === 'ai') return <Tag color="blue">AI 识别</Tag>;
  if (source === 'ai_edited') return <Tag color="orange">已修改</Tag>;
  if (source === 'barcode') return <Tag color="purple">扫码</Tag>;
  return <Tag color="default">手动添加</Tag>;
}

function kcalSourceLabel(ks: KcalSource) {
  if (!ks) return null;
  const map: Record<string, string> = {
    ai: 'AI估',
    table: '表估',
    category: '粗估',
    user: '手填',
    barcode: '条码',
  };
  const label = map[ks] ?? ks;
  return (
    <Text type="secondary" style={{ fontSize: 10, marginLeft: 2 }}>
      {label}
    </Text>
  );
}

export default function MealItemsEditor({
  items,
  onChange,
  tags,
  categories,
  portions,
}: Props) {
  const watchTags = tags.filter((t) => t.is_watch);
  const structureTags = tags.filter((t) => !t.is_watch);

  const tagOptions = [
    {
      label: '关注项',
      options: watchTags.map((t) => ({ label: t.name_zh, value: t.code })),
    },
    {
      label: '结构项',
      options: structureTags.map((t) => ({ label: t.name_zh, value: t.code })),
    },
  ];

  function update(key: string, field: keyof EditableItem, value: unknown) {
    onChange(
      items.map((item) => {
        if (item._key !== key) return item;
        const updated: EditableItem = { ...item, [field]: value };
        if (item.source === 'ai' && field !== 'source' && field !== 'kcal' && field !== 'kcal_source') {
          updated.source = 'ai_edited';
        }
        return updated;
      })
    );
  }

  function updateKcal(key: string, val: number | null) {
    onChange(
      items.map((item) => {
        if (item._key !== key) return item;
        return {
          ...item,
          kcal: val,
          kcal_source: 'user' as KcalSource,
        };
      })
    );
  }

  function addItem() {
    const newItem: EditableItem = {
      _key: nextKey(),
      name: '',
      category: '其他',
      portion: '中',
      tags: [],
      source: 'user',
    };
    onChange([...items, newItem]);
  }

  function removeItem(key: string) {
    onChange(items.filter((item) => item._key !== key));
  }

  // Compute total kcal sum
  const kcalSum = items.reduce((acc, it) => {
    if (it.kcal != null && it.kcal > 0) return acc + it.kcal;
    return acc;
  }, 0);
  const hasAnyKcal = items.some((it) => it.kcal != null && it.kcal > 0);

  return (
    <div>
      {/* 图例 */}
      <div style={{ marginBottom: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Tag color="blue">AI 识别</Tag>
        <Tag color="orange">已修改</Tag>
        <Tag color="purple">扫码</Tag>
        <Tag color="default">手动添加</Tag>
        <span style={{ color: 'var(--dd-text-tertiary)', fontSize: 12 }}>— 来源标识</span>
      </div>

      {items.map((item, idx) => (
        <div
          key={item._key}
          style={{
            background: 'var(--dd-fill-alter)',
            border: '1px solid var(--dd-border)',
            borderRadius: 8,
            padding: '10px 14px',
            marginBottom: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <span style={{ color: 'var(--dd-text-tertiary)', fontSize: 12, minWidth: 20 }}>
              {idx + 1}.
            </span>
            <Input
              value={item.name}
              placeholder="菜品名称"
              onChange={(e) => update(item._key, 'name', e.target.value)}
              style={{ flex: '1 1 140px', minWidth: 100 }}
            />
            <Select
              value={item.category}
              onChange={(v) => update(item._key, 'category', v)}
              style={{ minWidth: 100 }}
              options={categories.map((c) => ({
                label: (
                  <Tag color={categoryColor(c)} style={{ margin: 0 }}>
                    {c}
                  </Tag>
                ),
                value: c,
              }))}
            />
            <Segmented
              options={portions.length ? portions : ['少', '中', '多']}
              value={item.portion}
              onChange={(v) => update(item._key, 'portion', v as string)}
              size="small"
            />
            {sourceLabel(item.source)}
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => removeItem(item._key)}
              size="small"
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Select
              mode="multiple"
              value={item.tags}
              onChange={(v) => update(item._key, 'tags', v)}
              options={tagOptions}
              placeholder="选择标签（可多选）"
              style={{ flex: 1, minWidth: 200 }}
              maxTagCount="responsive"
              tagRender={(props) => {
                const found = tags.find((t) => t.code === props.value);
                return (
                  <Tag
                    color={found?.is_watch ? 'orange' : 'lime'}
                    closable
                    onClose={props.onClose}
                    style={{ marginRight: 2 }}
                  >
                    {props.label}
                  </Tag>
                );
              }}
            />
            {item.confidence !== undefined && (
              <Space size={4} style={{ whiteSpace: 'nowrap' }}>
                <span style={{ fontSize: 11, color: 'var(--dd-text-tertiary)' }}>置信度</span>
                <Progress
                  percent={Math.round(item.confidence * 100)}
                  size="small"
                  style={{ width: 80 }}
                  strokeColor={item.confidence > 0.7 ? '#52c41a' : '#faad14'}
                />
              </Space>
            )}
          </div>

          {/* Kcal row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--dd-text-tertiary)' }}>热量估算</span>
            <InputNumber
              min={0}
              max={5000}
              value={item.kcal ?? undefined}
              onChange={(val) => updateKcal(item._key, val ?? null)}
              placeholder="kcal"
              addonAfter="kcal"
              style={{ width: 130 }}
              size="small"
            />
            {kcalSourceLabel(item.kcal_source ?? null)}
          </div>
        </div>
      ))}

      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={addItem}
        block
        style={{ marginTop: 4 }}
      >
        添加菜品
      </Button>

      {hasAnyKcal && (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--dd-text-tertiary)', textAlign: 'right' }}>
          本餐估算约 <strong style={{ color: 'var(--dd-text-secondary)' }}>{kcalSum}</strong> kcal · 仅供参考
        </div>
      )}
    </div>
  );
}

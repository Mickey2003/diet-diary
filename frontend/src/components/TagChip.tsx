import { Tag } from 'antd';
import type { TagOut } from '../api/types';

interface TagChipProps {
  tag: TagOut;
  style?: React.CSSProperties;
}

export default function TagChip({ tag, style }: TagChipProps) {
  const color = tag.is_watch ? 'orange' : 'lime';
  return (
    <Tag color={color} style={{ marginBottom: 2, ...style }}>
      {tag.name_zh}
    </Tag>
  );
}

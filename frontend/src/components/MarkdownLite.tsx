import React from 'react';

/** 极简 Markdown 渲染：支持 # 标题、- 列表、**加粗**、段落换行。 */

function parseInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /\*\*(.*?)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<strong key={match.index}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? <>{parts}</> : text;
}

interface Props {
  children: string;
  className?: string;
  style?: React.CSSProperties;
}

export default function MarkdownLite({ children, className, style }: Props) {
  const lines = String(children ?? '').replace(/\r\n?/g, '\n').split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('### ')) {
      elements.push(
        <h5 key={i} style={{ marginTop: 12, marginBottom: 4 }}>
          {parseInline(line.slice(4))}
        </h5>
      );
    } else if (line.startsWith('## ')) {
      elements.push(
        <h4 key={i} style={{ marginTop: 16, marginBottom: 6 }}>
          {parseInline(line.slice(3))}
        </h4>
      );
    } else if (line.startsWith('# ')) {
      elements.push(
        <h3 key={i} style={{ marginTop: 20, marginBottom: 8 }}>
          {parseInline(line.slice(2))}
        </h3>
      );
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      const listItems: string[] = [];
      while (
        i < lines.length &&
        (lines[i].startsWith('- ') || lines[i].startsWith('* '))
      ) {
        listItems.push(lines[i].slice(2));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} style={{ paddingLeft: 20, marginBottom: 8 }}>
          {listItems.map((li, j) => (
            <li key={j}>{parseInline(li)}</li>
          ))}
        </ul>
      );
      continue;
    } else if (/^-{3,}$/.test(line.trim()) || /^\*{3,}$/.test(line.trim())) {
      elements.push(
        <hr key={i} style={{ border: 'none', borderTop: '1px solid currentColor', opacity: 0.18, margin: '12px 0' }} />
      );
    } else if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ''));
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} style={{ paddingLeft: 22, marginBottom: 8 }}>
          {items.map((li, j) => (
            <li key={j}>{parseInline(li)}</li>
          ))}
        </ol>
      );
      continue;
    } else if (line.trim() === '') {
      elements.push(<div key={i} style={{ height: 8 }} />);
    } else {
      elements.push(
        <p key={i} style={{ marginBottom: 6 }}>
          {parseInline(line)}
        </p>
      );
    }
    i++;
  }

  return (
    <div className={className} style={{ lineHeight: 1.7, ...style }}>
      {elements}
    </div>
  );
}

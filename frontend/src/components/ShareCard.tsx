import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Collapse,
  Modal,
  Segmented,
  Spin,
  Space,
  Typography,
  message,
  theme as antdTheme,
} from 'antd';
import { ShareAltOutlined, PictureOutlined, CopyOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { generateShareCard, getShareHistory, attachShareImage } from '../api/share';
import type { ShareCardOut, ShareHistoryItem } from '../api/share';
import { isNativeApp, nativeShare } from '../native/bridge';
import { usePendingTasks, pollUntilDone } from '../hooks/usePendingTasks';

const { Text } = Typography;

const TONES = ['轻松', '励志', '文艺', '极简'] as const;
type Tone = typeof TONES[number];

interface Props {
  kind: 'weekly' | 'monthly' | 'today' | 'meal';
  anchor?: string;
  mealId?: number;
  label?: string;
}

// Canvas dimensions (4:5)
const CANVAS_W = 1080;
const CANVAS_H = 1350;

// Theme palettes
const THEMES: Record<string, { bg: string; accent: string; text: string; sub: string; tile: string }> = {
  warm:  { bg: '#fdf6ec', accent: '#f5a623', text: '#3a2e1e', sub: '#8a6e4e', tile: '#fff3e0' },
  fresh: { bg: '#f5fdf5', accent: '#52c41a', text: '#1a3a1a', sub: '#4a7a4a', tile: '#e8f5e9' },
  night: { bg: '#0d1b2a', accent: '#c9a227', text: '#e8dcc8', sub: '#9a8a6a', tile: '#1a2d42' },
};

/** 按最大宽度自适应字号，仍放不下则截断加省略号（避免文字溢出格子） */
function fitText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxW: number,
  size: number,
  opts: { bold?: boolean; min?: number } = {},
): { text: string; size: number } {
  const prefix = opts.bold ? 'bold ' : '';
  const min = opts.min ?? 14;
  const setFont = (px: number) => {
    ctx.font = `${prefix}${px}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  };
  let s = size;
  setFont(s);
  while (s > min && ctx.measureText(text).width > maxW) {
    s -= 2;
    setFont(s);
  }
  let out = text;
  if (ctx.measureText(out).width > maxW) {
    while (out.length > 1 && ctx.measureText(out + '…').width > maxW) {
      out = out.slice(0, -1);
    }
    out += '…';
  }
  return { text: out, size: s };
}


function drawCard(
  canvas: HTMLCanvasElement,
  card: ShareCardOut['card'],
  copy: ShareCardOut['copy'],
  disclaimer?: string,
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;

  const theme = THEMES[card.theme] ?? THEMES.warm;
  const pad = 80;

  // Background
  ctx.fillStyle = theme.bg;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

  // Top accent bar
  ctx.fillStyle = theme.accent;
  ctx.fillRect(0, 0, CANVAS_W, 8);

  let y = 100;

  // Title
  ctx.fillStyle = theme.accent;
  ctx.font = `bold 64px "PingFang SC", "Microsoft YaHei", sans-serif`;
  ctx.textAlign = 'center';
  const titleLines = drawCenteredLines(ctx, card.title, CANVAS_W / 2, y, CANVAS_W - pad * 2, 74, 2);
  y += titleLines * 74 + 12;

  // Subtitle
  if (card.subtitle) {
    ctx.fillStyle = theme.sub;
    ctx.font = `36px "PingFang SC", "Microsoft YaHei", sans-serif`;
    const lines = drawCenteredLines(ctx, card.subtitle, CANVAS_W / 2, y, CANVAS_W - pad * 2, 44, 2);
    y += lines * 44 + 10;
  }

  // Date range
  if (card.date_range) {
    ctx.fillStyle = theme.sub;
    ctx.font = `28px "PingFang SC", "Microsoft YaHei", sans-serif`;
    const lines = drawCenteredLines(ctx, card.date_range, CANVAS_W / 2, y, CANVAS_W - pad * 2, 36, 2);
    y += lines * 36 + 10;
  }

  y += 30;

  // Stats tiles
  const stats = (card.stats ?? []).slice(0, 4);
  if (stats.length > 0) {
    const tileW = (CANVAS_W - pad * 2 - 20 * (stats.length - 1)) / stats.length;
    const tileH = 160;
    for (let i = 0; i < stats.length; i++) {
      const tx = pad + i * (tileW + 20);
      ctx.fillStyle = theme.tile;
      ctx.beginPath();
      ctx.roundRect(tx, y, tileW, tileH, 16);
      ctx.fill();

      // 数值与标签都按格子宽度自适应，避免长菜名溢出
      ctx.fillStyle = theme.accent;
      ctx.textAlign = 'center';
      const vf = fitText(ctx, String(stats[i].value), tileW - 20, 52, { bold: true, min: 20 });
      ctx.fillText(vf.text, tx + tileW / 2, y + 90);

      ctx.fillStyle = theme.sub;
      const lf = fitText(ctx, stats[i].label, tileW - 16, 24, { min: 16 });
      ctx.fillText(lf.text, tx + tileW / 2, y + 138);
    }
    y += tileH + 50;
  }

  // Highlight
  if (card.highlight) {
    ctx.fillStyle = theme.tile;
    ctx.beginPath();
    ctx.roundRect(pad, y, CANVAS_W - pad * 2, 90, 12);
    ctx.fill();
    ctx.fillStyle = theme.text;
    ctx.textAlign = 'center';
    const hf = fitText(ctx, card.highlight, CANVAS_W - pad * 2 - 56, 30, { min: 18 });
    ctx.fillText(hf.text, CANVAS_W / 2, y + 56, CANVAS_W - pad * 2 - 40);
    y += 120;
  }

  // ---- 底部文案区：锚定在卡片底部，避免标题浮在中间、分隔线过高 ----
  const footerY = CANVAS_H - 60;
  const disclaimerH = disclaimer ? 34 : 0;
  const bottomLimit = footerY - 26 - disclaimerH; // 文案块底边（hashtags 基线）上限

  const H_HEAD = 58;
  const H_BODY = 46;
  const headLine = `${copy.emoji ?? ''} ${copy.headline}`.trim();

  // 预量文本行数
  ctx.font = `bold 48px "PingFang SC", "Microsoft YaHei", sans-serif`;
  const headLines = wrapText(ctx, headLine, CANVAS_W - pad * 2).slice(0, 2);
  ctx.font = `32px "PingFang SC", "Microsoft YaHei", sans-serif`;
  const bodyLines = wrapText(ctx, copy.body, CANVAS_W - pad * 2).slice(0, 3);

  const blockH = headLines.length * H_HEAD + 14 + bodyLines.length * H_BODY + 18 + 34;
  // 文案块顶部：尽量贴底；若上方内容较多则保持最小间距
  let by = Math.min(bottomLimit - blockH, y + 40);
  if (by < y + 20) by = y + 20;

  // 分隔线（位于底部文案区上方）
  const dividerY = by - 28;
  ctx.strokeStyle = theme.sub;
  ctx.globalAlpha = 0.3;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pad, dividerY);
  ctx.lineTo(CANVAS_W - pad, dividerY);
  ctx.stroke();
  ctx.globalAlpha = 1;

  ctx.textAlign = 'center';
  // 标题（emoji + headline）
  ctx.fillStyle = theme.accent;
  ctx.font = `bold 48px "PingFang SC", "Microsoft YaHei", sans-serif`;
  headLines.forEach((line, i) => ctx.fillText(line, CANVAS_W / 2, by + 40 + i * H_HEAD));
  by += headLines.length * H_HEAD + 14;

  // 正文
  ctx.fillStyle = theme.text;
  ctx.font = `32px "PingFang SC", "Microsoft YaHei", sans-serif`;
  bodyLines.forEach((line, i) => ctx.fillText(line, CANVAS_W / 2, by + 30 + i * H_BODY));
  by += bodyLines.length * H_BODY + 18;

  // 标签
  ctx.fillStyle = theme.accent;
  ctx.font = `26px "PingFang SC", "Microsoft YaHei", sans-serif`;
  ctx.fillText(copy.hashtags.join(' '), CANVAS_W / 2, by + 26, CANVAS_W - pad * 2);
  ctx.textAlign = 'left';

  // Footer
  ctx.fillStyle = theme.sub;
  ctx.font = `22px "PingFang SC", "Microsoft YaHei", sans-serif`;
  ctx.textAlign = 'center';
  ctx.fillText(
    `今天吃得怎么样 · AI 饮食日记 · ${dayjs().format('YYYY-MM-DD')}`,
    CANVAS_W / 2,
    footerY,
  );

  // Bottom bar
  ctx.fillStyle = theme.accent;
  ctx.fillRect(0, CANVAS_H - 8, CANVAS_W, 8);

  // Disclaimer
  if (disclaimer) {
    ctx.fillStyle = theme.sub;
    ctx.globalAlpha = 0.5;
    ctx.font = `18px "PingFang SC", "Microsoft YaHei", sans-serif`;
    ctx.fillText(disclaimer.slice(0, 60), CANVAS_W / 2, footerY - 30, CANVAS_W - pad * 2);
    ctx.globalAlpha = 1;
  }
}

function drawCenteredLines(ctx: CanvasRenderingContext2D, text: string, centerX: number, startY: number, maxW: number, lineHeight: number, maxLines = 3): number {
  const lines = wrapText(ctx, text, maxW).slice(0, maxLines);
  lines.forEach((line, index) => ctx.fillText(line, centerX, startY + index * lineHeight));
  return lines.length;
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const lines: string[] = [];
  let line = '';
  for (const ch of text) {
    const test = line + ch;
    if (ctx.measureText(test).width > maxW && line) {
      lines.push(line);
      line = ch;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines;
}

export default function ShareCard({ kind, anchor, mealId, label }: Props) {
  const [open, setOpen] = useState(false);
  const [tone, setTone] = useState<Tone>('轻松');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ShareCardOut | null>(null);
  const [history, setHistory] = useState<ShareHistoryItem[]>([]);
  const [viewing, setViewing] = useState<ShareHistoryItem | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const uploadedRef = useRef<string | null>(null);
  const pending = usePendingTasks();
  const [remoteBusy, setRemoteBusy] = useState(false);
  const { token } = antdTheme.useToken();
  const native = isNativeApp();

  useEffect(() => {
    if (open) {
      getShareHistory(10).then(setHistory).catch(() => {/* ignore */});
    }
  }, [open]);

  // 刷新后若服务端仍在生成卡片，则恢复等待，避免重复点击
  useEffect(() => {
    if (!pending.share) return;
    setRemoteBusy(true);
    const stop = pollUntilDone('share', () => {
      setRemoteBusy(false);
      getShareHistory(10).then(setHistory).catch(() => {/* ignore */});
    });
    return stop;
  }, [pending.share]);

  useEffect(() => {
    if (result && canvasRef.current) {
      drawCard(canvasRef.current, result.card, result.copy, result.disclaimer);
      // 渲染完成后上传卡片图（仅一次），历史记录即可查看/下载
      if (result.created_at && uploadedRef.current !== result.created_at) {
        uploadedRef.current = result.created_at;
        attachShareImage(canvasRef.current.toDataURL('image/png'), result.created_at)
          .then(() => getShareHistory(10))
          .then(setHistory)
          .catch(() => { /* 上传失败不影响本次使用 */ });
      }
    }
  }, [result]);

  async function handleGenerate() {
    setLoading(true);
    setResult(null);
    try {
      const r = await generateShareCard({
        kind,
        anchor,
        meal_id: mealId,
        tone,
      });
      setResult(r);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }

  function handleSaveImage() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = `diet-share-${dayjs().format('YYYYMMDD')}.png`;
    a.click();
  }

  function handleDownload(url: string, filename: string) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function handleCopyText() {
    if (!result) return;
    const text = `${result.copy.headline}\n${result.copy.body}\n${result.copy.hashtags.join(' ')}`;
    navigator.clipboard.writeText(text).then(() => message.success('已复制文案')).catch(() => {
      message.warning('复制失败，请手动选取');
    });
  }

  async function handleShare() {
    if (!result) return;
    const canvas = canvasRef.current;
    const text = `${result.copy.headline}\n${result.copy.body}\n${result.copy.hashtags.join(' ')}`;
    const title = result.card.title;

    if (canvas) {
      const dataUrl = canvas.toDataURL('image/png');

      // Try native share with files
      if (typeof navigator.share === 'function' && navigator.canShare) {
        const blob = await new Promise<Blob | null>((res) =>
          canvas.toBlob((b) => res(b), 'image/png')
        );
        if (blob) {
          const file = new File([blob], 'diet-share.png', { type: 'image/png' });
          if (navigator.canShare({ files: [file] })) {
            try {
              await navigator.share({ title, text, files: [file] });
              return;
            } catch {/* user cancelled */}
          }
        }
      }

      // Native app bridge
      if (native) {
        nativeShare(title, text, dataUrl);
        return;
      }
    }

    // Fallback: copy text + save image
    handleCopyText();
    handleSaveImage();
    message.info('已复制文案并保存图片');
  }

  return (
    <>
      <Button
        icon={<ShareAltOutlined />}
        onClick={() => setOpen(true)}
      >
        {label ?? '生成分享卡片'}
      </Button>

      <Modal
        open={open}
        title="生成分享卡片"
        onCancel={() => setOpen(false)}
        footer={null}
        width={600}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {/* Tone selector */}
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              文案风格
            </Text>
            <Segmented
              options={TONES.map((t) => ({ label: t, value: t }))}
              value={tone}
              onChange={(v) => setTone(v as Tone)}
            />
          </div>

          <Button
            type="primary"
            onClick={handleGenerate}
            loading={loading || remoteBusy}
            disabled={loading || remoteBusy}
            block
          >
            {remoteBusy ? '生成中…' : '生成卡片'}
          </Button>

          {(loading || remoteBusy) && (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <Spin />
              <div style={{ marginTop: 8, color: token.colorTextSecondary, fontSize: 12 }}>
                AI 正在生成文案…
              </div>
            </div>
          )}

          {result && (
            <div>
              {/* Canvas preview */}
              <div style={{ overflowX: 'auto', textAlign: 'center', marginBottom: 12 }}>
                <canvas
                  ref={canvasRef}
                  style={{
                    maxWidth: '100%',
                    height: 'auto',
                    borderRadius: 8,
                    boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
                  }}
                />
              </div>

              {/* Copy preview */}
              <div
                style={{
                  background: token.colorFillAlter,
                  borderRadius: 8,
                  padding: 12,
                  marginBottom: 12,
                  fontSize: 13,
                }}
              >
                <div style={{ fontWeight: 600 }}>{result.copy.headline}</div>
                <div style={{ color: token.colorTextSecondary, marginTop: 4 }}>{result.copy.body}</div>
                <div style={{ color: token.colorPrimary, marginTop: 4, fontSize: 12 }}>
                  {result.copy.hashtags.join(' ')}
                </div>
              </div>

              {/* Action buttons */}
              <Space wrap>
                <Button icon={<PictureOutlined />} onClick={handleSaveImage}>
                  保存图片
                </Button>
                <Button icon={<CopyOutlined />} onClick={handleCopyText}>
                  复制文案
                </Button>
                <Button icon={<ShareAltOutlined />} type="primary" onClick={handleShare}>
                  分享
                </Button>
              </Space>

              {/* Disclaimer */}
              {result.disclaimer && (
                <Alert
                  type="info"
                  showIcon
                  message={result.disclaimer}
                  style={{ marginTop: 12, fontSize: 11 }}
                />
              )}
            </div>
          )}

          {/* History（带缩略图，可查看大图/下载） */}
          {history.length > 0 && (
            <Collapse
              ghost
              items={[
                {
                  key: 'history',
                  label: `历史卡片（${history.length} 条）`,
                  children: (
                    <div style={{ maxHeight: 280, overflow: 'auto' }}>
                      {history.map((h, i) => (
                        <div
                          key={i}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                            padding: '8px 0',
                            borderBottom: `1px solid ${token.colorBorderSecondary}`,
                            fontSize: 12,
                          }}
                        >
                          {h.image_url ? (
                            <img
                              src={h.image_url}
                              alt="分享卡片"
                              onClick={() => setViewing(h)}
                              style={{
                                width: 44,
                                height: 56,
                                objectFit: 'cover',
                                borderRadius: 6,
                                cursor: 'pointer',
                                flexShrink: 0,
                              }}
                            />
                          ) : (
                            <div
                              style={{
                                width: 44,
                                height: 56,
                                borderRadius: 6,
                                flexShrink: 0,
                                background: token.colorFillAlter,
                                display: 'grid',
                                placeItems: 'center',
                                fontSize: 18,
                              }}
                            >
                              🖼
                            </div>
                          )}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <Text type="secondary">{dayjs(h.created_at).format('MM-DD HH:mm')}</Text>
                            <Text style={{ marginLeft: 8 }}>{h.kind}</Text>
                            <Text style={{ marginLeft: 8 }} type="secondary">风格：{h.tone}</Text>
                            {h.copy && (
                              <div style={{ color: token.colorTextSecondary, marginTop: 2 }}>
                                {h.copy.headline}
                              </div>
                            )}
                          </div>
                          {h.image_url && (
                            <Button size="small" type="link" onClick={() => setViewing(h)}>
                              查看
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  ),
                },
              ]}
            />
          )}
        </Space>
      </Modal>

      {/* 历史卡片大图查看 */}
      <Modal
        open={!!viewing}
        title="历史分享卡片"
        onCancel={() => setViewing(null)}
        footer={null}
        width={520}
        destroyOnClose
      >
        {viewing && (
          <div>
            {viewing.image_url ? (
              <img
                src={viewing.image_url}
                alt="分享卡片"
                style={{ width: '100%', borderRadius: 8 }}
              />
            ) : (
              <Alert type="info" showIcon message="该条历史没有保存图片" />
            )}
            {viewing.copy && (
              <div style={{ marginTop: 10, fontSize: 13 }}>
                <div style={{ fontWeight: 600 }}>{viewing.copy.headline}</div>
                <div style={{ color: token.colorTextSecondary, marginTop: 4 }}>
                  {viewing.copy.body}
                </div>
                <div style={{ color: token.colorPrimary, marginTop: 4, fontSize: 12 }}>
                  {viewing.copy.hashtags?.join(' ')}
                </div>
              </div>
            )}
            <Space style={{ marginTop: 12 }} wrap>
              {viewing.image_url && (
                <Button
                  icon={<PictureOutlined />}
                  onClick={() => handleDownload(
                    viewing.image_url as string,
                    `diet-share-${dayjs(viewing.created_at).format('YYYYMMDD-HHmm')}.png`,
                  )}
                >
                  下载图片
                </Button>
              )}
              {viewing.copy && (
                <Button
                  icon={<CopyOutlined />}
                  onClick={() => {
                    const t = `${viewing.copy?.headline ?? ''}\n${viewing.copy?.body ?? ''}`;
                    navigator.clipboard.writeText(t)
                      .then(() => message.success('已复制文案'))
                      .catch(() => message.warning('复制失败，请手动选取'));
                  }}
                >
                  复制文案
                </Button>
              )}
            </Space>
          </div>
        )}
      </Modal>
    </>
  );
}

import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Drawer,
  Space,
  Skeleton,
  Tag,
  Typography,
  message,
  theme as antdTheme,
  Grid,
  Divider,
} from 'antd';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import MarkdownLite from '../components/MarkdownLite';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import client from '../api/client';
import { UnreadContext } from '../context/UnreadContext';

const { Text, Title } = Typography;
const { useBreakpoint } = Grid;

interface InboxExtra {
  markdown?: boolean;
  sound_url?: string;
  volume?: number;
  vibrate?: boolean;
  meal_type?: string;
  time?: string;
}

interface InboxMessage {
  id: number;
  kind: string;
  kind_label?: string;
  title: string;
  body: string;
  url?: string;
  extra?: InboxExtra;
  created_at: string;
  read_at: string | null;
}

interface InboxDetailMessage extends InboxMessage {
  kind_label: string;
}

function hasMarkdownMarkers(text: string): boolean {
  return /^#+ /m.test(text) || /^- /m.test(text) || /\*\*/.test(text);
}

export default function InboxPage() {
  const { token } = antdTheme.useToken();
  const navigate = useNavigate();
  const { id: routeId } = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();
  const unreadCtx = useContext(UnreadContext);
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const [msgs, setMsgs] = useState<InboxMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  // Detail drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailMsg, setDetailMsg] = useState<InboxDetailMessage | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const loadMessages = useCallback(async () => {
    setLoading(true);
    try {
      const res = await client.get<{ messages: InboxMessage[] }>('/api/notify/inbox', {
        params: { since_id: 0, limit: 100 },
      });
      const reversed = (res.data.messages ?? []).slice().reverse();
      setMsgs(reversed);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  // Open specific message from route param or ?id=
  useEffect(() => {
    const idStr = routeId ?? searchParams.get('id');
    if (!idStr) return;
    const id = parseInt(idStr, 10);
    if (isNaN(id)) return;
    openDetail(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId, searchParams]);

  async function markRead(id: number) {
    try {
      await client.post('/api/notify/inbox/read', [id]);
      setMsgs((prev) =>
        prev.map((m) => (m.id === id ? { ...m, read_at: new Date().toISOString() } : m)),
      );
      unreadCtx?.refresh();
    } catch {
      /* ignore */
    }
  }

  async function openDetail(id: number) {
    setDrawerOpen(true);
    setDetailLoading(true);
    setDetailMsg(null);
    try {
      const res = await client.get<InboxDetailMessage>(`/api/notify/inbox/${id}`);
      setDetailMsg(res.data);
      if (!res.data.read_at) {
        await markRead(id);
      }
    } catch {
      /* error shown by interceptor */
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleTapMessage(m: InboxMessage) {
    await openDetail(m.id);
  }

  async function handleMarkAllRead() {
    const unreadIds = msgs.filter((m) => !m.read_at).map((m) => m.id);
    if (unreadIds.length === 0) return;
    setMarkingAll(true);
    try {
      await client.post('/api/notify/inbox/read-all');
      setMsgs((prev) =>
        prev.map((m) => ({ ...m, read_at: m.read_at ?? new Date().toISOString() })),
      );
      message.success('已全部标为已读');
      unreadCtx?.refresh();
    } catch {
      /* error shown by interceptor */
    } finally {
      setMarkingAll(false);
    }
  }

  function playSound(url: string, vol: number) {
    try {
      if (!audioRef.current) audioRef.current = new Audio();
      const a = audioRef.current;
      a.pause();
      a.src = url;
      a.volume = Math.min(1, Math.max(0, vol));
      const p = a.play();
      if (p) p.catch(() => { message.info('浏览器限制自动播放，请先与页面交互后重试'); });
    } catch { /* ignore */ }
  }

  const unreadCount = msgs.filter((m) => !m.read_at).length;

  // Kind to color map
  function kindColor(kind: string): string {
    const map: Record<string, string> = {
      meal_alert: 'orange',
      daily_reminder: 'blue',
      daily_summary: 'green',
      weekly_report: 'purple',
      system: 'default',
    };
    return map[kind] ?? 'default';
  }

  // Detail drawer content
  const renderDetail = () => {
    if (detailLoading) {
      return <Skeleton active paragraph={{ rows: 5 }} />;
    }
    if (!detailMsg) return null;

    const useMarkdown =
      detailMsg.extra?.markdown === true || hasMarkdownMarkers(detailMsg.body ?? '');

    const isMealAlert = detailMsg.kind === 'meal_alert';
    const soundUrl = detailMsg.extra?.sound_url;
    const soundVol = detailMsg.extra?.volume ?? 0.8;

    return (
      <div>
        {/* Header */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            {isMealAlert && <span style={{ fontSize: 18 }}>🍽️</span>}
            <Title level={5} style={{ margin: 0, flex: 1, wordBreak: 'break-word' }}>
              {detailMsg.title}
            </Title>
          </div>
          <Space wrap size={6}>
            <Tag color={kindColor(detailMsg.kind)} style={{ margin: 0 }}>
              {detailMsg.kind_label || detailMsg.kind}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(detailMsg.created_at).format('YYYY-MM-DD HH:mm')}
            </Text>
            {detailMsg.read_at && (
              <Text type="secondary" style={{ fontSize: 11 }}>· 已读</Text>
            )}
          </Space>
        </div>

        <Divider style={{ margin: '12px 0' }} />

        {/* Body */}
        <div style={{ marginBottom: 16 }}>
          {useMarkdown ? (
            <MarkdownLite style={{ fontSize: 14, lineHeight: 1.8 }}>
              {detailMsg.body ?? ''}
            </MarkdownLite>
          ) : (
            <Text style={{ fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', display: 'block', wordBreak: 'break-word' }}>
              {detailMsg.body ?? ''}
            </Text>
          )}
        </div>

        {/* Actions */}
        <Space wrap>
          {detailMsg.url && (
            <Button
              type="primary"
              onClick={() => {
                if (detailMsg.url!.startsWith('/')) {
                  navigate(detailMsg.url!);
                  setDrawerOpen(false);
                } else {
                  window.open(detailMsg.url!, '_blank', 'noopener,noreferrer');
                }
              }}
            >
              前往查看
            </Button>
          )}
          {isMealAlert && soundUrl && (
            <Button
              onClick={() => playSound(soundUrl, soundVol)}
            >
              试听音效
            </Button>
          )}
        </Space>
      </div>
    );
  };

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <PageHeader title="消息中心" subtitle="系统与提醒消息" />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <Space>
          <Text strong style={{ fontSize: 16 }}>消息中心</Text>
          {unreadCount > 0 && <Badge count={unreadCount} size="small" />}
        </Space>
        <Space>
          <Button
            size="small"
            onClick={handleMarkAllRead}
            loading={markingAll}
            disabled={unreadCount === 0}
          >
            全部标为已读
          </Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={loadMessages} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {loading && msgs.length === 0 ? (
        <div>
          <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 12 }} />
          <Skeleton active paragraph={{ rows: 2 }} />
        </div>
      ) : msgs.length === 0 ? (
        <EmptyState emoji="📭" hint="收件箱为空，暂无消息" />
      ) : (
        <div
          style={{
            background: token.colorBgContainer,
            borderRadius: 10,
            overflow: 'hidden',
            boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          }}
        >
          {msgs.map((m, idx) => {
            const isUnread = !m.read_at;
            const isMealAlert = m.kind === 'meal_alert';
            return (
              <div
                key={m.id}
                onClick={() => handleTapMessage(m)}
                style={{
                  padding: '12px 16px',
                  borderBottom:
                    idx < msgs.length - 1
                      ? `1px solid ${token.colorBorderSecondary}`
                      : 'none',
                  cursor: 'pointer',
                  background: isUnread ? token.colorPrimaryBg : 'transparent',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background = token.colorFillAlter)
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background =
                    isUnread ? token.colorPrimaryBg : 'transparent')
                }
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 4,
                    flexWrap: 'wrap',
                  }}
                >
                  {isMealAlert && <span style={{ fontSize: 14 }}>🍽️</span>}
                  {isUnread && (
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: token.colorPrimary,
                        display: 'inline-block',
                        flexShrink: 0,
                      }}
                    />
                  )}
                  <Text
                    strong={isUnread}
                    style={{
                      flex: 1,
                      fontSize: 14,
                      color: isUnread ? token.colorText : token.colorTextSecondary,
                    }}
                  >
                    {m.title}
                  </Text>
                  <Tag
                    color={kindColor(m.kind)}
                    style={{ margin: 0, fontSize: 10 }}
                  >
                    {m.kind_label || m.kind}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>
                    {dayjs(m.created_at).format('MM-DD HH:mm')}
                  </Text>
                </div>
                <Text
                  style={{
                    fontSize: 13,
                    color: token.colorTextSecondary,
                    display: 'block',
                    paddingLeft: isUnread ? 16 : 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '100%',
                  }}
                >
                  {m.body}
                </Text>
              </div>
            );
          })}
        </div>
      )}

      {/* Detail Drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        placement="right"
        width={isMobile ? '100%' : 520}
        title="消息详情"
        destroyOnClose
      >
        {renderDetail()}
      </Drawer>
    </div>
  );
}

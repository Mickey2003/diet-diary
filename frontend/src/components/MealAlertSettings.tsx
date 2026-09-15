/** 就餐提醒音效设置组件，用于 Health 页和 Notify 页 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Collapse,
  InputNumber,
  message,
  Popconfirm,
  Radio,
  Slider,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  Input,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlayCircleOutlined, SaveOutlined } from '@ant-design/icons';
import { isNativeApp } from '../native/bridge';
import {
  getSounds,
  uploadSound,
  deleteSound,
  putAlertSettings,
  testAlertSettings,
  renameSound,
} from '../api/sounds';
import type { AlertSettings, SoundFile, SoundPreset } from '../api/sounds';
import SoundPresetAdmin from './SoundPresetAdmin';

const { Text } = Typography;

const MEAL_TYPE_OPTIONS = [
  { label: '早餐', value: '早餐' },
  { label: '午餐', value: '午餐' },
  { label: '晚餐', value: '晚餐' },
  { label: '加餐', value: '加餐' },
];

const DEFAULT_SETTINGS: AlertSettings = {
  enabled: false,
  sound: '',
  lead_minutes: 5,
  meal_types: ['早餐', '午餐', '晚餐'],
  volume: 0.8,
  vibrate: false,
};

export default function MealAlertSettings() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [presets, setPresets] = useState<SoundPreset[]>([]);
  const [mine, setMine] = useState<SoundFile[]>([]);
  const [settings, setSettings] = useState<AlertSettings>(DEFAULT_SETTINGS);
  const [canManagePresets, setCanManagePresets] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameVal, setRenameVal] = useState('');
  const [renameSaving, setRenameSaving] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getSounds();
      setPresets(data.presets ?? []);
      setMine(data.mine ?? []);
      setSettings({ ...DEFAULT_SETTINGS, ...(data.settings ?? {}) });
      setCanManagePresets(!!data.can_manage_presets);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function playPreview(url: string) {
    try {
      if (!audioRef.current) {
        audioRef.current = new Audio();
      }
      const audio = audioRef.current;
      audio.pause();
      audio.src = url;
      audio.volume = Math.min(1, Math.max(0, settings.volume ?? 0.8));
      const p = audio.play();
      if (p) p.catch(() => { /* autoplay may be blocked */ });
    } catch {
      /* ignore */
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await putAlertSettings({
        enabled: settings.enabled,
        sound: settings.sound,
        lead_minutes: settings.lead_minutes,
        meal_types: settings.meal_types,
        volume: settings.volume,
        vibrate: settings.vibrate,
      });
      setSettings({ ...DEFAULT_SETTINGS, ...updated });
      message.success('设置已保存');
    } catch {
      /* error shown by interceptor */
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      await testAlertSettings();
      message.success(isNativeApp() ? '已发送测试提醒到 App' : '已发送到消息中心');
    } catch {
      /* error shown by interceptor */
    } finally {
      setTesting(false);
    }
  }

  async function handleUpload() {
    if (!uploadFile) return;
    setUploading(true);
    try {
      await uploadSound(uploadFile, uploadName.trim() || uploadFile.name.replace(/\.[^.]+$/, ''));
      message.success('上传成功');
      setUploadFile(null);
      setUploadName('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      await load();
    } catch {
      /* error shown by interceptor */
    } finally {
      setUploading(false);
    }
  }

  async function handleDeleteMine(id: number) {
    try {
      await deleteSound(id);
      message.success('已删除');
      await load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleSaveRename(f: SoundFile) {
    const trimmed = renameVal.trim();
    if (!trimmed) return;
    setRenameSaving(true);
    try {
      await renameSound(f.id, trimmed);
      message.success('名称已更新');
      setRenamingId(null);
      await load();
    } catch {
      /* error shown by interceptor */
    } finally {
      setRenameSaving(false);
    }
  }

  function selectSound(key: string, url: string) {
    setSettings((p) => ({ ...p, sound: key, sound_url: url }));
  }

  if (loading) {
    return (
      <Card title="就餐提醒音效" size="small" style={{ marginBottom: 16 }}>
        <Spin size="small" />
      </Card>
    );
  }

  return (
    <Card title="就餐提醒音效" size="small" style={{ marginBottom: 16 }}>
      {/* 启用开关 */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Switch
          checked={settings.enabled}
          onChange={(v) => setSettings((p) => ({ ...p, enabled: v }))}
          size="small"
        />
        <Text>启用就餐提醒</Text>
      </div>

      {settings.enabled && (
        <>
          {/* 提前分钟 */}
          <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>提前</Text>
            <InputNumber
              size="small"
              min={0}
              max={60}
              value={settings.lead_minutes}
              onChange={(v) => setSettings((p) => ({ ...p, lead_minutes: v ?? 0 }))}
              style={{ width: 64 }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>分钟提醒</Text>
          </div>

          {/* 餐次 */}
          <div style={{ marginBottom: 14 }}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>提醒的餐次</Text>
            <Checkbox.Group
              options={MEAL_TYPE_OPTIONS}
              value={settings.meal_types ?? []}
              onChange={(vals) => setSettings((p) => ({ ...p, meal_types: vals as string[] }))}
            />
          </div>

          {/* 音量 */}
          <div style={{ marginBottom: 14 }}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              音量：{Math.round((settings.volume ?? 0.8) * 100)}%
            </Text>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={settings.volume ?? 0.8}
              onChange={(v) => setSettings((p) => ({ ...p, volume: v }))}
              style={{ maxWidth: 220 }}
            />
          </div>

          {/* 振动 */}
          <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Switch
              size="small"
              checked={!!settings.vibrate}
              onChange={(v) => setSettings((p) => ({ ...p, vibrate: v }))}
            />
            <Text style={{ fontSize: 12 }}>振动</Text>
            {!isNativeApp() && (
              <Tag color="default" style={{ fontSize: 10 }}>仅 App 有效</Tag>
            )}
          </div>

          {/* 系统预设音效 */}
          {presets.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                系统预设音效
              </Text>
              <Radio.Group
                value={settings.sound}
                onChange={(e) => {
                  const pr = presets.find((p) => p.key === e.target.value);
                  selectSound(e.target.value, pr?.url ?? '');
                }}
              >
                <Space direction="vertical" size={4}>
                  {presets.map((preset) => (
                    <Space key={preset.key} size={8}>
                      <Radio value={preset.key}>{preset.name}</Radio>
                      <Button
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() => playPreview(preset.url)}
                      >
                        试听
                      </Button>
                    </Space>
                  ))}
                </Space>
              </Radio.Group>
            </div>
          )}

          {/* 我的上传 */}
          {mine.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                我的上传
              </Text>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                {mine.map((f) => (
                  <Space key={f.id} size={8} wrap>
                    <Radio
                      checked={settings.sound === f.key}
                      onChange={() => selectSound(f.key, f.url)}
                    >
                      {renamingId === f.id ? (
                        <Space size={4}>
                          <Input
                            size="small"
                            value={renameVal}
                            onChange={(e) => setRenameVal(e.target.value)}
                            style={{ width: 100 }}
                            onPressEnter={() => handleSaveRename(f)}
                          />
                          <Button
                            size="small"
                            type="primary"
                            icon={<SaveOutlined />}
                            loading={renameSaving}
                            onClick={() => handleSaveRename(f)}
                          />
                          <Button size="small" onClick={() => setRenamingId(null)}>取消</Button>
                        </Space>
                      ) : (
                        <span>{f.name}</span>
                      )}
                    </Radio>
                    {renamingId !== f.id && (
                      <Button
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => { setRenamingId(f.id); setRenameVal(f.name); }}
                      />
                    )}
                    <Button
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={() => playPreview(f.url)}
                    >
                      试听
                    </Button>
                    <Popconfirm title="确定删除此音效？" onConfirm={() => handleDeleteMine(f.id)}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                ))}
              </Space>
            </div>
          )}

          {/* 上传音效 */}
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              上传自定义音效（audio/*，≤ 3MB）
            </Text>
            <Space wrap>
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                style={{ fontSize: 12 }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (!f) { setUploadFile(null); return; }
                  if (f.size > 3 * 1024 * 1024) {
                    message.warning('文件不能超过 3MB');
                    e.target.value = '';
                    return;
                  }
                  setUploadFile(f);
                  setUploadName(f.name.replace(/\.[^.]+$/, ''));
                }}
              />
              {uploadFile && (
                <>
                  <Input
                    size="small"
                    value={uploadName}
                    onChange={(e) => setUploadName(e.target.value)}
                    placeholder="音效名称"
                    style={{ width: 120 }}
                  />
                  <Button
                    size="small"
                    type="primary"
                    loading={uploading}
                    onClick={handleUpload}
                  >
                    上传
                  </Button>
                </>
              )}
            </Space>
          </div>
        </>
      )}

      <Space wrap>
        <Button type="primary" onClick={handleSave} loading={saving}>
          保存
        </Button>
        <Button onClick={handleTest} loading={testing}>
          发送测试提醒
        </Button>
      </Space>

      {/* Admin preset management (collapsed) */}
      {canManagePresets && (
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 16 }}
          items={[{
            key: 'admin',
            label: <Text type="secondary" style={{ fontSize: 12 }}>系统预设音效管理（管理员）</Text>,
            children: <SoundPresetAdmin onPresetsChanged={load} />,
          }]}
        />
      )}
    </Card>
  );
}

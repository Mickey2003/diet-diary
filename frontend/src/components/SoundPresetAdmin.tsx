/** 系统预设音效管理（仅管理员可见） */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Input,
  message,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlayCircleOutlined, SaveOutlined } from '@ant-design/icons';
import {
  getAdminPresets,
  uploadAdminPreset,
  patchBuiltinPreset,
  deleteSound,
} from '../api/sounds';
import type { SoundPreset } from '../api/sounds';

const { Text } = Typography;

interface Props {
  onPresetsChanged?: () => void;
}

export default function SoundPresetAdmin({ onPresetsChanged }: Props) {
  const [presets, setPresets] = useState<SoundPreset[]>([]);
  const [maxSystem, setMaxSystem] = useState(10);
  const [loading, setLoading] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploading, setUploading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAdminPresets();
      setPresets(data.presets ?? []);
      setMaxSystem(data.max_system ?? 10);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function playPreview(url: string) {
    try {
      if (!audioRef.current) audioRef.current = new Audio();
      const a = audioRef.current;
      a.pause();
      a.src = url;
      a.volume = 0.8;
      const p = a.play();
      if (p) p.catch(() => {/* autoplay blocked */});
    } catch {/* ignore */}
  }

  function startEdit(preset: SoundPreset) {
    setEditingKey(preset.key);
    setEditName(preset.name);
  }

  async function saveName(preset: SoundPreset) {
    const trimmed = editName.trim();
    if (!trimmed) return;
    setSavingKey(preset.key);
    try {
      if (preset.builtin) {
        // Extract key name after "preset:"
        const keyName = preset.key.startsWith('preset:') ? preset.key.slice(7) : preset.key;
        await patchBuiltinPreset(keyName, { name: trimmed });
      } else if (preset.id != null) {
        // system upload — use rename endpoint
        const { renameSound } = await import('../api/sounds');
        await renameSound(preset.id, trimmed);
      }
      message.success('名称已更新');
      setEditingKey(null);
      await load();
      onPresetsChanged?.();
    } catch {
      /* error shown by interceptor */
    } finally {
      setSavingKey(null);
    }
  }

  async function handleToggleVisible(preset: SoundPreset, visible: boolean) {
    if (!preset.builtin) return;
    const keyName = preset.key.startsWith('preset:') ? preset.key.slice(7) : preset.key;
    try {
      await patchBuiltinPreset(keyName, { hidden: !visible });
      message.success(visible ? '已设为可见' : '已对用户隐藏');
      await load();
      onPresetsChanged?.();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleDelete(preset: SoundPreset) {
    if (preset.id == null) return;
    try {
      await deleteSound(preset.id);
      message.success('已删除');
      await load();
      onPresetsChanged?.();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleUpload() {
    if (!uploadFile) return;
    setUploading(true);
    try {
      await uploadAdminPreset(
        uploadFile,
        uploadName.trim() || uploadFile.name.replace(/\.[^.]+$/, ''),
      );
      message.success('上传成功');
      setUploadFile(null);
      setUploadName('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      await load();
      onPresetsChanged?.();
    } catch {
      /* error shown by interceptor */
    } finally {
      setUploading(false);
    }
  }

  const systemUploads = presets.filter((p) => !p.builtin);
  const usedSystem = systemUploads.length;

  if (loading) return <Spin size="small" />;

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          已用系统上传 {usedSystem} / {maxSystem}
        </Text>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        {presets.map((preset) => (
          <div
            key={preset.key}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              flexWrap: 'wrap',
              padding: '6px 0',
              borderBottom: '1px solid var(--dd-border, #f0f0f0)',
            }}
          >
            {/* Play */}
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => playPreview(preset.url)}
            />

            {/* Name / edit */}
            {editingKey === preset.key ? (
              <Space size={4}>
                <Input
                  size="small"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  style={{ width: 120 }}
                  onPressEnter={() => saveName(preset)}
                />
                <Button
                  size="small"
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={savingKey === preset.key}
                  onClick={() => saveName(preset)}
                >
                  保存
                </Button>
                <Button size="small" onClick={() => setEditingKey(null)}>取消</Button>
              </Space>
            ) : (
              <Space size={4}>
                <Text style={{ fontSize: 13 }}>{preset.name}</Text>
                <Button
                  size="small"
                  type="text"
                  icon={<EditOutlined />}
                  onClick={() => startEdit(preset)}
                />
              </Space>
            )}

            {/* Tags */}
            {preset.builtin && <Tag color="blue" style={{ fontSize: 10 }}>内置</Tag>}
            {preset.hidden && <Tag color="default" style={{ fontSize: 10 }}>已隐藏</Tag>}

            {/* Builtin: visibility switch */}
            {preset.builtin && (
              <Space size={4} align="center">
                <Switch
                  size="small"
                  checked={!preset.hidden}
                  onChange={(v) => handleToggleVisible(preset, v)}
                  checkedChildren="可见"
                  unCheckedChildren="隐藏"
                />
                <Text type="secondary" style={{ fontSize: 11 }}>对用户可见</Text>
              </Space>
            )}

            {/* System upload: delete */}
            {!preset.builtin && preset.id != null && (
              <Popconfirm
                title="确定删除此系统预设音效？"
                onConfirm={() => handleDelete(preset)}
              >
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            )}
          </div>
        ))}
      </div>

      {/* Upload area */}
      <div>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          上传新系统预设（audio/*，≤ 3MB）
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
                placeholder="预设名称"
                style={{ width: 120 }}
              />
              <Button
                size="small"
                type="primary"
                loading={uploading}
                disabled={usedSystem >= maxSystem}
                onClick={handleUpload}
              >
                上传
              </Button>
            </>
          )}
        </Space>
        {usedSystem >= maxSystem && (
          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
            已达上限，请先删除旧预设再上传
          </Text>
        )}
      </div>
    </div>
  );
}

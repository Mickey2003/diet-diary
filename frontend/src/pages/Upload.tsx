import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload,
  Button,
  Alert,
  Segmented,
  DatePicker,
  Input,
  message,
  Spin,
  Typography,
  Divider,
  Image,
  Grid,
  theme as antdTheme,
} from 'antd';
import {
  InboxOutlined,
  ThunderboltOutlined,
  EditOutlined,
  SaveOutlined,
  CameraOutlined,
  PictureOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import type { UploadFile } from 'antd';
import MealItemsEditor, { nextKey } from '../components/MealItemsEditor';
import BarcodeScanner from '../components/BarcodeScanner';
import Disclaimer from '../components/Disclaimer';
import {
  getMeta,
  getTags,
  recognizeMeal,
  recognizeByPath,
  uploadOnly,
  createMeal,
} from '../api/endpoints';
import {
  isNativeApp,
  nativeTakePhoto,
  nativePickPhoto,
  getPendingUploadNative,
  clearPendingUploadNative,
} from '../native/bridge';
import type { MetaOut, TagOut, RecognizeOut, EditableItem } from '../api/types';

const { Dragger } = Upload;
const { TextArea } = Input;
const { Text } = Typography;
const { useBreakpoint } = Grid;

const DRAFT_KEY = 'dd-upload-draft';
const DRAFT_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours

interface Draft {
  image_path: string;
  image_url: string;
  result: RecognizeOut | null;
  items: EditableItem[];
  mealType: string;
  eatenAt: string; // ISO
  note: string;
  updatedAt: number; // timestamp ms
}

function saveDraft(draft: Partial<Draft>) {
  try {
    const existing = loadDraftRaw();
    const merged = { ...existing, ...draft, updatedAt: Date.now() };
    localStorage.setItem(DRAFT_KEY, JSON.stringify(merged));
  } catch {
    /* ignore */
  }
}

function loadDraftRaw(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw) as Draft;
    if (!d.updatedAt || Date.now() - d.updatedAt > DRAFT_MAX_AGE_MS) {
      localStorage.removeItem(DRAFT_KEY);
      return null;
    }
    return d;
  } catch {
    return null;
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* ignore */
  }
}

export default function UploadPage() {
  const navigate = useNavigate();
  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const native = isNativeApp();

  const [meta, setMeta] = useState<MetaOut | null>(null);
  const [allTags, setAllTags] = useState<TagOut[]>([]);

  // 上传文件状态
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string>('');

  // 识别结果
  const [recognizeResult, setRecognizeResult] = useState<RecognizeOut | null>(null);
  const [recognizing, setRecognizing] = useState(false);
  const [recognized, setRecognized] = useState(false);

  // 可编辑项目
  const [editableItems, setEditableItems] = useState<EditableItem[]>([]);

  // 餐食元数据
  const [mealType, setMealType] = useState<string>('早餐');
  const [eatenAt, setEatenAt] = useState<Dayjs>(dayjs());
  const [note, setNote] = useState('');

  // 保存状态
  const [saving, setSaving] = useState(false);

  // 是否已进入手动填写模式
  const [manualMode, setManualMode] = useState(false);
  const [serverImagePath, setServerImagePath] = useState<string>('');
  const [serverImageUrl, setServerImageUrl] = useState<string>('');

  // Draft restore
  const [draftAlert, setDraftAlert] = useState(false);

  // Track draft changes
  const draftSyncRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scheduleDraftSave(patch: Partial<Draft>) {
    if (draftSyncRef.current) clearTimeout(draftSyncRef.current);
    draftSyncRef.current = setTimeout(() => {
      saveDraft(patch);
    }, 300);
  }

  // Load draft and setup native photo on mount
  useEffect(() => {
    getMeta().then(setMeta).catch(() => {/* 忽略 */});
    getTags().then(setAllTags).catch(() => {/* 忽略 */});

    // Load local draft
    const draft = loadDraftRaw();
    if (draft) {
      restoreFromDraft(draft);
      setDraftAlert(true);
    }

    // Native: check pending upload
    if (native) {
      checkPendingUpload();
    }

    // Listen for dd:photo event
    const handlePhoto = (e: Event) => {
      const detail = (e as CustomEvent<{ image_path: string; image_url: string }>).detail;
      adoptNativePhoto(detail.image_path, detail.image_url);
    };
    window.addEventListener('dd:photo', handlePhoto);

    // On visibility change, re-check pending upload
    const handleVisibility = () => {
      if (!document.hidden && native) {
        checkPendingUpload();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      window.removeEventListener('dd:photo', handlePhoto);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function restoreFromDraft(draft: Draft) {
    if (draft.image_url) setPreviewUrl(draft.image_url);
    if (draft.image_path) setServerImagePath(draft.image_path);
    if (draft.image_url) setServerImageUrl(draft.image_url);
    if (draft.result) {
      setRecognizeResult(draft.result);
      setRecognized(true);
    }
    if (draft.items && draft.items.length > 0) {
      setEditableItems(draft.items);
      if (!draft.result) setManualMode(true);
    }
    if (draft.mealType) setMealType(draft.mealType);
    if (draft.eatenAt) setEatenAt(dayjs(draft.eatenAt));
    if (draft.note) setNote(draft.note);
  }

  function checkPendingUpload() {
    const pending = getPendingUploadNative();
    if (pending && pending.image_path) {
      // Only adopt if different from current draft
      const draft = loadDraftRaw();
      if (!draft || draft.image_path !== pending.image_path) {
        adoptNativePhoto(pending.image_path, pending.image_url);
        clearPendingUploadNative();
      }
    }
  }

  async function adoptNativePhoto(image_path: string, image_url: string) {
    setPreviewUrl(image_url);
    setServerImagePath(image_path);
    setServerImageUrl(image_url);
    setSelectedFile(null);
    setRecognized(false);
    setRecognizeResult(null);
    setEditableItems([]);
    setManualMode(false);

    saveDraft({ image_path, image_url, result: null, items: [], updatedAt: Date.now() });

    // Auto-recognize
    setRecognizing(true);
    try {
      const result = await recognizeByPath(image_path);
      setRecognizeResult(result);
      setServerImagePath(result.image_path || image_path);
      setServerImageUrl(image_url);
      if (result.result?.items) {
        const items: EditableItem[] = result.result.items.map((vi) => ({
          _key: nextKey(),
          name: vi.name,
          category: vi.category,
          portion: vi.portion,
          tags: vi.tags,
          confidence: vi.confidence,
          source: 'ai' as const,
          kcal: vi.kcal ?? undefined,
          kcal_source: vi.kcal_source ?? undefined,
        }));
        setEditableItems(items);
        saveDraft({ result, items, image_path: result.image_path || image_path, image_url });
      } else {
        saveDraft({ result, items: [], image_path: result.image_path || image_path, image_url });
      }
      if (result.result?.meal_type_guess) {
        setMealType(result.result.meal_type_guess);
      }
      setRecognized(true);
      setManualMode(false);
    } catch {
      /* error shown by interceptor */
    } finally {
      setRecognizing(false);
    }
  }

  function handleFileSelect(file: File) {
    setSelectedFile(file);
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    setRecognized(false);
    setRecognizeResult(null);
    setEditableItems([]);
    setManualMode(false);
    setServerImagePath('');
    setServerImageUrl('');
    clearDraft();
    setDraftAlert(false);
  }

  // Sync draft on state changes
  useEffect(() => {
    if (serverImagePath || editableItems.length > 0) {
      scheduleDraftSave({
        image_path: serverImagePath,
        image_url: serverImageUrl,
        result: recognizeResult,
        items: editableItems,
        mealType,
        eatenAt: eatenAt.toISOString(),
        note,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverImagePath, serverImageUrl, recognizeResult, editableItems, mealType, eatenAt, note]);

  async function handleRecognize() {
    if (!selectedFile) {
      message.warning('请先选择图片');
      return;
    }
    setRecognizing(true);
    try {
      const result = await recognizeMeal(selectedFile);
      setRecognizeResult(result);
      setServerImagePath(result.image_path);
      setServerImageUrl(`/uploads/${result.image_path}`);
      if (result.result?.items) {
        const items: EditableItem[] = result.result.items.map((vi) => ({
          _key: nextKey(),
          name: vi.name,
          category: vi.category,
          portion: vi.portion,
          tags: vi.tags,
          confidence: vi.confidence,
          source: 'ai' as const,
          kcal: vi.kcal ?? undefined,
          kcal_source: vi.kcal_source ?? undefined,
        }));
        setEditableItems(items);
        saveDraft({ result, items, image_path: result.image_path, image_url: `/uploads/${result.image_path}` });
      } else {
        setEditableItems([]);
        saveDraft({ result, items: [], image_path: result.image_path, image_url: `/uploads/${result.image_path}` });
      }
      if (result.result?.meal_type_guess) {
        setMealType(result.result.meal_type_guess);
      }
      setRecognized(true);
      setManualMode(false);
    } finally {
      setRecognizing(false);
    }
  }

  async function handleManualMode() {
    setManualMode(true);
    setRecognized(false);
    setRecognizeResult(null);
    if (editableItems.length === 0) {
      // keep any barcode items already added
    }
    if (selectedFile) {
      try {
        const res = await uploadOnly(selectedFile);
        setServerImagePath(res.image_path);
        setServerImageUrl(res.image_url);
        saveDraft({ image_path: res.image_path, image_url: res.image_url });
      } catch {
        /* 图片上传失败不阻塞 */
      }
    }
  }

  function handleBarcodeItem(item: EditableItem) {
    setEditableItems((prev) => [...prev, item]);
    // Enter editor mode if not already
    if (!manualMode && !recognized) {
      setManualMode(true);
    }
  }

  /** 扫码命中但数据源无图时，用户拍照补图 → 作为本餐次的图片保存 */
  function handleBarcodePhoto(imageUrl: string) {
    setPreviewUrl(imageUrl);
    const p = imageUrl.startsWith('/uploads/') ? imageUrl.slice('/uploads/'.length) : '';
    if (p) setServerImagePath(p);
    setServerImageUrl(imageUrl);
  }

  async function handleSave() {
    if (editableItems.length === 0) {
      message.warning('至少需要添加一条菜品记录');
      return;
    }
    const emptyName = editableItems.find((i) => !i.name.trim());
    if (emptyName) {
      message.warning('菜品名称不能为空');
      return;
    }
    setSaving(true);
    try {
      const allBarcode = editableItems.every((i) => i.source === 'barcode');
      const mealSource = allBarcode && !recognizeResult ? 'barcode' : (recognizeResult ? 'photo' : 'manual');
      void mealSource;

      await createMeal({
        eaten_at: eatenAt.format('YYYY-MM-DDTHH:mm:ss'),
        meal_type: mealType,
        image_path: serverImagePath || undefined,
        note: note || undefined,
        ai_model: recognizeResult?.model ?? undefined,
        ai_raw_json: recognizeResult?.raw ?? undefined,
        ai_latency_ms: recognizeResult?.latency_ms ?? undefined,
        items: editableItems.map((item) => ({
          name: item.name.trim(),
          category: item.category,
          portion: item.portion,
          tags: item.tags,
          confidence: item.confidence,
          source: item.source,
          barcode: item.barcode,
          kcal: item.kcal ?? undefined,
          kcal_source: item.kcal_source ?? undefined,
        })),
      });
      clearDraft();
      if (native) clearPendingUploadNative();
      message.success('已保存这顿饭！');
      navigate('/timeline');
    } finally {
      setSaving(false);
    }
  }

  function handleDiscardDraft() {
    clearDraft();
    if (native) clearPendingUploadNative();
    setDraftAlert(false);
    setPreviewUrl('');
    setServerImagePath('');
    setServerImageUrl('');
    setRecognizeResult(null);
    setRecognized(false);
    setEditableItems([]);
    setManualMode(false);
    setMealType('早餐');
    setEatenAt(dayjs());
    setNote('');
  }

  const showEditor = recognized || manualMode || editableItems.length > 0;
  const hasFallback = recognizeResult?.fallback || !recognizeResult?.result;

  return (
    <div>
      <div className="page-title">记录一餐</div>

      {/* Draft restored alert */}
      {draftAlert && (
        <Alert
          type="info"
          showIcon
          message="已恢复上次未保存的记录草稿"
          action={
            <Button size="small" danger onClick={handleDiscardDraft}>
              放弃草稿
            </Button>
          }
          closable
          onClose={() => setDraftAlert(false)}
          style={{ marginBottom: 12 }}
        />
      )}

      <div style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fit, minmax(${isMobile ? 280 : 360}px, 1fr))`,
        gap: 20,
      }}>
        {/* 左侧：图片上传 */}
        <div className="upload-section">
          {/* Native app: show camera/album buttons instead of dragger */}
          {native ? (
            <div
              style={{
                border: `1px dashed ${token.colorBorder}`,
                borderRadius: 10,
                minHeight: isMobile ? 160 : 200,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 12,
                background: token.colorFillAlter,
                padding: 16,
              }}
            >
              {previewUrl ? (
                <div style={{ width: '100%', textAlign: 'center' }}>
                  <Image
                    src={previewUrl}
                    alt="预览"
                    preview={false}
                    style={{
                      maxHeight: 220,
                      maxWidth: '100%',
                      objectFit: 'contain',
                      borderRadius: 8,
                    }}
                  />
                </div>
              ) : (
                <div style={{ color: token.colorTextTertiary, textAlign: 'center' }}>
                  <div style={{ fontSize: 40, marginBottom: 8 }}>📷</div>
                  <div style={{ fontSize: 14 }}>选择拍照或从相册选图</div>
                </div>
              )}
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
                <Button
                  icon={<CameraOutlined />}
                  onClick={nativeTakePhoto}
                  type="primary"
                >
                  拍照
                </Button>
                <Button
                  icon={<PictureOutlined />}
                  onClick={nativePickPhoto}
                >
                  相册
                </Button>
              </div>
            </div>
          ) : (
            <Dragger
              accept="image/*"
              multiple={false}
              showUploadList={false}
              fileList={fileList}
              beforeUpload={(file) => {
                handleFileSelect(file as unknown as File);
                return false;
              }}
              onChange={({ fileList: fl }) => setFileList(fl.slice(-1))}
              style={{ borderRadius: 10, minHeight: isMobile ? 160 : undefined }}
            >
              {previewUrl ? (
                <div style={{ padding: 8 }}>
                  <Image
                    src={previewUrl}
                    alt="预览"
                    preview={false}
                    style={{
                      maxHeight: 220,
                      maxWidth: '100%',
                      objectFit: 'contain',
                      borderRadius: 8,
                    }}
                  />
                </div>
              ) : (
                <div style={{ padding: isMobile ? 16 : 24 }}>
                  <p className="ant-upload-drag-icon">
                    <InboxOutlined style={{ fontSize: 40, color: token.colorPrimary }} />
                  </p>
                  <p style={{ fontSize: 15 }}>点击或拖拽图片到此区域</p>
                  <p style={{ color: token.colorTextTertiary, fontSize: 12 }}>
                    支持 JPG / PNG / HEIC 等常见格式
                  </p>
                </div>
              )}
            </Dragger>
          )}

          {/* 服务器端图片预览（识别后） */}
          {serverImageUrl && !native && (
            <div style={{ marginTop: 12, textAlign: 'center' }}>
              <Image
                src={serverImageUrl}
                alt="已上传"
                width={120}
                style={{ borderRadius: 6, objectFit: 'cover' }}
              />
              <div style={{ fontSize: 11, color: token.colorTextTertiary, marginTop: 4 }}>
                已保存到服务器
              </div>
            </div>
          )}

          {!native && (
            <div style={{ marginTop: 16, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={handleRecognize}
                loading={recognizing}
                disabled={!selectedFile}
                style={{ flex: 1 }}
                block={isMobile}
              >
                AI 识别
              </Button>
              <Button
                icon={<EditOutlined />}
                onClick={handleManualMode}
                disabled={recognizing}
                style={{ flex: 1 }}
                block={isMobile}
              >
                手动填写
              </Button>
            </div>
          )}

          {native && (
            <div style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <Button
                icon={<EditOutlined />}
                onClick={handleManualMode}
                disabled={recognizing}
                style={{ flex: 1 }}
                block={isMobile}
              >
                手动填写
              </Button>
            </div>
          )}

          {/* 扫码添加按钮 */}
          <div style={{ marginTop: 10 }}>
            <BarcodeScanner
              onItem={handleBarcodeItem}
              onPhoto={handleBarcodePhoto}
              allTags={allTags}
              categories={meta?.categories ?? []}
            />
          </div>

          {recognizing && (
            <div style={{ textAlign: 'center', marginTop: 12, color: token.colorTextSecondary }}>
              <Spin size="small" /> 正在识别…
            </div>
          )}
          {recognizeResult && !recognizing && (
            <div style={{
              marginTop: 12,
              fontSize: 12,
              color: token.colorTextTertiary,
              background: token.colorFillAlter,
              borderRadius: 6,
              padding: '6px 10px',
              lineHeight: 1.6,
            }}>
              识别 {recognizeResult.result?.items?.length ?? 0} 项
              {editableItems.some((i) => i.kcal != null && (i.kcal ?? 0) > 0)
                ? ` · 估算 ≈ ${editableItems.reduce((a, i) => a + (i.kcal ?? 0), 0)} kcal`
                : ''}
              {' · '}模型 {recognizeResult.model ?? '—'} · 耗时 {recognizeResult.latency_ms ?? '—'} ms
            </div>
          )}
        </div>

        {/* 右侧：表单区域 */}
        <div>
          {recognizeResult?.warnings?.map((w, i) => (
            <Alert key={i} type="warning" message={w} showIcon style={{ marginBottom: 10 }} />
          ))}

          {recognized && hasFallback && (
            <Alert
              type="warning"
              showIcon
              message="AI 识别失败，已切换手动填写模式"
              description="请手动添加菜品信息"
              style={{ marginBottom: 12 }}
            />
          )}

          {showEditor && (
            <>
              {recognizeResult?.result?.overall_note && (
                <div className="ai-note-block">
                  <strong>AI 的说明：</strong>
                  {recognizeResult.result.overall_note}
                  {recognizeResult.result.uncertainty && (
                    <>
                      <br />
                      <span style={{ color: token.colorPrimary }}>
                        不确定之处：{recognizeResult.result.uncertainty}
                      </span>
                    </>
                  )}
                </div>
              )}

              <div className="content-card" style={{ padding: 16 }}>
                <div style={{ marginBottom: 14 }}>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                    用餐时间
                  </Text>
                  <DatePicker
                    showTime
                    value={eatenAt}
                    onChange={(d) => d && setEatenAt(d)}
                    style={{ width: '100%' }}
                    format="YYYY-MM-DD HH:mm"
                  />
                </div>

                <div style={{ marginBottom: 14 }}>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                    餐次类型
                  </Text>
                  <Segmented
                    options={meta?.meal_types ?? ['早餐', '午餐', '晚餐', '加餐', '饮品']}
                    value={mealType}
                    onChange={(v) => setMealType(v as string)}
                    block
                  />
                </div>

                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                    备注（可选）
                  </Text>
                  <TextArea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={2}
                    placeholder="记录一下心情或场景…"
                  />
                </div>
              </div>

              <Divider style={{ margin: '12px 0' }} />

              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ display: 'block', marginBottom: 10 }}>
                  菜品明细
                </Text>
                <MealItemsEditor
                  items={editableItems}
                  onChange={setEditableItems}
                  tags={allTags}
                  categories={meta?.categories ?? []}
                  portions={meta?.portions ?? []}
                />
              </div>

              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={handleSave}
                loading={saving}
                size="large"
                block
              >
                保存这顿饭
              </Button>
            </>
          )}

          {!showEditor && !recognizing && (
            <div
              style={{
                textAlign: 'center',
                padding: '60px 20px',
                color: token.colorTextTertiary,
                fontSize: 14,
              }}
            >
              {native
                ? '点击「拍照」或「相册」选择图片，App 将自动识别'
                : '上传图片后点击「AI 识别」，或选择「手动填写」，或「扫码添加包装食品」'}
            </div>
          )}
        </div>
      </div>

      <Disclaimer text={meta?.disclaimer} />
    </div>
  );
}

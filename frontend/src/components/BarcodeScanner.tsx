import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Spin, Space, Typography, Card, Tag, message } from 'antd';
import { ScanOutlined, CloseOutlined, CameraOutlined } from '@ant-design/icons';
import { lookupBarcode, upsertBarcode, getRecentBarcodes } from '../api/barcode';
import type { BarcodeProduct, BarcodeResult } from '../api/barcode';
import { uploadOnly } from '../api/endpoints';
import { isNativeApp, scanBarcodeNative, nativeTakePhoto, getPendingUploadNative, clearPendingUploadNative } from '../native/bridge';
import type { EditableItem } from '../api/types';
import { nextKey } from './MealItemsEditor';

const { Text } = Typography;

interface Props {
  onItem: (item: EditableItem) => void;
  /** 数据源没有商品图、用户拍照补图后回传（本地 /uploads 或 blob URL） */
  onPhoto?: (imageUrl: string) => void;
  allTags?: { code: string; name_zh: string }[];
  categories?: string[];
}

function ProductCard({ product }: { product: BarcodeProduct }) {
  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', gap: 12 }}>
        {product.image_url && (
          <img src={product.image_url} alt={product.name} width={60} height={60}
            style={{ objectFit: 'cover', borderRadius: 6, flexShrink: 0 }} />
        )}
        <div>
          <div style={{ fontWeight: 600 }}>{product.name}</div>
          {product.brand && <div style={{ fontSize: 12, color: 'var(--dd-text-secondary)' }}>{product.brand}</div>}
          <Space wrap style={{ marginTop: 4 }}>
            <Tag>{product.category}</Tag>
            {product.tags.map((t) => <Tag key={t} color="lime">{t}</Tag>)}
          </Space>
          {product.nutriments && Object.keys(product.nutriments).length > 0 && (
            <div style={{ fontSize: 11, color: 'var(--dd-text-tertiary)', marginTop: 4 }}>
              含营养数据
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function BarcodeScanner({ onItem, onPhoto, allTags = [], categories = [] }: Props) {
  const [open, setOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [manualCode, setManualCode] = useState('');
  const [result, setResult] = useState<BarcodeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useState<BarcodeProduct[]>([]);
  const [recentLoading, setRecentLoading] = useState(false);
  const [newItemForm, setNewItemForm] = useState<{ name: string; category: string } | null>(null);
  // 扫码命中但数据源没有图片时，用户拍照补充的照片（服务端 URL）
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [photoUploading, setPhotoUploading] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const readerRef = useRef<any>(null);

  const native = isNativeApp();

  useEffect(() => {
    if (open) {
      loadRecent();
    } else {
      stopCamera();
      setResult(null);
      setManualCode('');
      setNewItemForm(null);
      setPhotoUrl(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 原生拍照回传：写入待选照片（供拍照补图用）
  useEffect(() => {
    function handlePhoto() {
      const pending = getPendingUploadNative();
      if (pending?.image_url) {
        setPhotoUrl(pending.image_url);
        onPhoto?.(pending.image_url);
        clearPendingUploadNative();
        message.success('已拍照，将作为该食品的图片');
      }
    }
    window.addEventListener('dd:photo', handlePhoto);
    return () => window.removeEventListener('dd:photo', handlePhoto);
  }, [onPhoto]);

  async function loadRecent() {
    setRecentLoading(true);
    try {
      const r = await getRecentBarcodes(10);
      setRecent(r);
    } catch {
      /* ignore */
    } finally {
      setRecentLoading(false);
    }
  }

  function stopCamera() {
    try {
      if (readerRef.current) {
        readerRef.current.reset();
        readerRef.current = null;
      }
    } catch {/* ignore */}
    setScanning(false);
  }

  async function startBrowserScan() {
    setScanning(true);
    try {
      const { BrowserMultiFormatReader } = await import('@zxing/browser');
      const reader = new BrowserMultiFormatReader();
      readerRef.current = reader;

      const devices = await BrowserMultiFormatReader.listVideoInputDevices();
      // prefer rear camera
      const device = devices.find((d) =>
        /back|rear|environment/i.test(d.label)
      ) ?? devices[0];

      if (!device) {
        message.warning('未检测到摄像头，请手动输入条形码');
        setScanning(false);
        return;
      }

      await reader.decodeFromVideoDevice(
        device.deviceId,
        videoRef.current!,
        (res, _err, controls) => {
          if (res) {
            controls.stop();
            readerRef.current = null;
            setScanning(false);
            handleCode(res.getText());
          }
        }
      );
    } catch {
      setScanning(false);
      message.warning('摄像头无法启动，请使用 HTTPS 或手动输入条形码');
    }
  }

  async function handleNativeScan() {
    setLoading(true);
    try {
      const code = await scanBarcodeNative();
      if (code) await handleCode(code);
    } finally {
      setLoading(false);
    }
  }

  async function handleCode(code: string) {
    setLoading(true);
    setResult(null);
    try {
      const r = await lookupBarcode(code);
      setResult(r);
      if (r.found && r.suggested_item) {
        // product found - auto-add
      } else if (!r.found) {
        setNewItemForm({ name: '', category: '其他' });
      }
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }

  function handleAddItem() {
    if (!result?.suggested_item) return;
    const si = result.suggested_item;
    onItem({
      _key: nextKey(),
      name: si.name,
      category: si.category,
      portion: si.portion,
      tags: si.tags,
      source: 'barcode',
      barcode: si.barcode,
    });
    message.success(`已添加：${si.name}`);
    setOpen(false);
  }

  async function handleSaveNew() {
    if (!newItemForm || !manualCode.trim() || !newItemForm.name.trim()) {
      message.warning('请输入商品名称');
      return;
    }
    setLoading(true);
    try {
      const r = await upsertBarcode(manualCode.trim(), {
        name: newItemForm.name.trim(),
        category: newItemForm.category || '其他',
      });
      setResult(r);
      setNewItemForm(null);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }

  function addFromRecent(p: BarcodeProduct) {
    onItem({
      _key: nextKey(),
      name: p.name,
      category: p.category,
      portion: '中',
      tags: p.tags,
      source: 'barcode',
      barcode: p.barcode,
    });
    message.success(`已添加：${p.name}`);
    setOpen(false);
  }

  void allTags;
  void categories;

  return (
    <>
      <Button
        icon={<ScanOutlined />}
        onClick={() => setOpen(true)}
      >
        扫码添加包装食品
      </Button>

      <Modal
        open={open}
        title="扫码添加包装食品"
        onCancel={() => setOpen(false)}
        footer={null}
        width={520}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {/* Scan buttons */}
          <Space wrap>
            {native ? (
              <Button
                icon={<ScanOutlined />}
                type="primary"
                loading={loading}
                onClick={handleNativeScan}
              >
                使用 App 扫码
              </Button>
            ) : (
              <Button
                icon={<ScanOutlined />}
                type="primary"
                onClick={startBrowserScan}
                loading={scanning}
              >
                开启摄像头扫码
              </Button>
            )}
            {scanning && (
              <Button icon={<CloseOutlined />} onClick={stopCamera}>
                停止
              </Button>
            )}
          </Space>

          {/* Browser camera preview */}
          {!native && (
            <div>
              <video
                ref={videoRef}
                style={{
                  width: '100%',
                  maxHeight: 240,
                  display: scanning ? 'block' : 'none',
                  borderRadius: 8,
                  background: '#000',
                }}
                playsInline
                muted
              />
              {!scanning && (
                <Alert
                  type="info"
                  showIcon
                  message="摄像头扫码需要 HTTPS 或 localhost 环境。若无法启动，请使用下方手动输入。"
                  style={{ fontSize: 12 }}
                />
              )}
            </div>
          )}

          {/* Manual input */}
          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="手动输入条形码（EAN-13 等）"
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
              onPressEnter={() => manualCode && handleCode(manualCode)}
            />
            <Button
              type="primary"
              loading={loading}
              onClick={() => manualCode && handleCode(manualCode)}
            >
              查询
            </Button>
          </Space.Compact>

          {/* Result */}
          {loading && <div style={{ textAlign: 'center' }}><Spin /></div>}

          {result?.found && result.product && (
            <div>
              <ProductCard product={result.product} />
              {result.source && (
                <div style={{ marginBottom: 8 }}>
                  <Tag color="blue">数据来源：{result.source}</Tag>
                </div>
              )}

              {/* 数据源没有提供图片：提示用户拍照补充 */}
              {!result.product.image_url && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 8 }}
                  message="该食品数据源没有提供图片"
                  description={
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <span style={{ fontSize: 12 }}>
                        建议拍一张实物照片，时间线与餐单中会显示你的实拍图，而不是占位图。
                      </span>
                      {photoUrl ? (
                        <Space size={8}>
                          <img
                            src={photoUrl}
                            alt="已拍照"
                            style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6 }}
                          />
                          <Text type="success" style={{ fontSize: 12 }}>已拍照，保存餐食后即使用这张图</Text>
                        </Space>
                      ) : (
                        <Button
                          size="small"
                          icon={<CameraOutlined />}
                          loading={photoUploading}
                          onClick={() => {
                            if (native) {
                              // 原生端：拍照后由 dd:photo 事件回传（照片已上传到服务端）
                              nativeTakePhoto();
                              return;
                            }
                            const input = document.createElement('input');
                            input.type = 'file';
                            input.accept = 'image/*';
                            input.capture = 'environment';
                            input.onchange = async () => {
                              const f = input.files?.[0];
                              if (!f) return;
                              setPhotoUploading(true);
                              try {
                                const r = await uploadOnly(f);
                                const url = r.image_url || `/uploads/${r.image_path}`;
                                setPhotoUrl(url);
                                onPhoto?.(url);
                                message.success('已上传照片，将作为该食品的图片');
                              } catch {
                                /* error shown by interceptor */
                              } finally {
                                setPhotoUploading(false);
                              }
                            };
                            input.click();
                          }}
                        >
                          拍照添加图片
                        </Button>
                      )}
                    </Space>
                  }
                />
              )}

              <Button type="primary" block onClick={handleAddItem}>
                添加到餐食记录
              </Button>
            </div>
          )}

          {result && !result.found && newItemForm && (
            <div>
              <Alert
                type="warning"
                showIcon
                message={result.message || '未找到此商品，请手动录入商品名称'}
                description="你也可以补充商品信息，方便下次扫码直接识别。"
                style={{ marginBottom: 8 }}
              />
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  placeholder="商品名称（必填）"
                  value={newItemForm.name}
                  onChange={(e) => setNewItemForm({ ...newItemForm, name: e.target.value })}
                />
                <Button type="primary" block loading={loading} onClick={handleSaveNew}>
                  保存并添加
                </Button>
              </Space>
            </div>
          )}

          {/* Recent */}
          {recent.length > 0 && (
            <div>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                最近扫过
              </Text>
              {recentLoading ? <Spin size="small" /> : (
                <Space wrap>
                  {recent.slice(0, 8).map((p) => (
                    <Button
                      key={p.barcode}
                      size="small"
                      onClick={() => addFromRecent(p)}
                    >
                      {p.name}
                    </Button>
                  ))}
                </Space>
              )}
            </div>
          )}
        </Space>
      </Modal>
    </>
  );
}

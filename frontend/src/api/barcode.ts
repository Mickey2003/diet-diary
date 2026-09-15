import client from './client';

export interface BarcodeProduct {
  barcode: string;
  name: string;
  brand: string | null;
  category: string;
  tags: string[];
  image_url: string | null;
  nutriments: Record<string, unknown> | null;
}

export interface BarcodeResult {
  found: boolean;
  source?: string | null;
  sources_found?: string[];
  message?: string;
  product?: BarcodeProduct;
  suggested_item?: {
    name: string;
    category: string;
    portion: string;
    tags: string[];
    source: string;
    barcode: string;
  };
}

export interface BarcodeManualIn {
  name: string;
  brand?: string;
  category?: string;
  tags?: string[];
  nutriments?: Record<string, unknown>;
}

export const lookupBarcode = (code: string) =>
  client.get<BarcodeResult>(`/api/barcode/${code}`).then((r) => r.data);

export const upsertBarcode = (code: string, payload: BarcodeManualIn) =>
  client.put<BarcodeResult>(`/api/barcode/${code}`, payload).then((r) => r.data);

export const getRecentBarcodes = (limit = 30) =>
  client.get<BarcodeProduct[]>('/api/barcode/recent', { params: { limit } }).then((r) => r.data);

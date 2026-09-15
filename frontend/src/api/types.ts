/** 所有与后端 API 对应的 TypeScript 类型定义。 */

export type Category = '主食' | '蛋白质' | '蔬菜' | '水果' | '饮品' | '甜点零食' | '汤' | '其他';
export type MealType = '早餐' | '午餐' | '晚餐' | '加餐' | '饮品';
export type Portion = '少' | '中' | '多';
export type ItemSource = 'ai' | 'ai_edited' | 'user' | 'barcode';
export type KcalSource = 'ai' | 'table' | 'category' | 'user' | 'barcode' | null;

// ---------- /api/meta ----------
export interface MetaOut {
  categories: string[];
  meal_types: string[];
  portions: string[];
  disclaimer: string;
}

// ---------- /api/tags ----------
export interface TagOut {
  code: string;
  name_zh: string;
  group: string;
  is_watch: boolean;
  description?: string;
}

// ---------- AI 识别 ----------
export interface VisionItem {
  name: string;
  category: Category;
  portion: Portion;
  tags: string[];   // tag codes
  confidence: number;
  kcal?: number | null;
  kcal_source?: KcalSource;
}

export interface VisionResult {
  items: VisionItem[];
  meal_type_guess?: MealType;
  overall_note: string;
  uncertainty: string;
}

export interface RecognizeOut {
  image_path: string;
  result?: VisionResult;
  fallback: boolean;
  warnings: string[];
  model?: string;
  latency_ms?: number;
  raw?: string;
  disclaimer: string;
}

// ---------- 餐食记录 ----------
export interface MealItemIn {
  name: string;
  category: string;
  portion: string;
  tags: string[];
  confidence?: number;
  source: ItemSource;
  barcode?: string;
  kcal?: number | null;
  kcal_source?: KcalSource;
}

export interface MealItemOut {
  id: number;
  name: string;
  category: string;
  portion: string;
  confidence?: number;
  source: string;
  barcode?: string;
  tags: TagOut[];
  kcal?: number | null;
  kcal_source?: KcalSource;
}

export interface MealOut {
  id: number;
  eaten_at: string;
  meal_type: string;
  image_path?: string;
  image_url?: string;
  thumb_url?: string;
  note?: string;
  ai_model?: string;
  ai_raw_json?: string;
  ai_latency_ms?: number;
  confirmed: boolean;
  created_at: string;
  updated_at: string;
  items: MealItemOut[];
  kcal_total?: number | null;
}

export interface MealPage {
  total: number;
  page: number;
  page_size: number;
  items: MealOut[];
}

export interface MealCreate {
  eaten_at: string;
  meal_type: string;
  image_path?: string;
  note?: string;
  ai_model?: string;
  ai_raw_json?: string;
  ai_latency_ms?: number;
  items: MealItemIn[];
}

export interface MealUpdate {
  eaten_at?: string;
  meal_type?: string;
  note?: string;
  items?: MealItemIn[];
}

// ---------- 统计 ----------
export interface CategoryShare {
  category: string;
  count: number;
  ratio: number;
  prev_ratio: number;
  delta_ratio: number;
}

export interface WatchTagStat {
  code: string;
  name: string;
  count: number;
  prev_count: number;
  delta_vs_prev: number;
}

export interface StructureTagStat {
  code: string;
  name: string;
  count: number;
}

export interface DailyRecord {
  date: string;
  weekday: string;
  meals: number;
  kcal?: number | null;
  [key: string]: number | string | null | undefined;
}

export interface StatsOut {
  period: {
    type: string;
    start: string;
    end: string;
    label: string;
    prev_start: string;
    prev_end: string;
  };
  days_total: number;
  days_with_records: number;
  missing_days: string[];
  meal_count: number;
  item_count: number;
  avg_meals_per_day: number;
  meal_type_counts: { meal_type: string; count: number }[];
  category_share: CategoryShare[];
  watch_tags: WatchTagStat[];
  structure_tags: StructureTagStat[];
  top_items: { name: string; count: number }[];
  daily: DailyRecord[];
  late_night_meals: number;
  item_sources: { ai: number; ai_edited: number; user: number };
  prev: {
    meal_count: number;
    item_count: number;
    days_with_records: number;
    avg_meals_per_day: number;
    kcal_total?: number | null;
    kcal_avg_per_day?: number | null;
  };
  kcal_total?: number | null;
  kcal_avg_per_day?: number | null;
  kcal_by_meal_type?: { meal_type: string; kcal: number }[];
  kcal_note?: string;
}

// ---------- 查询 ----------
export interface QueryPlan {
  metric: string;
  time_range: {
    preset: string;
    start?: string;
    end?: string;
  };
  filters: {
    tags: string[];
    categories: string[];
    meal_types: string[];
    name_contains?: string;
    hour_from?: number;
    hour_to?: number;
  };
  group_by: string;
  limit: number;
  unsupported: boolean;
  unsupported_reason?: string;
}

export interface QueryOut {
  id: number;
  question: string;
  status: string;
  plan?: QueryPlan;
  sql?: string;
  rows: Record<string, unknown>[];
  answer: string;
  warnings: string[];
  model?: string;
  disclaimer: string;
}

export interface QueryHistoryItem {
  id: number;
  question: string;
  status: string;
  answer: string;
  created_at: string;
  model?: string;
}

// ---------- 报告 ----------
export interface ReportOut {
  id: number;
  period_type: string;
  period_start: string;
  period_end: string;
  facts: Record<string, unknown>;
  summary_md: string;
  unverified_numbers: string[];
  model?: string;
  created_at: string;
}

// ---------- 设置 ----------
export interface PresetInfo {
  label: string;
  base_url: string;
  text_model: string;
  fast_model?: string;
  vision_model: string;
}

export interface SettingsOut {
  provider: string;
  base_url: string;
  text_model: string;
  fast_model?: string;
  vision_model: string;
  /** 旧的「OpenAI 兼容配图模型」（走主 API 的 images.generate），v0.8.5 前使用 */
  image_model: string;
  api_key_masked: string;
  has_api_key: boolean;
  source: string;
  presets: Record<string, PresetInfo>;
  can_edit: boolean;
  vision_async: boolean;
  net_proxy_mode: string;
  net_proxy_url: string;
  barcode_sources: string;
  dish_ai_images: boolean;
  barcode_source_options: Record<string, string>;
  // ---- 生图专用 API（与文本 / 识图模型解耦，v0.8.6） ----
  image_provider: string;
  image_base_url: string;
  /** 生图专用模型 id（独立于上面的 image_model） */
  image_model_id: string;
  image_key_masked: string;
  has_image_key: boolean;
  image_size: string;
  image_providers: ImageProviderInfo[];
  image_ready: boolean;
  image_emoji_fallback: boolean;
}

/** 生图后端预设（一个提供商下可挂多个模型，各自有尺寸清单） */
export interface ImageProviderInfo {
  id: string;
  label: string;
  base_url: string;
  protocol: 'senseaudio' | 'openai' | string;
  models: ImageModelInfo[];
}

export interface ImageModelInfo {
  id: string;
  label: string;
  sizes: string[];
}

export interface ConnectionTestOut {
  ok: boolean;
  message: string;
  latency_ms?: number;
  model?: string;
}

// ---------- 可编辑项（MealItemsEditor 内部状态） ----------
export interface EditableItem {
  _key: string;
  name: string;
  category: string;
  portion: string;
  tags: string[];
  confidence?: number;
  source: ItemSource;
  barcode?: string;
  kcal?: number | null;
  kcal_source?: KcalSource;
}

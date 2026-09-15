/** 健康档案与餐单 API 封装。 */
import client from './client';

// ---------- 人设预设 ----------
export interface PersonaInfo {
  label: string;
  description: string;
  default_activity_level: string;
  default_meal_times: Record<string, string>;
  typical_goals: string;
  typical_preferences_hint: string;
}

export interface PersonasOut {
  personas: Record<string, PersonaInfo>;
  disclaimer: string;
}

// ---------- 档案 ----------
export interface ProfileOut {
  user_id: number;
  persona?: string;
  gender?: string;
  birth_year?: number;
  height_cm?: number;
  weight_kg?: number;
  activity_level?: string;
  conditions?: string;
  medications?: string;
  allergies?: string;
  preferences?: string;
  tcm_constitution?: string;
  goals?: string;
  meal_times?: Record<string, string>;
  budget_level?: string;
  cooking_ability?: string;
  updated_at?: string;
  age?: number;
  bmi?: number;
  bmi_category?: string;
  estimated_daily_energy_kcal?: number;
  estimated_daily_energy_note?: string;
  cautions: string[];
  disclaimer: string;
}

export interface ProfileUpdate {
  persona?: string;
  gender?: string;
  birth_year?: number;
  height_cm?: number;
  weight_kg?: number;
  activity_level?: string;
  conditions?: string;
  medications?: string;
  allergies?: string;
  preferences?: string;
  tcm_constitution?: string;
  goals?: string;
  meal_times?: Record<string, string>;
  budget_level?: string;
  cooking_ability?: string;
  apply_preset_defaults?: boolean;
}

// ---------- 体质问卷 ----------
export interface QuizQuestion {
  id: string;
  text: string;
  constitution: string;
  options: { value: number; label: string }[];
}

export interface QuizOut {
  questions: QuizQuestion[];
  note: string;
  disclaimer: string;
}

export interface QuizResultOut {
  scores: Record<string, number>;
  suggested: string;
  note: string;
  disclaimer: string;
}

// ---------- 餐单 ----------
export interface PlanDish {
  name: string;
  category: string;
  portion: string;
  note?: string;
  image_url?: string;
  /** 200×150 缩略图（列表用，本地图才有） */
  thumb_url?: string;
  /** emoji 兜底：无 image_url 时渲染 */
  image_emoji?: string;
  /** Twemoji SVG 地址（跨端渲染统一） */
  image_emoji_url?: string;
  /** emoji 卡片背景渐变 */
  image_bg?: string;
}

export interface PlanMeal {
  meal_type: string;
  time: string;
  dishes: PlanDish[];
  tip: string;
}

export interface PlanDay {
  date: string;
  meals: PlanMeal[];
}

export interface PlanRationale {
  nutrition: string;
  tcm: string;
  swaps: string[];
}

export interface PlanDetail {
  title: string;
  days: PlanDay[];
  rationale: PlanRationale;
  shopping_list: string[];
}

export interface MealPlanOut {
  id: number;
  title: string;
  start_date: string;
  days: number;
  is_active: boolean;
  plan: PlanDetail;
  rationale?: string;
  cautions: string[];
  model?: string;
  created_at: string;
  updated_at: string;
  warnings: string[];
  disclaimer: string;
  /** 菜品配图统计：决定是否亮起「用 AI 生图替换 emoji 图」按钮 */
  image_stats?: { total: number; emoji: number; with_image: number };
  /** 批量替换接口的返回统计 */
  replace_result?: { total: number; remaining: number };
}

export interface PlanCreate {
  days: number;
  start_date?: string;
  focus?: string;
  regenerate_from?: number;
}

// ---------- API 函数 ----------
export const getPersonas = () =>
  client.get<PersonasOut>('/api/health/personas').then((r) => r.data);

export const getProfile = () =>
  client.get<ProfileOut>('/api/health/profile').then((r) => r.data);

export const updateProfile = (data: ProfileUpdate) =>
  client.put<ProfileOut>('/api/health/profile', data).then((r) => r.data);

export const getConstitutionQuiz = () =>
  client.get<QuizOut>('/api/health/constitution-quiz').then((r) => r.data);

export const submitConstitutionQuiz = (
  answers: { question_id: string; value: number }[],
  save = false,
) =>
  client
    .post<QuizResultOut>('/api/health/constitution-quiz', { answers, save })
    .then((r) => r.data);

export const createPlan = (data: PlanCreate) =>
  client.post<MealPlanOut>('/api/health/plans', data, { timeout: 240000 }).then((r) => r.data);

export const listPlans = () =>
  client.get<MealPlanOut[]>('/api/health/plans').then((r) => r.data);

export const getPlanGenerating = () =>
  client
    .get<{ generating: boolean; slot: boolean }>('/api/health/plans/generating')
    .then((r) => r.data);

export const getPlan = (id: number) =>
  client.get<MealPlanOut>(`/api/health/plans/${id}`).then((r) => r.data);

export const deletePlan = (id: number) =>
  client.delete(`/api/health/plans/${id}`).then((r) => r.data);

export const activatePlan = (id: number) =>
  client.post<MealPlanOut>(`/api/health/plans/${id}/activate`).then((r) => r.data);

export const updatePlanDays = (id: number, days: PlanDay[]) =>
  client
    .patch<MealPlanOut>(`/api/health/plans/${id}`, { days })
    .then((r) => r.data);

export const updatePlanSlot = (
  id: number,
  day_index: number,
  meal_index: number,
  instruction?: string,
) =>
  client
    .patch<MealPlanOut>(
      `/api/health/plans/${id}/slot`,
      { day_index, meal_index, instruction },
      { timeout: 120000 },
    )
    .then((r) => r.data);

export const applyPlanSwap = (
  id: number,
  swapInstruction: string,
) =>
  client
    .post<MealPlanOut>(
      `/api/health/plans/${id}/apply-swap`,
      { swap_instruction: swapInstruction },
      { timeout: 120000 },
    )
    .then((r) => r.data);

export const getTodayMeals = (id: number) =>
  client
    .get<{ date: string; meals: PlanMeal[] }>(`/api/health/plans/${id}/today`)
    .then((r) => r.data);

// ---------- 餐单历史版本（界面化回退） ----------
export interface PlanVersionItem {
  id: number;
  reason: string;
  title: string;
  days: number;
  dish_count: number;
  created_at: string;
}

export const listPlanVersions = (id: number) =>
  client.get<PlanVersionItem[]>(`/api/health/plans/${id}/versions`).then((r) => r.data);

export const restorePlanVersion = (id: number, versionId: number) =>
  client
    .post<MealPlanOut>(`/api/health/plans/${id}/versions/${versionId}/restore`)
    .then((r) => r.data);

// ---------- 批量把 emoji 图替换为 AI 生图（v0.8.6） ----------

/**
 * 把餐单里仍是 emoji 兜底的菜品，用 AI 生图批量替换。
 * 服务端会登记 busy("plan") 任务，重复触发返回 409（防重复点击）。
 * 图片较多时耗时较长，故给足超时。
 */
export const replaceEmojiImages = (id: number) =>
  client
    .post<MealPlanOut>(
      `/api/health/plans/${id}/replace-emoji-images`,
      {},
      { timeout: 300000 },
    )
    .then((r) => r.data);

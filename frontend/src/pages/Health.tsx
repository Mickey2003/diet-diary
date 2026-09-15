import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Divider,
  Drawer,
  Form,
  Grid,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Popover,
  Progress,
  Radio,
  Row,
  Col,
  Select,
  Segmented,
  Space,
  Skeleton,
  Spin,
  Tag,
  Tabs,
  TimePicker,
  Tooltip,
  Typography,
  theme as antdTheme,
} from 'antd';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import ErrorBoundary from '../components/ErrorBoundary';
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { useAppTheme } from '../theme/ThemeContext';
import { categoryColor } from '../utils/categoryColors';
import {
  getPersonas,
  getProfile,
  updateProfile,
  getConstitutionQuiz,
  submitConstitutionQuiz,
  createPlan,
  listPlans,
  deletePlan,
  activatePlan,
  updatePlanDays,
  updatePlanSlot,
  getTodayMeals,
  applyPlanSwap,
  listPlanVersions,
  restorePlanVersion,
  getPlanGenerating,
  replaceEmojiImages,
} from '../api/health';
import { getSettings } from '../api/endpoints';
import type {
  PersonaInfo,
  ProfileOut,
  QuizQuestion,
  QuizResultOut,
  MealPlanOut,
  PlanDay,
  PlanMeal,
  PlanDish,
  PlanVersionItem,
} from '../api/health';

const { Text, Title } = Typography;
const { TextArea } = Input;
const { useBreakpoint } = Grid;

// 9 体质 + 未知
const TCM_CONSTITUTIONS = [
  '平和质', '气虚质', '阳虚质', '阴虚质',
  '痰湿质', '湿热质', '血瘀质', '气郁质', '特禀质', '未知',
];

// 体质简介（参考）
const TCM_DESC: Record<string, string> = {
  平和质: '体质均衡，精力充沛，适应力强，是最理想的体质状态。',
  气虚质: '气力不足，容易疲倦、气短、多汗，体质偏弱。',
  阳虚质: '阳气不足，怕冷，手脚发凉，喜温热饮食。',
  阴虚质: '阴液亏虚，手脚心热，口干咽燥，睡眠不实。',
  痰湿质: '痰湿内盛，体型偏胖，腹部松软，身体沉重。',
  湿热质: '湿热蕴结，面部油腻，易生痤疮，口苦口臭。',
  血瘀质: '血行不畅，面色晦暗，皮肤易现瘀斑。',
  气郁质: '气机郁滞，情绪不稳，易烦躁焦虑，多愁善感。',
  特禀质: '先天禀赋不足或过敏体质，对花粉、食物等易过敏。',
};

// BMI 分类颜色
function bmiTagColor(cat?: string): string {
  if (!cat) return 'default';
  const map: Record<string, string> = {
    偏瘦: 'blue',
    正常: 'success',
    超重: 'warning',
    肥胖: 'error',
  };
  return map[cat] ?? 'default';
}

// 餐次颜色
const MEAL_TYPE_COLORS: Record<string, string> = {
  早餐: 'gold',
  午餐: 'green',
  晚餐: 'blue',
  加餐: 'cyan',
};

const SWAP_PRESETS = ['少油', '换成素的', '不要辣', '简单快手', '高蛋白'];

// ============================================================
// Tab 1 — 我的档案
// ============================================================
function ProfileTab() {
  const [profile, setProfile] = useState<ProfileOut | null>(null);
  const [personas, setPersonas] = useState<Record<string, PersonaInfo>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedPersona, setSelectedPersona] = useState<string | null>(null);
  const [showApplyPreset, setShowApplyPreset] = useState(false);

  // Form values
  const [gender, setGender] = useState<string>('');
  const [birthYear, setBirthYear] = useState<number | null>(null);
  const [heightCm, setHeightCm] = useState<number | null>(null);
  const [weightKg, setWeightKg] = useState<number | null>(null);
  const [activityLevel, setActivityLevel] = useState<string>('中');
  const [conditions, setConditions] = useState('');
  const [medications, setMedications] = useState('');
  const [allergies, setAllergies] = useState('');
  const [preferences, setPreferences] = useState('');
  const [goals, setGoals] = useState('');
  const [tcmConstitution, setTcmConstitution] = useState<string | undefined>();
  const [mealTimes, setMealTimes] = useState<Record<string, string>>({});
  const [budgetLevel, setBudgetLevel] = useState<string>('中');
  const [cookingAbility, setCookingAbility] = useState<string>('中');

  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      const [p, per] = await Promise.all([getProfile(), getPersonas()]);
      setProfile(p);
      setPersonas(per.personas);
      // populate form
      setGender(p.gender ?? '');
      setBirthYear(p.birth_year ?? null);
      setHeightCm(p.height_cm ?? null);
      setWeightKg(p.weight_kg ?? null);
      setActivityLevel(p.activity_level ?? '中');
      setConditions(p.conditions ?? '');
      setMedications(p.medications ?? '');
      setAllergies(p.allergies ?? '');
      setPreferences(p.preferences ?? '');
      setGoals(p.goals ?? '');
      setTcmConstitution(p.tcm_constitution);
      setMealTimes(p.meal_times ?? {});
      setBudgetLevel(p.budget_level ?? '中');
      setCookingAbility(p.cooking_ability ?? '中');
      if (p.persona) {
        setSelectedPersona(p.persona);
      }
    } catch {
      /* 错误已由 interceptor 显示 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await updateProfile({
        gender: gender || undefined,
        birth_year: birthYear ?? undefined,
        height_cm: heightCm ?? undefined,
        weight_kg: weightKg ?? undefined,
        activity_level: activityLevel || undefined,
        conditions: conditions || undefined,
        medications: medications || undefined,
        allergies: allergies || undefined,
        preferences: preferences || undefined,
        goals: goals || undefined,
        tcm_constitution: tcmConstitution,
        meal_times: Object.keys(mealTimes).length > 0 ? mealTimes : undefined,
        budget_level: budgetLevel || undefined,
        cooking_ability: cookingAbility || undefined,
      });
      setProfile(updated);
      message.success('档案已保存');
    } catch {
      /* 错误已显示 */
    } finally {
      setSaving(false);
    }
  }

  async function handleApplyPreset(personaKey: string) {
    setSaving(true);
    try {
      const updated = await updateProfile({
        persona: personaKey,
        apply_preset_defaults: true,
      });
      setProfile(updated);
      setActivityLevel(updated.activity_level ?? '中');
      setMealTimes(updated.meal_times ?? {});
      setShowApplyPreset(false);
      message.success('已应用预设默认值');
    } catch {
      /* 错误已显示 */
    } finally {
      setSaving(false);
    }
  }

  async function handleSelectPersona(key: string) {
    setSelectedPersona(key);
    setShowApplyPreset(true);
    try {
      await updateProfile({ persona: key });
    } catch {
      /* 错误已显示 */
    }
  }

  if (loading) {
    return (
      <div>
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
        <Skeleton active paragraph={{ rows: 3 }} />
      </div>
    );
  }

  return (
    <div>
      {/* 人设预设卡片 */}
      <div style={{ marginBottom: 24 }}>
        <Text type="secondary" style={{ fontSize: 13, marginBottom: 10, display: 'block' }}>
          选择最符合你情况的人群预设（可选）
        </Text>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {Object.entries(personas).map(([key, info]) => (
            <Card
              key={key}
              size="small"
              hoverable
              onClick={() => handleSelectPersona(key)}
              style={{
                width: isMobile ? 'calc(50% - 5px)' : 160,
                cursor: 'pointer',
                border: selectedPersona === key
                  ? `2px solid ${token.colorPrimary}`
                  : `1px solid ${token.colorBorderSecondary}`,
                background: selectedPersona === key ? token.colorPrimaryBg : token.colorBgContainer,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                {selectedPersona === key && (
                  <CheckCircleOutlined style={{ color: token.colorPrimary, marginRight: 4 }} />
                )}
                {info.label}
              </div>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {info.description}
              </Text>
            </Card>
          ))}
        </div>

        {showApplyPreset && selectedPersona && (
          <div style={{ marginTop: 10 }}>
            <Space>
              <Button
                size="small"
                type="primary"
                ghost
                onClick={() => handleApplyPreset(selectedPersona)}
                loading={saving}
              >
                应用该人群的默认值（活动强度、用餐时间）
              </Button>
              <Button size="small" onClick={() => setShowApplyPreset(false)}>
                跳过
              </Button>
            </Space>
          </div>
        )}
      </div>

      <Row gutter={[20, 20]}>
        {/* 档案表单 */}
        <Col xs={24} md={16}>
          <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
            <Form layout="vertical" size="small">
              <Form.Item label="性别">
                <Segmented
                  options={['男', '女', '其他']}
                  value={gender || '其他'}
                  onChange={(v) => setGender(v as string)}
                />
              </Form.Item>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item label="出生年份">
                    <InputNumber
                      value={birthYear}
                      onChange={(v) => setBirthYear(v)}
                      min={1900}
                      max={new Date().getFullYear()}
                      placeholder="如：1990"
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="身高 (cm)">
                    <InputNumber
                      value={heightCm}
                      onChange={(v) => setHeightCm(v)}
                      min={100}
                      max={250}
                      placeholder="如：170"
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="体重 (kg)">
                    <InputNumber
                      value={weightKg}
                      onChange={(v) => setWeightKg(v)}
                      min={25}
                      max={300}
                      placeholder="如：65"
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item label="活动强度">
                <Segmented
                  options={['低', '中', '高']}
                  value={activityLevel}
                  onChange={(v) => setActivityLevel(v as string)}
                />
              </Form.Item>
            </Form>
          </Card>

          <Card title="健康信息" size="small" style={{ marginBottom: 16 }}>
            <Form layout="vertical" size="small">
              <Form.Item label="疾病史 / 慢性病">
                <TextArea
                  value={conditions}
                  onChange={(e) => setConditions(e.target.value)}
                  rows={2}
                  placeholder="如：高血压、糖尿病；没有可留空"
                />
              </Form.Item>
              <Form.Item label="正在服用的药物">
                <TextArea
                  value={medications}
                  onChange={(e) => setMedications(e.target.value)}
                  rows={2}
                  placeholder="如：二甲双胍、华法林；没有可留空"
                />
              </Form.Item>
              <Form.Item label="食物过敏 / 不耐受">
                <TextArea
                  value={allergies}
                  onChange={(e) => setAllergies(e.target.value)}
                  rows={2}
                  placeholder="如：花生、海鲜、乳糖；没有可留空"
                />
              </Form.Item>
              <Form.Item label="饮食偏好">
                <TextArea
                  value={preferences}
                  onChange={(e) => setPreferences(e.target.value)}
                  rows={2}
                  placeholder="如：不吃辣、偏素、喜欢清淡；可留空"
                />
              </Form.Item>
              <Form.Item label="健康目标">
                <TextArea
                  value={goals}
                  onChange={(e) => setGoals(e.target.value)}
                  rows={2}
                  placeholder="如：控制体重、增肌、改善睡眠；可留空"
                />
              </Form.Item>
              <Form.Item label="中医体质（可通过体质自测获取）">
                <Select
                  allowClear
                  placeholder="请选择或通过体质自测获取"
                  value={tcmConstitution}
                  onChange={(v) => setTcmConstitution(v)}
                  options={TCM_CONSTITUTIONS.map((c) => ({ label: c, value: c }))}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Form>
          </Card>

          <Card title="用餐习惯" size="small" style={{ marginBottom: 16 }}>
            <Form layout="vertical" size="small">
              <Form.Item label="用餐时间">
                <Row gutter={8}>
                  {['早餐', '午餐', '晚餐', '加餐'].map((meal) => (
                    <Col key={meal} span={12} style={{ marginBottom: 8 }}>
                      <div style={{ marginBottom: 4, fontSize: 12, color: token.colorTextSecondary }}>
                        {meal}
                      </div>
                      <TimePicker
                        format="HH:mm"
                        value={mealTimes[meal] ? dayjs(mealTimes[meal], 'HH:mm') : null}
                        onChange={(d) => {
                          setMealTimes((prev) => ({
                            ...prev,
                            [meal]: d ? d.format('HH:mm') : '',
                          }));
                        }}
                        style={{ width: '100%' }}
                        placeholder={`${meal}时间`}
                      />
                    </Col>
                  ))}
                </Row>
              </Form.Item>
              <Form.Item label="饮食预算">
                <Segmented
                  options={['低', '中', '高']}
                  value={budgetLevel}
                  onChange={(v) => setBudgetLevel(v as string)}
                />
              </Form.Item>
              <Form.Item label="烹饪能力">
                <Segmented
                  options={['低', '中', '高']}
                  value={cookingAbility}
                  onChange={(v) => setCookingAbility(v as string)}
                />
              </Form.Item>
            </Form>
          </Card>

          <Button
            type="primary"
            loading={saving}
            onClick={handleSave}
            block={isMobile}
            size="large"
          >
            保存档案
          </Button>
        </Col>

        {/* 摘要卡片 */}
        <Col xs={24} md={8}>
          <div style={{ position: isMobile ? 'static' : 'sticky', top: 20 }}>
            <Card title="健康摘要" size="small" style={{ marginBottom: 12 }}>
              {profile?.bmi ? (
                <div style={{ textAlign: 'center', marginBottom: 16 }}>
                  <div style={{ fontSize: 48, fontWeight: 700, color: token.colorPrimary, lineHeight: 1.1 }}>
                    {profile.bmi}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <Tag color={bmiTagColor(profile.bmi_category)}>BMI {profile.bmi_category}</Tag>
                  </div>
                  {profile.age && (
                    <div style={{ marginTop: 6, color: token.colorTextSecondary, fontSize: 13 }}>
                      年龄：{profile.age} 岁
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ color: token.colorTextTertiary, fontSize: 13, marginBottom: 12 }}>
                  填写身高、体重、出生年份后显示 BMI
                </div>
              )}

              {profile?.estimated_daily_energy_kcal && (
                <div style={{ marginBottom: 12 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>估算每日能量需求</Text>
                  <div style={{ fontSize: 20, fontWeight: 600 }}>
                    {profile.estimated_daily_energy_kcal}{' '}
                    <span style={{ fontSize: 13, fontWeight: 400 }}>kcal</span>
                  </div>
                  {profile.estimated_daily_energy_note && (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {profile.estimated_daily_energy_note}
                    </Text>
                  )}
                </div>
              )}

              {(profile?.cautions ?? []).length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="注意事项"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
                      {(profile?.cautions ?? []).map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  }
                  style={{ marginBottom: 12 }}
                />
              )}
            </Card>

            {profile?.disclaimer && (
              <Alert
                type="info"
                showIcon
                message={profile.disclaimer}
                style={{ fontSize: 12 }}
              />
            )}
          </div>
        </Col>
      </Row>
    </div>
  );
}

// ============================================================
// Tab 2 — 体质自测
// ============================================================
function QuizTab() {
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [note, setNote] = useState('');
  const [disclaimer, setDisclaimer] = useState('');
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<QuizResultOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);

  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();

  useEffect(() => {
    setLoading(true);
    getConstitutionQuiz()
      .then((r) => {
        setQuestions(r.questions);
        setNote(r.note);
        setDisclaimer(r.disclaimer);
      })
      .catch(() => {/* 忽略 */})
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit() {
    const answered = questions.map((q) => ({
      question_id: q.id,
      value: answers[q.id] ?? 1,
    }));
    setSubmitting(true);
    try {
      const r = await submitConstitutionQuiz(answered, false);
      setResult(r);
    } catch {
      /* 错误已显示 */
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSaveToProfile() {
    if (!result) return;
    setSaving(true);
    try {
      const answered = questions.map((q) => ({
        question_id: q.id,
        value: answers[q.id] ?? 1,
      }));
      await submitConstitutionQuiz(answered, true);
      message.success(`已将「${result.suggested}」保存到健康档案`);
    } catch {
      /* 错误已显示 */
    } finally {
      setSaving(false);
    }
  }

  const chartOption = (): EChartsOption => {
    if (!result) return {};
    const entries = Object.entries(result.scores).sort((a, b) => b[1] - a[1]);
    const names = entries.map(([k]) => k);
    const vals = entries.map(([, v]) => v);
    const dataItems = vals.map((v, i) => ({
      value: v,
      itemStyle: {
        color: names[i] === result.suggested ? token.colorPrimary : token.colorFill,
      },
    }));
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { show: false },
      grid: { top: 10, bottom: 20, left: 8, right: 8, containLabel: true },
      xAxis: {
        type: 'value',
        max: 100,
        axisLabel: { color: token.colorTextSecondary, fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        data: names,
        axisLabel: { fontSize: 11, color: token.colorTextSecondary },
      },
      series: [
        {
          type: 'bar',
          data: dataItems,
          label: { show: true, position: 'right', formatter: '{c}' },
        },
      ],
    };
  };

  if (loading) {
    return (
      <div>
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginBottom: 16 }} />
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    );
  }

  return (
    <div>
      <Alert type="info" message={note} showIcon style={{ marginBottom: 20 }} />

      {!result && (
        <div>
          {questions.map((q, qi) => (
            <Card key={q.id} size="small" style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 500, marginBottom: 10 }}>
                {qi + 1}. {q.text}
              </div>
              <Radio.Group
                value={answers[q.id]}
                onChange={(e) =>
                  setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                }
              >
                <Space direction="vertical">
                  {q.options.map((opt) => (
                    <Radio key={opt.value} value={opt.value}>
                      {opt.label}
                    </Radio>
                  ))}
                </Space>
              </Radio.Group>
            </Card>
          ))}

          <Button
            type="primary"
            size="large"
            block
            loading={submitting}
            onClick={handleSubmit}
            style={{ marginTop: 8 }}
          >
            提交测试
          </Button>
        </div>
      )}

      {result && (
        <div>
          <Card
            title={
              <span>
                测试结果：建议体质{' '}
                <Tag color={token.colorPrimary} style={{ fontSize: 15, padding: '2px 12px' }}>
                  {result.suggested}
                </Tag>
              </span>
            }
            size="small"
            style={{ marginBottom: 16 }}
          >
            <ReactECharts
              option={chartOption()}
              style={{ height: Math.max(220, questions.length * 28) }}
              notMerge
              theme={resolved === 'dark' ? 'dark' : undefined}
              opts={{ renderer: 'canvas' }}
            />
          </Card>

          <Card
            title="九种体质简介（参考）"
            size="small"
            style={{ marginBottom: 16 }}
            extra={<Tag color="default">参考</Tag>}
          >
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: token.colorFillAlter }}>
                    <th style={{ padding: '6px 10px', textAlign: 'left', border: `1px solid ${token.colorBorderSecondary}` }}>体质</th>
                    <th style={{ padding: '6px 10px', textAlign: 'left', border: `1px solid ${token.colorBorderSecondary}` }}>特征简述</th>
                    <th style={{ padding: '6px 10px', textAlign: 'center', border: `1px solid ${token.colorBorderSecondary}` }}>得分</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(TCM_DESC).map(([name, desc]) => (
                    <tr
                      key={name}
                      style={{ background: name === result.suggested ? token.colorPrimaryBg : 'transparent' }}
                    >
                      <td style={{ padding: '6px 10px', border: `1px solid ${token.colorBorderSecondary}`, whiteSpace: 'nowrap' }}>
                        {name === result.suggested && (
                          <CheckCircleOutlined style={{ color: token.colorPrimary, marginRight: 4 }} />
                        )}
                        {name}
                      </td>
                      <td style={{ padding: '6px 10px', border: `1px solid ${token.colorBorderSecondary}` }}>{desc}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'center', border: `1px solid ${token.colorBorderSecondary}` }}>
                        {result.scores[name] ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Space wrap>
            <Button type="primary" onClick={handleSaveToProfile} loading={saving}>
              保存到档案
            </Button>
            <Button onClick={() => { setResult(null); setAnswers({}); }}>
              重新测试
            </Button>
          </Space>

          <Alert
            type="info"
            showIcon
            message={disclaimer}
            style={{ marginTop: 16, fontSize: 11 }}
          />
        </div>
      )}
    </div>
  );
}

// ============================================================
// Tab 3 — 个性化餐单
// ============================================================

/** 菜品图：有真实图片优先用 200×150 缩略图；否则用 emoji 兜底，绝不空白。 */
function DishImage({ dish, height = 72 }: { dish: PlanDish; height?: number }) {
  const [broken, setBroken] = useState(false);
  const raw = dish.thumb_url || dish.image_url;
  const src = raw ? (raw.startsWith('http') || raw.startsWith('/') ? raw : `/${raw}`) : '';

  if (src && !broken) {
    return (
      <img
        src={src}
        alt={dish.name}
        loading="lazy"
        decoding="async"
        onError={() => setBroken(true)}
        style={{
          width: '100%',
          height,
          objectFit: 'cover',
          borderRadius: 6,
          marginBottom: 5,
          background: '#f5f5f5',
        }}
      />
    );
  }

  const emoji = dish.image_emoji || '🍽';
  return (
    <div
      style={{
        height,
        borderRadius: 6,
        marginBottom: 5,
        display: 'grid',
        placeItems: 'center',
        background: dish.image_bg || 'linear-gradient(135deg, #fdf6ec 0%, #fdebd0 100%)',
      }}
    >
      {dish.image_emoji_url ? (
        <img
          src={dish.image_emoji_url}
          alt={dish.name}
          loading="lazy"
          width={Math.round(height * 0.72)}
          height={Math.round(height * 0.72)}
          onError={(e) => {
            // Twemoji CDN 不可达时退回系统原生 emoji
            const el = e.currentTarget;
            el.style.display = 'none';
            el.parentElement?.insertAdjacentText('afterbegin', emoji);
          }}
        />
      ) : (
        <span style={{ fontSize: Math.round(height * 0.44) }}>{emoji}</span>
      )}
    </div>
  );
}

function DishTag({ dish }: { dish: PlanDish }) {
  const noteText = dish.note ? `${dish.portion}量 · ${dish.note}` : `${dish.portion}量`;
  return (
    <Tooltip title={noteText}>
      <Card size="small" bodyStyle={{ padding: 8 }} style={{ width: 132, marginBottom: 4 }}>
        <DishImage dish={dish} />
        <div style={{ fontWeight: 600, fontSize: 12, lineHeight: 1.35, wordBreak: 'break-word' }}>{dish.name}</div>
        <Text type="secondary" style={{ fontSize: 11 }}>{dish.portion}量</Text>
      </Card>
    </Tooltip>
  );
}

interface SlotReplacePopoverProps {
  onConfirm: (instruction: string) => void;
  loading: boolean;
  disabled?: boolean;
}

function SlotReplacePopover({ onConfirm, loading, disabled }: SlotReplacePopoverProps) {
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState('');

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      title="换一换这顿"
      content={
        <div style={{ width: 220 }}>
          <div style={{ marginBottom: 8 }}>
            {SWAP_PRESETS.map((p) => (
              <Tag
                key={p}
                style={{ cursor: 'pointer', marginBottom: 4 }}
                onClick={() => setInstruction(p)}
                color={instruction === p ? 'blue' : 'default'}
              >
                {p}
              </Tag>
            ))}
          </div>
          <Input
            placeholder="或输入自定义要求"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            style={{ marginBottom: 8 }}
          />
          <Button
            type="primary"
            size="small"
            block
            loading={loading}
            onClick={() => {
              onConfirm(instruction);
              setOpen(false);
              setInstruction('');
            }}
          >
            重新生成
          </Button>
        </div>
      }
    >
      <Button size="small" icon={<ReloadOutlined />} disabled={disabled}>
        换一换
      </Button>
    </Popover>
  );
}

interface PlansTabProps {
  onSwitchTab: (key: string) => void;
}

function PlansTab({ onSwitchTab }: PlansTabProps) {
  const [planDays, setPlanDays] = useState<3 | 5 | 7>(3);
  const [startDate, setStartDate] = useState<Dayjs>(dayjs());
  const [focus, setFocus] = useState('');
  const [generating, setGenerating] = useState(false);
  const [pollingFor409, setPollingFor409] = useState(false);
  const [currentPlan, setCurrentPlan] = useState<MealPlanOut | null>(null);
  const [planList, setPlanList] = useState<MealPlanOut[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [selectedDayIdx, setSelectedDayIdx] = useState(0);
  const [editMode, setEditMode] = useState(false);
  const [editDays, setEditDays] = useState<PlanDay[]>([]);
  const [slotLoading, setSlotLoading] = useState<string | null>(null);
  const [todayMeals, setTodayMeals] = useState<{ date: string; meals: PlanMeal[] } | null>(null);
  const [profileIncomplete, setProfileIncomplete] = useState(false);
  const [swapsLoading, setSwapsLoading] = useState<string | false>(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<PlanVersionItem[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [slotRemoteBusy, setSlotRemoteBusy] = useState(false);
  const slotPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 用 AI 生图批量替换 emoji 图（v0.8.6）
  const [aiImagesOn, setAiImagesOn] = useState(false);
  const [replacingEmoji, setReplacingEmoji] = useState(false);
  const [replaceProgress, setReplaceProgress] = useState(0);
  const replacePollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { token } = antdTheme.useToken();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (slotPollRef.current) clearInterval(slotPollRef.current);
      if (replacePollRef.current) clearInterval(replacePollRef.current);
    };
  }, []);

  const loadList = useCallback(async () => {
    setLoadingList(true);
    try {
      const list = await listPlans();
      // Dedupe by id, sort by created_at desc
      const dedupedMap = new Map<number, MealPlanOut>();
      for (const p of list) dedupedMap.set(p.id, p);
      const deduped = Array.from(dedupedMap.values()).sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setPlanList(deduped);
      const active = deduped.find((p) => p.is_active);
      // 进入「健康」页直接展示当前使用中的餐单（未手动选择其他餐单时）
      if (active) setCurrentPlan((prev) => prev ?? active);
      if (active) {
        try {
          const today = await getTodayMeals(active.id);
          setTodayMeals(today);
        } catch {
          /* 忽略 */
        }
      }
    } catch {
      /* 忽略 */
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    loadList();
    // Check profile completeness
    getProfile()
      .then((p) => {
        setProfileIncomplete(!p.height_cm || !p.weight_kg);
      })
      .catch(() => { /* ignore */ });
    // 刷新后若服务端仍在生成餐单 / 重做单餐，则恢复“生成中”状态，避免重复点击
    getPlanGenerating()
      .then((s) => {
        if (s.generating) { startPolling409(); startReplacePolling(); }
        if (s.slot) startSlotPolling();
      })
      .catch(() => { /* ignore */ });
    // 是否开启了 AI 生图（决定「替换 emoji 图」按钮是否亮起）
    getSettings()
      .then((s) => setAiImagesOn(Boolean(s.dish_ai_images) && Boolean(s.image_ready)))
      .catch(() => { /* 非管理员 / 未登录时忽略 */ });
  }, [loadList]);

  /** 刷新后恢复“单餐重新生成中”状态并轮询解除 */
  function startSlotPolling() {
    if (slotPollRef.current) return;
    setSlotRemoteBusy(true);
    slotPollRef.current = setInterval(async () => {
      try {
        const s = await getPlanGenerating();
        if (!s.slot) {
          if (slotPollRef.current) clearInterval(slotPollRef.current);
          slotPollRef.current = null;
          setSlotRemoteBusy(false);
          await loadList();
        }
      } catch {
        /* ignore */
      }
    }, 4000);
  }

  const isGenerating = generating || pollingFor409;

  function startPolling409() {
    setPollingFor409(true);
    let attempts = 0;
    const maxAttempts = 48; // 4 min at 5s intervals

    pollTimerRef.current = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(pollTimerRef.current!);
        pollTimerRef.current = null;
        setPollingFor409(false);
        return;
      }
      try {
        const list = await listPlans();
        const dedupedMap = new Map<number, MealPlanOut>();
        for (const p of list) dedupedMap.set(p.id, p);
        const deduped = Array.from(dedupedMap.values()).sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        );
        const newActive = deduped.find((p) => p.is_active);
        if (newActive) {
          clearInterval(pollTimerRef.current!);
          pollTimerRef.current = null;
          setPollingFor409(false);
          setPlanList(deduped);
          setCurrentPlan(newActive);
          setSelectedDayIdx(0);
          setEditMode(false);
          message.success('餐单已生成');
          try {
            const today = await getTodayMeals(newActive.id);
            setTodayMeals(today);
          } catch { /* ignore */ }
        }
      } catch { /* ignore */ }
    }, 5000);
  }

  /**
   * 刷新后恢复「正在把 emoji 图替换为 AI 图」的等待态。
   * 服务端把该任务登记为 busy("plan")，因此刷新后仍能查到。
   */
  function startReplacePolling() {
    if (replacePollRef.current) return;
    setReplacingEmoji(true);
    setReplaceProgress(0);
    replacePollRef.current = setInterval(async () => {
      try {
        const s = await getPlanGenerating();
        if (!s.generating) {
          if (replacePollRef.current) clearInterval(replacePollRef.current);
          replacePollRef.current = null;
          setReplacingEmoji(false);
          setReplaceProgress(0);
          message.success('emoji 图已替换完成');
          await loadList();
          try {
            const list = await listPlans();
            const active = list.find((p) => p.is_active);
            if (active) setCurrentPlan(active);
          } catch { /* ignore */ }
        } else {
          setReplaceProgress((n) => (n >= 90 ? 90 : n + 3));
        }
      } catch { /* ignore */ }
    }, 4000);
  }

  /** 一键把餐单里仍是 emoji 的菜品用 AI 生图替换掉 */
  async function handleReplaceEmojiImages() {
    if (!currentPlan || replacingEmoji) return;
    setReplacingEmoji(true);
    setReplaceProgress(5);
    // 进度条纯粹是“等待感”，服务端不回报进度，故在 90% 处封顶
    const tick = setInterval(() => setReplaceProgress((n) => (n >= 90 ? 90 : n + 2)), 2500);
    try {
      const updated = await replaceEmojiImages(currentPlan.id);
      clearInterval(tick);
      setCurrentPlan(updated);
      setReplaceProgress(100);
      const r = updated.replace_result;
      if (r && r.remaining > 0) {
        message.warning(
          `已替换 ${r.total - r.remaining}/${r.total} 道菜，仍有 ${r.remaining} 道未能生成（可再试一次）`,
        );
      } else {
        message.success('emoji 图已全部替换为 AI 生图');
      }
      await loadList();
    } catch (err: unknown) {
      clearInterval(tick);
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        message.info('替换任务正在进行中，请稍候');
        startReplacePolling();
      } else {
        // 400（未开启 / 未配置）等错误已由拦截器提示
        setReplacingEmoji(false);
      }
    } finally {
      setReplaceProgress(0);
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    try {
      const plan = await createPlan({
        days: planDays,
        start_date: startDate.format('YYYY-MM-DD'),
        focus: focus || undefined,
      });
      setCurrentPlan(plan);
      setSelectedDayIdx(0);
      setEditMode(false);
      await loadList();
      message.success('餐单已生成');
    } catch (err: unknown) {
      // Check for 409 (interceptor already showed warning toast)
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        startPolling409();
      }
      // Other errors already handled by interceptor
    } finally {
      setGenerating(false);
    }
  }

  async function handleSlotReplace(dayIndex: number, mealIndex: number, instruction: string) {
    if (!currentPlan) return;
    const key = `${dayIndex}-${mealIndex}`;
    setSlotLoading(key);
    try {
      const updated = await updatePlanSlot(
        currentPlan.id,
        dayIndex,
        mealIndex,
        instruction || undefined,
      );
      setCurrentPlan(updated);
      message.success('已重新生成该餐');
    } catch {
      /* 错误已显示 */
    } finally {
      setSlotLoading(null);
    }
  }

  async function handleApplySwap(planId: number, swapInstruction: string) {
    setSwapsLoading(swapInstruction);
    try {
      const updated = await applyPlanSwap(planId, swapInstruction);
      setCurrentPlan(updated);
      const warn = (updated.warnings ?? []).slice(-1)[0];
      message.success(warn || '已应用替换建议（可在“历史版本”中回退）');
    } catch {
      /* 错误已显示 */
    } finally {
      setSwapsLoading(false);
    }
  }

  function handleApplyAllSwaps(swaps: string[]) {
    if (!currentPlan || swaps.length === 0) return;
    handleApplySwap(currentPlan.id, swaps.join('；'));
  }

  async function openVersions() {
    if (!currentPlan) return;
    setVersionsOpen(true);
    setVersionsLoading(true);
    try {
      setVersions(await listPlanVersions(currentPlan.id));
    } catch {
      /* 错误已显示 */
    } finally {
      setVersionsLoading(false);
    }
  }

  async function handleRestoreVersion(versionId: number) {
    if (!currentPlan) return;
    setRestoringId(versionId);
    try {
      const updated = await restorePlanVersion(currentPlan.id, versionId);
      setCurrentPlan(updated);
      setEditMode(false);
      message.success('已恢复到该历史版本');
      setVersions(await listPlanVersions(currentPlan.id));
    } catch {
      /* 错误已显示 */
    } finally {
      setRestoringId(null);
    }
  }

  function startEdit() {
    if (!currentPlan) return;
    setEditDays(JSON.parse(JSON.stringify(currentPlan.plan?.days ?? [])));
    setEditMode(true);
  }

  async function handleSaveEdit() {
    if (!currentPlan) return;
    try {
      const updated = await updatePlanDays(currentPlan.id, editDays);
      setCurrentPlan(updated);
      setEditMode(false);
      message.success('已保存修改');
    } catch {
      /* 错误已显示 */
    }
  }

  async function handleActivate(id: number) {
    try {
      await activatePlan(id);
      message.success('餐单已激活');
      await loadList();
    } catch {
      /* 错误已显示 */
    }
  }

  async function handleDeletePlan(id: number) {
    try {
      await deletePlan(id);
      if (currentPlan?.id === id) setCurrentPlan(null);
      await loadList();
      message.success('餐单已删除');
    } catch {
      /* 错误已显示 */
    }
  }

  const planData = currentPlan?.plan;
  const activePlan = planList.find((p) => p.is_active);

  // Defensive: days array
  const planDaysList = planData?.days ?? [];
  const hasValidDays = planDaysList.length > 0;

  // Wrap text style for long content
  const wrapStyle: React.CSSProperties = {
    wordBreak: 'break-word',
    whiteSpace: 'normal',
    overflowWrap: 'anywhere',
  };

  return (
    <div style={{ maxWidth: '100%', overflowX: 'hidden' }}>
      {/* 档案不完整提示 */}
      {profileIncomplete && (
        <Alert
          type="info"
          showIcon
          message={
            <span>
              先完善档案可让餐单更贴合你{' '}
              <Button
                type="link"
                size="small"
                style={{ padding: 0, height: 'auto' }}
                onClick={() => onSwitchTab('profile')}
              >
                去完善档案
              </Button>
            </span>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 今日餐单 */}
      {todayMeals && (todayMeals.meals ?? []).length > 0 && (
        <Card
          title={`今日餐单 · ${dayjs(todayMeals.date).format('M月D日')}`}
          size="small"
          style={{ marginBottom: 16 }}
          extra={activePlan && <Tag color="success">{activePlan.title}</Tag>}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {(todayMeals.meals ?? []).map((m, i) => (
              <Card key={i} size="small" style={{ minWidth: 140, flex: 1 }}>
                <div style={{ marginBottom: 6 }}>
                  <Tag color={MEAL_TYPE_COLORS[m.meal_type] ?? 'default'}>{m.meal_type}</Tag>
                  <Text type="secondary" style={{ fontSize: 11 }}>{m.time}</Text>
                </div>
                <div>
                  {(m.dishes ?? []).map((d, j) => (
                    <DishTag key={j} dish={d} />
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {/* 生成工具栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>天数</Text>
            <Segmented
              options={[
                { label: '3天', value: 3 },
                { label: '5天', value: 5 },
                { label: '7天', value: 7 },
              ]}
              value={planDays}
              onChange={(v) => setPlanDays(v as 3 | 5 | 7)}
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>开始日期</Text>
            <DatePicker
              value={startDate}
              onChange={(d) => d && setStartDate(d)}
              allowClear={false}
              format="MM-DD"
            />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>特别要求（可选）</Text>
            <Input
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="如：减少含糖饮料、清淡、增肌"
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <Button
              type="primary"
              onClick={handleGenerate}
              loading={generating}
              disabled={isGenerating}
            >
              {generating
                ? 'AI 正在结合你的档案与近期记录生成餐单…'
                : pollingFor409
                ? '等待生成结果…'
                : '生成餐单'}
            </Button>
          </div>
        </div>
        {isGenerating && (
          <Alert
            type="info"
            showIcon
            message="大模型生成餐单通常需要 1~3 分钟，请勿重复点击"
            style={{ marginTop: 10 }}
          />
        )}
      </Card>

      {/* AI 生图：批量替换 emoji 兜底图 */}
      {currentPlan &&
        aiImagesOn &&
        (currentPlan.image_stats?.emoji ?? 0) > 0 &&
        !isGenerating && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={
              <span>
                当前餐单中还有 <b>{currentPlan.image_stats?.emoji}</b>/
                {currentPlan.image_stats?.total} 道菜使用 emoji 占位
              </span>
            }
            description="用 AI 生图为这些菜品生成统一风格的配图（中餐更准、风格一致）。图片较多时需要 1~3 分钟，期间请勿重复点击。"
            action={
              <Button
                type="primary"
                size="small"
                loading={replacingEmoji}
                disabled={replacingEmoji || slotRemoteBusy}
                onClick={handleReplaceEmojiImages}
              >
                {replacingEmoji ? '正在生成…' : '用 AI 生图替换掉 emoji 图'}
              </Button>
            }
          />
        )}
      {replacingEmoji && (
        <div style={{ marginBottom: 12 }}>
          <Progress
            percent={replaceProgress}
            size="small"
            status="active"
            format={() => '正在生成配图…'}
          />
        </div>
      )}

      {/* 警告 */}
      {(currentPlan?.warnings ?? []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={
            <ul style={{ margin: 0, paddingLeft: 16, ...wrapStyle }}>
              {(currentPlan?.warnings ?? []).map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}
      {(currentPlan?.cautions ?? []).length > 0 && (
        <Alert
          type="info"
          showIcon
          message="饮食注意事项"
          description={
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, ...wrapStyle }}>
              {(currentPlan?.cautions ?? []).map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 餐单主体 */}
      {planData && currentPlan && (
        <>
          {!hasValidDays ? (
            <Alert
              type="warning"
              showIcon
              message="该餐单数据不完整，可删除后重新生成"
              action={
                <Button
                  size="small"
                  danger
                  onClick={() => handleDeletePlan(currentPlan.id)}
                >
                  删除
                </Button>
              }
              style={{ marginBottom: 12 }}
            />
          ) : (
            <ErrorBoundary resetKey={`plan-${currentPlan.id}`}>
              <div>
                {/* 操作栏 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <Title level={5} style={{ margin: 0, ...wrapStyle }}>
                    {planData.title || currentPlan.title}
                  </Title>
                  <Space>
                    <Button size="small" icon={<HistoryOutlined />} onClick={openVersions}>
                      历史版本
                    </Button>
                    {!editMode ? (
                      <Button size="small" icon={<EditOutlined />} onClick={startEdit}>
                        编辑
                      </Button>
                    ) : (
                      <>
                        <Button size="small" type="primary" onClick={handleSaveEdit}>
                          保存修改
                        </Button>
                        <Button size="small" onClick={() => setEditMode(false)}>
                          取消
                        </Button>
                      </>
                    )}
                  </Space>
                </div>

                {/* 历史版本抽屉：界面化回退 */}
                <Drawer
                  title="历史版本"
                  placement={isMobile ? 'bottom' : 'right'}
                  height={isMobile ? '70%' : undefined}
                  width={isMobile ? undefined : 380}
                  open={versionsOpen}
                  onClose={() => setVersionsOpen(false)}
                >
                  {versionsLoading ? (
                    <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
                  ) : versions.length === 0 ? (
                    <Alert
                      type="info"
                      showIcon
                      message="暂无历史版本"
                      description="应用替换建议、重新生成或手动编辑后，系统会自动在此保存可回退的版本。"
                    />
                  ) : (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        共 {versions.length} 个版本，恢复前会自动备份当前餐单。
                      </Text>
                      <div style={{ marginTop: 10 }}>
                        {versions.map((v) => (
                          <div
                            key={v.id}
                            style={{
                              padding: '10px 12px',
                              marginBottom: 8,
                              borderRadius: 8,
                              border: `1px solid ${token.colorBorderSecondary}`,
                              background: token.colorFillAlter,
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 500, ...wrapStyle }}>
                                  {v.reason || '历史版本'}
                                </div>
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  {dayjs(v.created_at).format('YYYY-MM-DD HH:mm')} · {v.days}天 · {v.dish_count}道菜
                                </Text>
                              </div>
                              <Button
                                size="small"
                                type="link"
                                loading={restoringId === v.id}
                                onClick={() => handleRestoreVersion(v.id)}
                              >
                                恢复
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </Drawer>

                {/* 日期选项卡 - 横向可滚动，不撑宽页面 */}
                <div
                  style={{
                    overflowX: 'auto',
                    WebkitOverflowScrolling: 'touch',
                    paddingBottom: 8,
                    marginBottom: 12,
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, width: 'max-content' }}>
                    {planDaysList.map((day, di) => (
                      <Button
                        key={di}
                        size="small"
                        type={selectedDayIdx === di ? 'primary' : 'default'}
                        onClick={() => setSelectedDayIdx(di)}
                        style={{ flexShrink: 0 }}
                      >
                        {dayjs(day.date).format('M/D')}
                      </Button>
                    ))}
                  </div>
                </div>

                {/* 当天餐次 */}
                {(() => {
                  const day = planDaysList[selectedDayIdx];
                  if (!day) return null;
                  const dayMeals = day.meals ?? [];
                  if (dayMeals.length === 0) {
                    return (
                      <Alert
                        type="warning"
                        showIcon
                        message="该餐单数据不完整，可删除后重新生成"
                        action={
                          <Button size="small" danger onClick={() => handleDeletePlan(currentPlan.id)}>
                            删除
                          </Button>
                        }
                        style={{ marginBottom: 12 }}
                      />
                    );
                  }
                  return (
                    <div>
                      {dayMeals.map((meal, mi) => {
                        const slotKey = `${selectedDayIdx}-${mi}`;
                        const isSlotLoading = slotLoading === slotKey;

                        return (
                          <Card
                            key={mi}
                            size="small"
                            style={{ marginBottom: 10 }}
                            title={
                              <span>
                                <Tag color={MEAL_TYPE_COLORS[meal.meal_type] ?? 'default'}>
                                  {meal.meal_type}
                                </Tag>
                                {editMode ? (
                                  <TimePicker
                                    format="HH:mm"
                                    size="small"
                                    value={
                                      editDays[selectedDayIdx]?.meals[mi]?.time
                                        ? dayjs(editDays[selectedDayIdx].meals[mi].time, 'HH:mm')
                                        : null
                                    }
                                    onChange={(d) => {
                                      if (!d) return;
                                      const newDays = JSON.parse(JSON.stringify(editDays)) as PlanDay[];
                                      newDays[selectedDayIdx].meals[mi].time = d.format('HH:mm');
                                      setEditDays(newDays);
                                    }}
                                  />
                                ) : (
                                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                                    {meal.time}
                                  </Text>
                                )}
                              </span>
                            }
                            extra={
                              !editMode && (
                                <SlotReplacePopover
                                  loading={isSlotLoading}
                                  disabled={slotRemoteBusy}
                                  onConfirm={(inst) => handleSlotReplace(selectedDayIdx, mi, inst)}
                                />
                              )
                            }
                          >
                            {isSlotLoading ? (
                              <Spin size="small" />
                            ) : (
                              <div>
                                <div style={{ marginBottom: 6, flexWrap: 'wrap', display: 'flex', gap: 6, alignItems: 'stretch' }}>
                                  {editMode
                                    ? (editDays[selectedDayIdx]?.meals[mi]?.dishes ?? []).map((d, di2) => (
                                        <Input
                                          key={di2}
                                          size="small"
                                          value={d.name}
                                          onChange={(e) => {
                                            const newDays = JSON.parse(JSON.stringify(editDays)) as PlanDay[];
                                            newDays[selectedDayIdx].meals[mi].dishes[di2].name = e.target.value;
                                            setEditDays(newDays);
                                          }}
                                          style={{ width: 'auto', marginRight: 6, marginBottom: 4 }}
                                        />
                                      ))
                                    : (meal.dishes ?? []).map((d, di2) => <DishTag key={di2} dish={d} />)}
                                </div>
                                {meal.tip && (
                                  <Text
                                    type="secondary"
                                    style={{ fontSize: 12, fontStyle: 'italic', display: 'block', ...wrapStyle }}
                                  >
                                    {meal.tip}
                                  </Text>
                                )}
                              </div>
                            )}
                          </Card>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* 方案说明 */}
                {planData.rationale && (
                  <Card title="方案说明" size="small" style={{ marginBottom: 12 }}>
                    <Row gutter={[16, 8]}>
                      <Col xs={24} md={12}>
                        <div style={{ fontWeight: 500, marginBottom: 6, color: token.colorPrimary }}>
                          现代营养视角
                        </div>
                        <Text style={{ fontSize: 13, ...wrapStyle, display: 'block' }}>
                          {planData.rationale.nutrition}
                        </Text>
                      </Col>
                      <Col xs={24} md={12}>
                        <div style={{ fontWeight: 500, marginBottom: 6, color: token.colorPrimary }}>
                          中医体质视角
                        </div>
                        <Text style={{ fontSize: 13, ...wrapStyle, display: 'block' }}>
                          {planData.rationale.tcm}
                        </Text>
                      </Col>
                    </Row>
                    {(planData.rationale.swaps ?? []).length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>替换建议：</Text>
                          {!editMode && currentPlan && (
                            <Button
                              size="small"
                              icon={<ReloadOutlined />}
                              onClick={() => handleApplyAllSwaps(planData.rationale.swaps ?? [])}
                              loading={swapsLoading !== false}
                            >
                              一键应用替换
                            </Button>
                          )}
                        </div>
                        <ul style={{ margin: '4px 0 0', paddingLeft: 20, fontSize: 13, ...wrapStyle }}>
                          {(planData.rationale.swaps ?? []).map((s, i) => (
                            <li key={i} style={{ ...wrapStyle, marginBottom: 6, padding: '6px 8px', borderRadius: 6, background: token.colorFillAlter }}>
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                                <span style={{ flex: 1 }}>{s}</span>
                                {!editMode && currentPlan && (
                                  <Button
                                    size="small"
                                    type="link"
                                    style={{ padding: '0 4px', whiteSpace: 'nowrap' }}
                                    onClick={() => handleApplySwap(currentPlan.id, s)}
                                    loading={swapsLoading === s}
                                  >
                                    应用
                                  </Button>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </Card>
                )}

                {/* 购物清单 */}
                {(planData.shopping_list ?? []).length > 0 && (
                  <Card
                    title="购物清单"
                    size="small"
                    style={{ marginBottom: 12 }}
                    extra={
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => {
                          navigator.clipboard
                            .writeText((planData.shopping_list ?? []).join('、'))
                            .then(() => message.success('已复制'))
                            .catch(() => message.warning('复制失败'));
                        }}
                      >
                        复制
                      </Button>
                    }
                  >
                    <ul style={{ margin: 0, paddingLeft: 20, ...wrapStyle }}>
                      {(planData.shopping_list ?? []).map((item, i) => (
                        <li key={i} style={{ marginBottom: 4, ...wrapStyle }}>{item}</li>
                      ))}
                    </ul>
                  </Card>
                )}

                {/* 免责声明 */}
                <Alert
                  type="info"
                  showIcon
                  message="非医疗建议，有疾病或用药请遵医嘱"
                  description={
                    <span style={wrapStyle}>{currentPlan.disclaimer}</span>
                  }
                  style={{ marginBottom: 16, fontSize: 12 }}
                />
              </div>
            </ErrorBoundary>
          )}
        </>
      )}

      {/* 历史餐单 */}
      <Divider>历史餐单</Divider>
      {loadingList ? (
        <Skeleton active paragraph={{ rows: 3 }} />
      ) : planList.length === 0 ? (
        <EmptyState
          emoji="🥗"
          hint="暂无餐单，填写健康档案后生成第一份个性化餐单"
          actionLabel="生成第一份餐单"
          onAction={handleGenerate}
          actionDisabled={isGenerating}
        />
      ) : (
        <div>
          {planList.map((p) => (
            <Card
              key={p.id}
              size="small"
              style={{ marginBottom: 8 }}
              title={
                <span style={{ flexWrap: 'wrap', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {p.is_active && (
                    <Tag color="success" style={{ marginRight: 6 }}>
                      当前使用
                    </Tag>
                  )}
                  <span style={wrapStyle}>{p.title}</span>
                  <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                    {dayjs(p.created_at).format('MM-DD HH:mm')} · {p.days}天
                  </Text>
                </span>
              }
              extra={
                <Space size="small">
                  <Button
                    size="small"
                    onClick={() => {
                      setCurrentPlan(p);
                      setSelectedDayIdx(0);
                      setEditMode(false);
                    }}
                  >
                    查看
                  </Button>
                  {!p.is_active && (
                    <Button size="small" type="primary" ghost onClick={() => handleActivate(p.id)}>
                      激活
                    </Button>
                  )}
                  <Popconfirm
                    title="确定删除此餐单吗？"
                    onConfirm={() => handleDeletePlan(p.id)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              }
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                开始日期：{p.start_date}
              </Text>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// 主页面
// ============================================================
export default function HealthPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const validTabs = ['plans', 'profile', 'quiz'];
  const [activeTab, setActiveTab] = useState<string>(
    validTabs.includes(tabParam ?? '') ? (tabParam as string) : 'plans',
  );

  function handleTabChange(key: string) {
    setActiveTab(key);
    setSearchParams({ tab: key }, { replace: true });
  }

  return (
    <div>
      <PageHeader title="健康管理" subtitle="个性化餐单、健康档案与体质自测" />
      <div className="page-title">健康档案与餐单</div>
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        tabPosition="top"
        style={{ minHeight: 400 }}
        items={[
          {
            key: 'plans',
            label: '个性化餐单',
            children: <PlansTab onSwitchTab={handleTabChange} />,
          },
          {
            key: 'profile',
            label: '我的档案',
            children: <ProfileTab />,
          },
          {
            key: 'quiz',
            label: '体质自测',
            children: <QuizTab />,
          },
        ]}
      />
    </div>
  );
}

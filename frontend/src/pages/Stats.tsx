import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Segmented,
  DatePicker,
  Statistic,
  Skeleton,
  Empty,
  Alert,
  Typography,
  Card,
  Tag,
  Table,
  Grid,
  theme as antdTheme,
  Button,
} from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { getStats } from '../api/endpoints';
import type { StatsOut } from '../api/types';
import { useAppTheme } from '../theme/ThemeContext';
import ShareCard from '../components/ShareCard';
import PageHeader from '../components/PageHeader';

const { Text } = Typography;
const { useBreakpoint } = Grid;

// Fix: round to 1 decimal to avoid float noise
function roundDelta(n: number): number {
  return Math.round(n * 10) / 10;
}

function delta(n: number, primaryColor: string, textTertiary: string) {
  const abs = Math.abs(roundDelta(n));
  if (n > 0.005) return <span style={{ color: primaryColor }}>▲{abs}</span>;
  if (n < -0.005) return <span style={{ color: '#52c41a' }}>▼{abs}</span>;
  return <span style={{ color: textTertiary }}>—</span>;
}

function diffNum(cur: number, prev: number, primaryColor: string, textTertiary: string) {
  const d = cur - prev;
  return delta(d, primaryColor, textTertiary);
}

export default function StatsPage() {
  const navigate = useNavigate();
  const [range, setRange] = useState<'week' | 'month'>('week');
  const [anchor, setAnchor] = useState<Dayjs>(dayjs());
  const [stats, setStats] = useState<StatsOut | null>(null);
  const [loading, setLoading] = useState(false);
  const { token } = antdTheme.useToken();
  const { resolved } = useAppTheme();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const chartTheme = resolved === 'dark' ? 'dark' : undefined;
  const chartHeight = isMobile ? 200 : 260;

  useEffect(() => {
    setLoading(true);
    getStats(range, anchor.format('YYYY-MM-DD'))
      .then(setStats)
      .catch(() => {/* 忽略 */})
      .finally(() => setLoading(false));
  }, [range, anchor]);

  return (
    <div>
      <PageHeader title="统计图表" subtitle="周/月饮食结构与估算热量趋势" />
      {/* 控制栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          marginBottom: 24,
          background: token.colorBgContainer,
          borderRadius: 12,
          padding: '14px 20px',
          boxShadow: '0 1px 2px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.04)',
          flexWrap: 'wrap',
        }}
      >
        <Segmented
          options={[
            { label: '周', value: 'week' },
            { label: '月', value: 'month' },
          ]}
          value={range}
          onChange={(v) => setRange(v as 'week' | 'month')}
        />
        <DatePicker
          picker={range === 'week' ? 'week' : 'month'}
          value={anchor}
          onChange={(d) => d && setAnchor(d)}
          allowClear={false}
          format={range === 'week' ? 'YYYY 年第 w 周' : 'YYYY-MM'}
        />
        {stats && (
          <Text type="secondary" style={{ fontSize: 13 }}>
            {stats.period.label}
          </Text>
        )}
        <ShareCard
          kind={range === 'week' ? 'weekly' : 'monthly'}
          anchor={anchor.format('YYYY-MM-DD')}
        />
      </div>

      {loading ? (
        <div>
          <div className="stat-cards-row" style={{ marginBottom: 24 }}>
            {[0,1,2,3].map((i) => (
              <Card key={i} size="small">
                <Skeleton active paragraph={{ rows: 1 }} />
              </Card>
            ))}
          </div>
          <div className="chart-grid">
            {[0,1,2,3].map((i) => (
              <Card key={i} size="small">
                <Skeleton active paragraph={{ rows: 4 }} />
              </Card>
            ))}
          </div>
        </div>
      ) : !stats ? (
        <Empty description="暂无统计数据" />
      ) : stats.meal_count === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Empty
            description="该时段没有记录数据，去「记录一餐」拍一张吧。"
          />
          <Button type="primary" style={{ marginTop: 16 }} onClick={() => navigate('/')}>
            记录一餐
          </Button>
        </div>
      ) : (
        <>
          {/* 缺失日期提示 */}
          {stats.missing_days.length > 0 && (
            <Alert
              type="info"
              showIcon
              message={`本期有 ${stats.missing_days.length} 天没有记录：${stats.missing_days.slice(0, 5).join('、')}${stats.missing_days.length > 5 ? '…' : ''}`}
              style={{ marginBottom: 16 }}
            />
          )}

          {/* 摘要卡片 */}
          <div className="stat-cards-row">
            <Card size="small">
              <Statistic
                title="记录餐数"
                value={stats.meal_count}
                suffix={
                  <span style={{ fontSize: 13 }}>
                    {' '}
                    {diffNum(stats.meal_count, stats.prev.meal_count, token.colorPrimary, token.colorTextTertiary)}
                  </span>
                }
              />
            </Card>
            <Card size="small">
              <Statistic
                title="覆盖天数"
                value={stats.days_with_records}
                suffix={
                  <span style={{ fontSize: 12, color: token.colorTextTertiary }}>
                    /{stats.days_total} 天
                  </span>
                }
              />
            </Card>
            <Card size="small">
              <Statistic
                title="日均餐数"
                value={stats.avg_meals_per_day}
                precision={1}
                suffix={
                  <span style={{ fontSize: 13 }}>
                    {' '}
                    {diffNum(stats.avg_meals_per_day, stats.prev.avg_meals_per_day, token.colorPrimary, token.colorTextTertiary)}
                  </span>
                }
              />
            </Card>
            <Card size="small">
              <Statistic
                title="夜宵次数"
                value={stats.late_night_meals}
                valueStyle={{ color: stats.late_night_meals > 0 ? token.colorPrimary : undefined }}
              />
            </Card>
            {stats.kcal_avg_per_day != null && (
              <Card size="small">
                <Statistic
                  title="日均估算热量"
                  value={Math.round(stats.kcal_avg_per_day)}
                  suffix={
                    <span style={{ fontSize: 12, color: token.colorTextTertiary }}>
                      {' '}kcal
                      {stats.prev.kcal_avg_per_day != null && stats.kcal_avg_per_day != null && (
                        <span style={{ marginLeft: 4 }}>
                          {diffNum(stats.kcal_avg_per_day, stats.prev.kcal_avg_per_day, token.colorPrimary, token.colorTextTertiary)}
                        </span>
                      )}
                    </span>
                  }
                />
              </Card>
            )}
          </div>

          {/* 图表区 */}
          <div className="chart-grid">
            {/* 每日餐次 + 关注项折线 */}
            <Card title="每日餐次 & 关注标签" size="small">
              <div style={{ overflow: 'hidden' }}>
                <ReactECharts
                  option={dailyChartOption(stats, token.colorPrimary, token.colorTextSecondary)}
                  style={{ height: chartHeight }}
                  notMerge
                  theme={chartTheme}
                  opts={{ renderer: 'canvas' }}
                />
              </div>
            </Card>

            {/* 食物分类饼图 */}
            <Card title="食物分类占比" size="small">
              <div style={{ overflow: 'hidden' }}>
                <ReactECharts
                  option={categoryPieOption(stats, token.colorTextSecondary, isMobile)}
                  style={{ height: chartHeight }}
                  notMerge
                  theme={chartTheme}
                  opts={{ renderer: 'canvas' }}
                />
              </div>
            </Card>

            {/* 关注标签横向条 */}
            <Card title="关注标签频次（与上期对比）" size="small">
              {stats.watch_tags.length === 0 ? (
                <Empty description="本期无关注标签记录" />
              ) : (
                <>
                  <div style={{ overflow: 'hidden' }}>
                    <ReactECharts
                      option={watchTagBarOption(stats, token.colorPrimary, token.colorTextSecondary)}
                      style={{ height: Math.max(isMobile ? 140 : 160, stats.watch_tags.length * 36) }}
                      notMerge
                      theme={chartTheme}
                      opts={{ renderer: 'canvas' }}
                    />
                  </div>
                  <div style={{ overflowX: 'auto' }}>
                    <Table
                      size="small"
                      pagination={false}
                      dataSource={stats.watch_tags}
                      rowKey="code"
                      columns={[
                        { title: '标签', dataIndex: 'name', key: 'name' },
                        { title: '本期', dataIndex: 'count', key: 'count' },
                        { title: '上期', dataIndex: 'prev_count', key: 'prev_count' },
                        {
                          title: '变化',
                          key: 'delta',
                          render: (_, r) => delta(r.delta_vs_prev, token.colorPrimary, token.colorTextTertiary),
                        },
                      ]}
                      style={{ marginTop: 12, minWidth: 280 }}
                    />
                  </div>
                </>
              )}
            </Card>

            {/* 常吃食物 Top 8 */}
            <Card title="最常记录的食物 Top 8" size="small">
              {stats.top_items.length === 0 ? (
                <Empty description="暂无数据" />
              ) : (
                <div style={{ overflow: 'hidden' }}>
                  <ReactECharts
                    option={topItemsOption(stats, token.colorTextSecondary)}
                    style={{ height: Math.max(isMobile ? 140 : 160, stats.top_items.length * 32) }}
                    notMerge
                    theme={chartTheme}
                    opts={{ renderer: 'canvas' }}
                  />
                </div>
              )}
            </Card>

            {/* 每日估算热量柱图 */}
            {stats.daily.some((d) => d.kcal != null && (d.kcal ?? 0) > 0) && (
              <Card title="每日估算热量" size="small">
                <div style={{ overflow: 'hidden' }}>
                  <ReactECharts
                    option={dailyKcalOption(stats, token.colorPrimary, token.colorTextSecondary)}
                    style={{ height: chartHeight }}
                    notMerge
                    theme={chartTheme}
                    opts={{ renderer: 'canvas' }}
                  />
                </div>
                {stats.kcal_note && (
                  <div style={{ fontSize: 11, color: token.colorTextTertiary, marginTop: 6 }}>
                    {stats.kcal_note}
                  </div>
                )}
              </Card>
            )}

            {/* 各餐次热量占比甜甜圈 */}
            {stats.kcal_by_meal_type && stats.kcal_by_meal_type.some((m) => m.kcal > 0) && (
              <Card title="各餐次热量占比（估算）" size="small">
                <div style={{ overflow: 'hidden' }}>
                  <ReactECharts
                    option={kcalByMealTypeOption(stats, token.colorTextSecondary, isMobile)}
                    style={{ height: chartHeight }}
                    notMerge
                    theme={chartTheme}
                    opts={{ renderer: 'canvas' }}
                  />
                </div>
                {stats.kcal_note && (
                  <div style={{ fontSize: 11, color: token.colorTextTertiary, marginTop: 6 }}>
                    {stats.kcal_note}
                  </div>
                )}
              </Card>
            )}
          </div>

          {/* 来源统计 */}
          <div style={{ marginTop: 20, fontSize: 12, color: token.colorTextTertiary, textAlign: 'right' }}>
            数据来源：AI 识别{' '}
            <Tag color="blue" style={{ fontSize: 11 }}>
              {stats.item_sources.ai}
            </Tag>{' '}
            已修改{' '}
            <Tag color="orange" style={{ fontSize: 11 }}>
              {stats.item_sources.ai_edited}
            </Tag>{' '}
            手动{' '}
            <Tag color="default" style={{ fontSize: 11 }}>
              {stats.item_sources.user}
            </Tag>
          </div>
        </>
      )}
    </div>
  );
}

// ---- ECharts 选项构建 ----

function dailyChartOption(stats: StatsOut, colorPrimary: string, textColor: string): EChartsOption {
  const xData = stats.daily.map((d) => `${d.date.slice(5)}\n周${d.weekday}`);
  const hasWatchTags = stats.watch_tags.length > 0;

  const series: EChartsOption['series'] = [
    {
      name: '餐数',
      type: 'bar',
      data: stats.daily.map((d) => d.meals),
      itemStyle: { color: colorPrimary },
      yAxisIndex: 0,
    },
    ...stats.watch_tags.map((wt) => ({
      name: wt.name,
      type: 'line' as const,
      data: stats.daily.map((d) => Number(d[wt.code]) || 0),
      yAxisIndex: 1,
      smooth: false,
      connectNulls: true,
      symbol: 'circle',
      symbolSize: 4,
    })),
  ];

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', textStyle: { color: textColor } },
    legend: {
      type: 'scroll',
      bottom: 0,
      itemGap: 10,
      itemWidth: 14,
      textStyle: { fontSize: 11, color: textColor },
    },
    grid: { top: 24, left: 8, right: 8, bottom: hasWatchTags ? 60 : 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        interval: 0,
        rotate: xData.length > 7 ? 40 : 0,
        fontSize: 10,
        color: textColor,
        hideOverlap: true,
      },
    },
    yAxis: [
      { type: 'value', name: '餐数', minInterval: 1, axisLabel: { color: textColor } },
      { type: 'value', name: '次', minInterval: 1, axisLabel: { color: textColor } },
    ],
    series,
  };
}

function categoryPieOption(stats: StatsOut, textColor: string, isMobile: boolean): EChartsOption {
  const data = stats.category_share
    .filter((c) => c.count > 0)
    .map((c) => ({ name: c.category, value: c.count }));

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 项 ({d}%)',
    },
    legend: isMobile
      ? {
          type: 'scroll',
          orient: 'horizontal',
          bottom: 0,
          itemGap: 8,
          itemWidth: 14,
          textStyle: { fontSize: 10, color: textColor },
        }
      : {
          type: 'scroll',
          orient: 'vertical',
          left: 'left',
          itemGap: 10,
          itemWidth: 14,
          textStyle: { fontSize: 11, color: textColor },
        },
    series: [
      {
        type: 'pie',
        radius: isMobile ? ['34%', '58%'] : ['38%', '65%'],
        center: isMobile ? ['50%', '42%'] : ['62%', '50%'],
        avoidLabelOverlap: true,
        data,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 13, fontWeight: 'bold' },
        },
      },
    ],
  };
}

function watchTagBarOption(stats: StatsOut, colorPrimary: string, textColor: string): EChartsOption {
  const tags = [...stats.watch_tags].reverse();
  const names = tags.map((w) => w.name);
  const counts = tags.map((w) => w.count);
  const prevCounts = tags.map((w) => w.prev_count);

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number; value: number; seriesName: string }>;
        if (!arr.length) return '';
        const idx = arr[0].dataIndex;
        const wt = tags[idx];
        return [
          `${wt.name}`,
          ...arr.map((p) => `${p.seriesName}: ${p.value}`),
          `变化: ${wt.delta_vs_prev >= 0 ? '+' : ''}${wt.delta_vs_prev}`,
        ].join('<br/>');
      },
    },
    legend: {
      type: 'scroll',
      bottom: 0,
      itemGap: 10,
      itemWidth: 14,
      textStyle: { fontSize: 10, color: textColor },
    },
    grid: { top: 10, bottom: 44, left: 8, right: 8, containLabel: true },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: textColor } },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { fontSize: 11, color: textColor },
    },
    series: [
      {
        name: '本期',
        type: 'bar',
        data: counts,
        itemStyle: { color: colorPrimary },
        label: { show: true, position: 'right' },
      },
      {
        name: '上期',
        type: 'bar',
        data: prevCounts,
        itemStyle: { color: 'rgba(128,128,128,0.4)' },
      },
    ],
  };
}

function topItemsOption(stats: StatsOut, textColor: string): EChartsOption {
  const items = [...stats.top_items].reverse();
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: 10, bottom: 20, left: 8, right: 8, containLabel: true },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: textColor } },
    yAxis: {
      type: 'category',
      data: items.map((i) => i.name),
      axisLabel: { fontSize: 11, color: textColor },
    },
    series: [
      {
        type: 'bar',
        data: items.map((i) => i.count),
        itemStyle: { color: '#87ceeb' },
        label: { show: true, position: 'right' },
      },
    ],
  };
}

function dailyKcalOption(stats: StatsOut, colorPrimary: string, textColor: string): EChartsOption {
  const xData = stats.daily.map((d) => d.date.slice(5));
  const kcalData = stats.daily.map((d) => d.kcal ?? 0);
  const avgKcal = stats.kcal_avg_per_day ?? 0;

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const arr = params as Array<{ name: string; value: number }>;
        if (!arr.length) return '';
        return `${arr[0].name}<br/>≈ ${arr[0].value} kcal`;
      },
    },
    legend: { show: false },
    grid: { top: 24, left: 8, right: 8, bottom: 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: {
        interval: 0,
        rotate: xData.length > 7 ? 40 : 0,
        fontSize: 10,
        color: textColor,
        hideOverlap: true,
      },
    },
    yAxis: {
      type: 'value',
      name: 'kcal',
      axisLabel: { color: textColor },
    },
    series: [
      {
        name: '估算热量',
        type: 'bar',
        data: kcalData,
        itemStyle: { color: colorPrimary, borderRadius: [3, 3, 0, 0] },
        markLine: avgKcal > 0 ? {
          silent: true,
          lineStyle: { type: 'dashed', color: 'rgba(128,128,128,0.6)' },
          data: [{ type: 'average', name: '均值' }],
          label: { formatter: `均 ${Math.round(avgKcal)} kcal`, fontSize: 10 },
        } : undefined,
      },
    ],
  };
}

function kcalByMealTypeOption(stats: StatsOut, textColor: string, isMobile: boolean): EChartsOption {
  const data = (stats.kcal_by_meal_type ?? [])
    .filter((m) => m.kcal > 0)
    .map((m) => ({ name: m.meal_type, value: m.kcal }));

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} kcal ({d}%)',
    },
    legend: isMobile
      ? {
          type: 'scroll',
          orient: 'horizontal',
          bottom: 0,
          itemGap: 8,
          itemWidth: 14,
          textStyle: { fontSize: 10, color: textColor },
        }
      : {
          type: 'scroll',
          orient: 'vertical',
          left: 'left',
          itemGap: 10,
          itemWidth: 14,
          textStyle: { fontSize: 11, color: textColor },
        },
    series: [
      {
        type: 'pie',
        radius: isMobile ? ['34%', '58%'] : ['38%', '62%'],
        center: isMobile ? ['50%', '42%'] : ['62%', '50%'],
        avoidLabelOverlap: true,
        data,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 13, fontWeight: 'bold' },
        },
      },
    ],
  };
}

import { useEffect, useState, type ReactNode } from 'react';
import { Modal, Steps, Typography, theme as antdTheme, Button } from 'antd';
import {
  CameraOutlined,
  HeartOutlined,
  SearchOutlined,
  BellOutlined,
  SafetyOutlined,
  RocketOutlined,
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

const ONBOARD_KEY = 'dd_onboarded_v081';
export const OPEN_ONBOARDING_EVENT = 'dd:open-onboarding';

interface StepDef {
  title: string;
  icon: ReactNode;
  emoji: string;
  heading: string;
  body: string[];
  tip?: string;
}

const STEPS: StepDef[] = [
  {
    title: '记录一餐',
    icon: <CameraOutlined />,
    emoji: '📷',
    heading: '拍照就能记，不用手敲',
    body: [
      '在「记录」页拍下或上传一顿饭，AI 会自动识别菜品、估算营养。',
      '识别结果可以手动增删改，确认后一键保存。',
    ],
    tip: '安卓端也可直接调用系统相机，拍完自动回传。',
  },
  {
    title: '健康餐单',
    icon: <HeartOutlined />,
    emoji: '🍱',
    heading: '按你的体质给一周吃法',
    body: [
      '在「健康」页完善身高体重、体质与目标，AI 生成 7 天个性化餐单。',
      '不满意某顿？点「换一换」让 AI 重做，或一键应用替换建议。',
    ],
    tip: '餐单仅供饮食参考，不构成医疗诊断。',
  },
  {
    title: '自然语言查询',
    icon: <SearchOutlined />,
    emoji: '🔍',
    heading: '用大白话问，不用记报表',
    body: [
      '在「查询」页直接问："我这周吃几次火锅？""最近蛋白质够吗？"',
      'AI 会读懂你的问题，从已记录的数据里给出答案。',
    ],
  },
  {
    title: '通知提醒',
    icon: <BellOutlined />,
    emoji: '🔔',
    heading: '到点提醒，别饿过头',
    body: [
      '在「通知」页设置三餐提醒时间，应用会按时提醒你吃饭。',
      '提醒可单独开关，不打扰你的作息。',
    ],
  },
  {
    title: '数据与隐私',
    icon: <SafetyOutlined />,
    emoji: '🔒',
    heading: '你的数据，你做主',
    body: [
      '所有饮食记录存在你的账户下，可在「数据与集成」导出或备份。',
      '模型密钥只保存在后端，前端看不到明文。',
    ],
    tip: '想重看本教程？在「我的」页底部点「新手教程」即可。',
  },
];

export default function OnboardingTutorial() {
  const { token } = antdTheme.useToken();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    try {
      if (localStorage.getItem(ONBOARD_KEY) !== '1') {
        setOpen(true);
      }
    } catch {
      setOpen(true);
    }
    const onOpen = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener(OPEN_ONBOARDING_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ONBOARDING_EVENT, onOpen);
  }, []);

  const finish = () => {
    try {
      localStorage.setItem(ONBOARD_KEY, '1');
    } catch {
      /* ignore */
    }
    setOpen(false);
  };

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <Modal
      open={open}
      onCancel={finish}
      footer={null}
      width={460}
      destroyOnClose
      styles={{ body: { paddingTop: 8 } }}
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <RocketOutlined style={{ color: token.colorPrimary }} />
          <span>欢迎使用「今天吃得怎么样」</span>
        </div>
      }
    >
      <Steps
        current={step}
        size="small"
        direction="horizontal"
        style={{ marginBottom: 16 }}
        items={STEPS.map((s) => ({ title: s.title, icon: s.icon }))}
      />

      <div
        style={{
          background: token.colorFillSecondary,
          borderRadius: 12,
          padding: '18px 16px',
          textAlign: 'center',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 40, lineHeight: 1 }}>{current.emoji}</div>
        <Title level={5} style={{ margin: '10px 0 4px' }}>{current.heading}</Title>
      </div>

      <Paragraph style={{ fontSize: 13, marginBottom: current.tip ? 8 : 0 }}>
        {current.body.map((b, i) => (
          <div key={i} style={{ marginBottom: 4 }}>· {b}</div>
        ))}
      </Paragraph>
      {current.tip && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          💡 {current.tip}
        </Text>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 18 }}>
        <Button onClick={finish}>跳过</Button>
        <div style={{ display: 'flex', gap: 8 }}>
          {step > 0 && <Button onClick={() => setStep((s) => s - 1)}>上一步</Button>}
          {isLast ? (
            <Button type="primary" onClick={finish}>开始使用</Button>
          ) : (
            <Button type="primary" onClick={() => setStep((s) => s + 1)}>下一步</Button>
          )}
        </div>
      </div>
    </Modal>
  );
}

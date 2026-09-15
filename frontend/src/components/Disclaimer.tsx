import { Typography } from 'antd';

const { Text } = Typography;

interface DisclaimerProps {
  text?: string;
}

const DEFAULT =
  '识别与估算可能有误，本应用不提供医疗诊断或精确营养数据，仅帮助你观察饮食结构。';

export default function Disclaimer({ text }: DisclaimerProps) {
  return (
    <div style={{ marginTop: 24, textAlign: 'center' }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        ⚠ {text ?? DEFAULT}
      </Text>
    </div>
  );
}

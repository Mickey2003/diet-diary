import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Form, Input, Result, Typography, theme as antdTheme } from 'antd';
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons';
import { login, loginTotp, register, getAuthStatus } from '../api/auth';

const { Title, Text } = Typography;

interface Props {
  onSuccess: (username: string, displayName?: string | null, isAdmin?: boolean) => void;
}

type Step = 'password' | 'totp' | 'register' | 'pending_approval';

export default function LoginPage({ onSuccess }: Props) {
  const { token } = antdTheme.useToken();
  const [step, setStep] = useState<Step>('password');
  const [pendingToken, setPendingToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowRegistration, setAllowRegistration] = useState(false);
  const [requireApproval, setRequireApproval] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((s) => {
        if (s.allow_registration) setAllowRegistration(true);
        if (s.require_approval) setRequireApproval(true);
      })
      .catch(() => {/* ignore */});
  }, []);

  async function notifySuccess(username: string) {
    try {
      const s = await getAuthStatus();
      onSuccess(s.username ?? username, s.display_name, !!s.is_admin);
    } catch {
      onSuccess(username);
    }
  }

  async function handlePassword(values: { username: string; password: string; remember?: boolean }) {
    setLoading(true);
    setError(null);
    try {
      const res = await login(values.username.trim(), values.password, !!values.remember);
      if (res.need_totp && res.pending_token) {
        setPendingToken(res.pending_token);
        setStep('totp');
      } else if (res.username) {
        await notifySuccess(res.username);
      }
    } catch (e: unknown) {
      setError(extractDetail(e) ?? '登录失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleTotp(values: { code: string }) {
    setLoading(true);
    setError(null);
    try {
      const res = await loginTotp(pendingToken, values.code.trim());
      if (res.username) await notifySuccess(res.username);
    } catch (e: unknown) {
      setError(extractDetail(e) ?? '验证失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(values: {
    username: string;
    password: string;
    confirm: string;
    display_name?: string;
  }) {
    if (values.password !== values.confirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await register(
        values.username.trim(),
        values.password,
        values.display_name?.trim() || undefined,
      );
      if (result.pending_approval) {
        // User registered but needs admin approval — do NOT log in
        setStep('pending_approval');
      } else {
        await notifySuccess(values.username.trim());
      }
    } catch (e: unknown) {
      setError(extractDetail(e) ?? '注册失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        {/* App icon badge */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: '50%',
              background: token.colorPrimaryBg,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 32,
              marginBottom: 14,
            }}
          >
            🍱
          </div>
          <Title level={3} style={{ margin: 0, lineHeight: 1.2 }}>今天吃得怎么样</Title>
          <Text type="secondary" style={{ fontSize: 13, marginTop: 4, display: 'block' }}>
            AI 饮食观察日记 · {step === 'register' ? '注册账号' : step === 'pending_approval' ? '注册成功' : '请登录'}
          </Text>
        </div>

        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

        {step === 'password' && (
          <Form layout="vertical" onFinish={handlePassword} initialValues={{ remember: true }}>
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input
                size="large"
                prefix={<UserOutlined />}
                placeholder="用户名"
                autoComplete="username"
                autoFocus
              />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 16 }}>
              <Checkbox>30 天内记住我</Checkbox>
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{ height: 44, fontSize: 15 }}
            >
              登录
            </Button>
            {allowRegistration && (
              <Button
                type="link"
                block
                style={{ marginTop: 8 }}
                onClick={() => { setStep('register'); setError(null); }}
              >
                注册新账号
              </Button>
            )}
            <div style={{ marginTop: 16, fontSize: 12, color: token.colorTextTertiary, lineHeight: 1.6 }}>
              首次使用：初始密码在服务器 <code>backend/data/initial_password.txt</code>，
              或由 <code>.env</code> 中的 <code>ADMIN_PASSWORD</code> 指定。登录后请尽快修改密码并开启两步验证。
            </div>
          </Form>
        )}

        {step === 'totp' && (
          <Form layout="vertical" onFinish={handleTotp}>
            <Alert
              type="info"
              showIcon
              icon={<SafetyOutlined />}
              message="两步验证"
              description="请输入验证器 App 中的 6 位动态码，或使用一个备用码（格式 0000-0000）。"
              style={{ marginBottom: 16 }}
            />
            <Form.Item name="code" rules={[{ required: true, message: '请输入验证码' }]}>
              <Input
                size="large"
                placeholder="6 位验证码或备用码"
                autoComplete="one-time-code"
                autoFocus
                maxLength={12}
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{ height: 44, fontSize: 15 }}
            >
              验证并登录
            </Button>
            <Button type="link" block onClick={() => { setStep('password'); setError(null); }}>
              返回重新输入密码
            </Button>
          </Form>
        )}

        {step === 'register' && (
          <Form layout="vertical" onFinish={handleRegister}>
            <Form.Item
              name="username"
              label="用户名"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 2, message: '至少 2 个字符' },
              ]}
            >
              <Input
                size="large"
                prefix={<UserOutlined />}
                placeholder="用户名（至少 2 个字符）"
                autoComplete="username"
                autoFocus
              />
            </Form.Item>
            <Form.Item name="display_name" label="显示名（可选）">
              <Input size="large" placeholder="昵称" autoComplete="name" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 8, message: '至少 8 位' },
              ]}
            >
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="至少 8 位"
                autoComplete="new-password"
              />
            </Form.Item>
            <Form.Item
              name="confirm"
              label="确认密码"
              rules={[{ required: true, message: '请再次输入密码' }]}
            >
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="再次输入密码"
                autoComplete="new-password"
              />
            </Form.Item>
            {requireApproval && (
              <Alert
                type="info"
                showIcon
                message="注册后需管理员审核通过才能登录"
                style={{ marginBottom: 16 }}
              />
            )}
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{ height: 44, fontSize: 15 }}
            >
              注册并登录
            </Button>
            <Button type="link" block onClick={() => { setStep('password'); setError(null); }}>
              已有账号，去登录
            </Button>
          </Form>
        )}

        {step === 'pending_approval' && (
          <Result
            status="success"
            title="注册成功，等待管理员审核"
            subTitle="您的账号已提交，管理员审核通过后您即可登录使用。"
            extra={[
              <Button
                key="back"
                type="primary"
                onClick={() => { setStep('password'); setError(null); }}
              >
                返回登录
              </Button>,
            ]}
          />
        )}
      </div>
    </div>
  );
}

function extractDetail(e: unknown): string | null {
  if (typeof e === 'object' && e !== null) {
    const err = e as { response?: { data?: { detail?: unknown } } };
    const d = err.response?.data?.detail;
    if (typeof d === 'string') return d;
  }
  return null;
}

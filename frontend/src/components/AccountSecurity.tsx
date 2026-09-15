import { useEffect, useState } from 'react';
import { Alert, Button, Divider, Form, Input, Modal, Space, Tag, Typography, message } from 'antd';
import { KeyOutlined, LogoutOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import {
  changePassword,
  getMe,
  logout,
  logoutAll,
  regenerateBackupCodes,
  totpDisable,
  totpEnable,
  totpSetup,
  type MeOut,
  type TotpSetupOut,
} from '../api/auth';

const { Text, Paragraph } = Typography;

interface Props {
  onLoggedOut: () => void;
}

/** 账户与安全：修改密码、两步验证（TOTP）、备用码、退出登录。 */
export default function AccountSecurity({ onLoggedOut }: Props) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<TotpSetupOut | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [pwForm] = Form.useForm();
  const [setupForm] = Form.useForm();
  const [enableForm] = Form.useForm();
  const [disableForm] = Form.useForm();

  const load = () => getMe().then(setMe).catch(() => {/* 忽略 */});
  useEffect(() => { load(); }, []);

  async function onChangePassword(v: { current: string; next: string; confirm: string }) {
    if (v.next !== v.confirm) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await changePassword(v.current, v.next);
      message.success('密码已修改，其他设备已下线');
      pwForm.resetFields();
      load();
    } finally {
      setBusy(false);
    }
  }

  async function onSetup(v: { password: string }) {
    setBusy(true);
    try {
      setSetup(await totpSetup(v.password));
      setupForm.resetFields();
    } finally {
      setBusy(false);
    }
  }

  async function onEnable(v: { code: string }) {
    setBusy(true);
    try {
      const res = await totpEnable(v.code.trim());
      setBackupCodes(res.backup_codes);
      setSetup(null);
      enableForm.resetFields();
      message.success('两步验证已开启');
      load();
    } finally {
      setBusy(false);
    }
  }

  async function onDisable(v: { password: string; code: string }) {
    setBusy(true);
    try {
      await totpDisable(v.password, v.code.trim());
      message.success('两步验证已关闭');
      disableForm.resetFields();
      load();
    } finally {
      setBusy(false);
    }
  }

  async function onRegenerate() {
    let pw = '';
    Modal.confirm({
      title: '重新生成备用码',
      content: (
        <div>
          <Paragraph type="secondary">旧的备用码将全部失效。请输入密码确认：</Paragraph>
          <Input.Password onChange={(e) => { pw = e.target.value; }} placeholder="当前密码" />
        </div>
      ),
      onOk: async () => {
        const res = await regenerateBackupCodes(pw);
        setBackupCodes(res.backup_codes);
        load();
      },
    });
  }

  async function onLogout(all: boolean) {
    setBusy(true);
    try {
      if (all) await logoutAll(); else await logout();
      onLoggedOut();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content-card settings-form">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <Text strong style={{ fontSize: 16 }}>账户与安全</Text>
          {me && (
            <div style={{ fontSize: 12, color: 'var(--dd-text-secondary)', marginTop: 4 }}>
              当前用户 <Tag>{me.username}</Tag>
              两步验证 {me.totp_enabled ? <Tag color="green">已开启</Tag> : <Tag color="orange">未开启</Tag>}
              活动会话 {me.sessions} 个
              {me.totp_enabled && <>，剩余备用码 {me.backup_codes_left} 个</>}
            </div>
          )}
        </div>
        <Space>
          <Button icon={<LogoutOutlined />} onClick={() => onLogout(false)} loading={busy}>退出登录</Button>
          <Button danger onClick={() => onLogout(true)} loading={busy}>所有设备下线</Button>
        </Space>
      </div>

      {!me?.totp_enabled && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message="服务已暴露在公网时，强烈建议开启两步验证"
          description="开启后登录需要密码 + 手机验证器动态码，即使密码泄露也难以被登录。"
        />
      )}

      <Divider orientation="left" plain><KeyOutlined /> 修改密码</Divider>
      <Form form={pwForm} layout="vertical" onFinish={onChangePassword}>
        <Form.Item name="current" label="当前密码" rules={[{ required: true }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          <Form.Item name="next" label="新密码（至少 8 位）" rules={[{ required: true, min: 8, message: '至少 8 位' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </div>
        <Button type="primary" htmlType="submit" loading={busy}>修改密码</Button>
      </Form>

      <Divider orientation="left" plain><SafetyCertificateOutlined /> 两步验证（TOTP）</Divider>
      {me && !me.totp_enabled && !setup && (
        <Form form={setupForm} layout="inline" onFinish={onSetup}>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="输入当前密码以生成二维码" style={{ width: 240 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>生成二维码</Button>
        </Form>
      )}
      {setup && (
        <div>
          <Paragraph>
            1. 用 <b>Google Authenticator</b>、<b>Microsoft Authenticator</b>、<b>Authy</b> 或支持 TOTP 的密码管理器扫描下方二维码；
            2. 输入 App 显示的 6 位动态码完成绑定。
          </Paragraph>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <img src={setup.qr_data_url} alt="TOTP 二维码" width={180} height={180} style={{ border: '1px solid var(--dd-border)', borderRadius: 8 }} />
            <div style={{ flex: 1, minWidth: 220 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>无法扫码时手动输入密钥：</Text>
              <Paragraph copyable code style={{ wordBreak: 'break-all' }}>{setup.secret}</Paragraph>
              <Form form={enableForm} layout="inline" onFinish={onEnable}>
                <Form.Item name="code" rules={[{ required: true, message: '请输入 6 位验证码' }]}>
                  <Input placeholder="6 位动态码" maxLength={6} style={{ width: 140 }} autoComplete="one-time-code" />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={busy}>确认开启</Button>
                <Button type="link" onClick={() => setSetup(null)}>取消</Button>
              </Form>
            </div>
          </div>
        </div>
      )}
      {me?.totp_enabled && (
        <div>
          <Space wrap style={{ marginBottom: 12 }}>
            <Button onClick={onRegenerate}>重新生成备用码</Button>
          </Space>
          <Form form={disableForm} layout="inline" onFinish={onDisable}>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password placeholder="当前密码" style={{ width: 180 }} />
            </Form.Item>
            <Form.Item name="code" rules={[{ required: true, message: '请输入验证码' }]}>
              <Input placeholder="动态码或备用码" style={{ width: 160 }} />
            </Form.Item>
            <Button danger htmlType="submit" loading={busy}>关闭两步验证</Button>
          </Form>
        </div>
      )}

      <Modal
        open={!!backupCodes}
        title="请妥善保存备用码（只显示这一次）"
        onOk={() => setBackupCodes(null)}
        onCancel={() => setBackupCodes(null)}
        cancelButtonProps={{ style: { display: 'none' } }}
        okText="我已保存"
      >
        <Paragraph type="secondary">手机丢失或无法获取动态码时，每个备用码可使用一次。</Paragraph>
        <Paragraph copyable={{ text: (backupCodes ?? []).join('\n') }}>
          <pre style={{ fontSize: 15, lineHeight: 1.8, margin: 0 }}>{(backupCodes ?? []).join('\n')}</pre>
        </Paragraph>
      </Modal>
    </div>
  );
}

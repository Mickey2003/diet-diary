import { useEffect, useState, useCallback } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
  theme as antdTheme,
} from 'antd';
import { UserAddOutlined, LockOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { listAdminUsers, createAdminUser, patchAdminUser, deleteAdminUser, approveAdminUser } from '../api/admin';
import type { AdminUserOut } from '../api/admin';
import { useAuth } from '../auth/AuthContext';
import client from '../api/client';
import PageHeader from '../components/PageHeader';

const { Text } = Typography;

interface RegistrationSettings {
  allow_registration: boolean;
  require_approval: boolean;
  pending_count: number;
}

export default function AdminUsersPage() {
  const { isAdmin, username: currentUsername } = useAuth();
  const { token } = antdTheme.useToken();

  const [users, setUsers] = useState<AdminUserOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [resetPwOpen, setResetPwOpen] = useState<AdminUserOut | null>(null);
  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();
  const [allowReg, setAllowReg] = useState(false);
  const [requireApproval, setRequireApproval] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [regLoading, setRegLoading] = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [filter, setFilter] = useState<'all' | 'pending'>('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listAdminUsers();
      setUsers(list);
    } catch {
      /* error shown by interceptor */
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRegSettings = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const r = await client.get<RegistrationSettings>('/api/admin/users/registration');
      setAllowReg(r.data.allow_registration);
      setRequireApproval(r.data.require_approval);
      setPendingCount(r.data.pending_count ?? 0);
    } catch {/* ignore */}
  }, [isAdmin]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRegSettings(); }, [loadRegSettings]);

  async function handleToggleReg(checked: boolean) {
    setRegLoading(true);
    try {
      await client.put('/api/admin/users/registration', { allow_registration: checked });
      setAllowReg(checked);
      message.success(checked ? '已开放自主注册' : '已关闭自主注册');
    } catch {
      /* error shown by interceptor */
    } finally {
      setRegLoading(false);
    }
  }

  async function handleToggleApproval(checked: boolean) {
    setApprovalLoading(true);
    try {
      await client.put('/api/admin/users/registration', { require_approval: checked });
      setRequireApproval(checked);
      message.success(checked ? '已开启注册审核' : '已关闭注册审核');
    } catch {
      /* error shown by interceptor */
    } finally {
      setApprovalLoading(false);
    }
  }

  if (!isAdmin) {
    return (
      <div>
        <div className="page-title">用户管理</div>
        <Alert
          type="error"
          showIcon
          message="403 禁止访问"
          description="此页面仅管理员可见。"
        />
      </div>
    );
  }

  async function handleCreate(values: {
    username: string;
    display_name?: string;
    password: string;
    role: string;
  }) {
    try {
      await createAdminUser({
        username: values.username.trim(),
        password: values.password,
        role: values.role,
        display_name: values.display_name?.trim() || undefined,
      });
      message.success('用户已创建');
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleResetPw(values: { new_password: string }) {
    if (!resetPwOpen) return;
    try {
      await patchAdminUser(resetPwOpen.id, { new_password: values.new_password });
      message.success('密码已重置，该用户其他会话已下线');
      setResetPwOpen(null);
      resetForm.resetFields();
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleToggleActive(user: AdminUserOut, checked: boolean) {
    try {
      await patchAdminUser(user.id, { is_active: checked });
      message.success(checked ? '账户已启用' : '账户已停用');
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleResetTotp(user: AdminUserOut) {
    try {
      await patchAdminUser(user.id, { reset_totp: true });
      message.success('两步验证已重置');
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleRoleChange(user: AdminUserOut, role: string) {
    try {
      await patchAdminUser(user.id, { role });
      message.success('角色已更新');
      load();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleDelete(user: AdminUserOut) {
    try {
      await deleteAdminUser(user.id);
      message.success('用户已删除');
      setPendingCount((p) => (user.is_approved === false ? Math.max(0, p - 1) : p));
      load();
      loadRegSettings();
    } catch {
      /* error shown by interceptor */
    }
  }

  async function handleApprove(user: AdminUserOut) {
    try {
      await approveAdminUser(user.id);
      message.success(`已通过 ${user.username} 的注册申请`);
      setPendingCount((p) => Math.max(0, p - 1));
      load();
      loadRegSettings();
    } catch {
      /* error shown by interceptor */
    }
  }

  const isSelf = (u: AdminUserOut) => u.username === currentUsername;

  const filteredUsers = filter === 'pending'
    ? users.filter((u) => u.is_approved === false)
    : users;

  return (
    <div>
      <PageHeader title="用户管理" subtitle="账号、角色与注册开关" />
      <div className="page-title">用户管理</div>

      {/* Registration setting */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Switch
              checked={allowReg}
              loading={regLoading}
              onChange={handleToggleReg}
            />
            <div>
              <Text strong>开放用户自主注册</Text>
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                开启后，登录页面将显示「注册新账号」入口
              </Text>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Switch
              checked={requireApproval}
              loading={approvalLoading}
              onChange={handleToggleApproval}
            />
            <div>
              <Text strong>新注册账号需管理员审核</Text>
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                开启后新注册用户需在此处通过审核才能登录（默认开启）
              </Text>
            </div>
            {pendingCount > 0 && (
              <Badge
                count={pendingCount}
                style={{ backgroundColor: '#fa8c16' }}
              >
                <Tag color="orange" style={{ cursor: 'pointer' }} onClick={() => setFilter('pending')}>
                  待审核 {pendingCount}
                </Tag>
              </Badge>
            )}
          </div>
        </div>
      </Card>

      <div
        style={{
          background: token.colorBgContainer,
          borderRadius: 10,
          padding: '16px 20px',
          marginBottom: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <Space wrap>
          <Text type="secondary">共 {users.length} 个用户</Text>
          <Segmented
            value={filter}
            onChange={(v) => setFilter(v as 'all' | 'pending')}
            options={[
              { label: '全部', value: 'all' },
              {
                label: pendingCount > 0
                  ? <span>待审核 <Badge count={pendingCount} size="small" style={{ backgroundColor: '#fa8c16' }} /></span>
                  : '待审核',
                value: 'pending',
              },
            ]}
          />
        </Space>
        <Button
          type="primary"
          icon={<UserAddOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          新建用户
        </Button>
      </div>

      {/* User card list (mobile-friendly) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {loading && filteredUsers.length === 0 && (
          <Text type="secondary" style={{ textAlign: 'center', padding: 24, display: 'block' }}>加载中…</Text>
        )}
        {filteredUsers.map((u) => {
          const self = isSelf(u);
          const isPending = u.is_approved === false;
          return (
            <Card
              key={u.id}
              size="small"
              style={{
                borderRadius: 10,
                borderLeft: isPending ? `3px solid #fa8c16` : undefined,
              }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <Text strong>{u.username}</Text>
                {u.display_name && <Text type="secondary">{u.display_name}</Text>}
                {self && <Tag color="blue">自己</Tag>}
                {isPending && <Tag color="orange" style={{ fontWeight: 600 }}>待审核</Tag>}
                <Tag color={u.role === 'admin' ? 'red' : 'default'}>{u.role === 'admin' ? '管理员' : '普通用户'}</Tag>
                <Tag color={u.is_active ? 'green' : 'default'}>{u.is_active ? '已启用' : '已停用'}</Tag>
                {u.totp_enabled && <Tag color="green">两步验证</Tag>}
              </div>
              <div style={{ fontSize: 12, color: token.colorTextTertiary, marginBottom: 10 }}>
                注册时间：{dayjs(u.created_at).format('MM-DD HH:mm')} · 餐食数：{u.meal_count}
              </div>
              <Space wrap size={6}>
                {isPending && (
                  <>
                    <Button
                      size="small"
                      type="primary"
                      icon={<CheckOutlined />}
                      disabled={self}
                      onClick={() => handleApprove(u)}
                    >
                      通过
                    </Button>
                    <Popconfirm
                      title={`确定拒绝并删除用户 ${u.username}？`}
                      onConfirm={() => handleDelete(u)}
                    >
                      <Button size="small" danger icon={<CloseOutlined />} disabled={self}>拒绝</Button>
                    </Popconfirm>
                  </>
                )}
                <Select
                  size="small"
                  value={u.role}
                  disabled={self}
                  options={[
                    { label: '管理员', value: 'admin' },
                    { label: '普通用户', value: 'user' },
                  ]}
                  onChange={(v) => handleRoleChange(u, v)}
                  style={{ width: 110 }}
                />
                <Switch
                  size="small"
                  checked={u.is_active}
                  disabled={self}
                  onChange={(v) => handleToggleActive(u, v)}
                  checkedChildren="启用"
                  unCheckedChildren="停用"
                />
                <Button
                  size="small"
                  icon={<LockOutlined />}
                  disabled={self}
                  onClick={() => { setResetPwOpen(u); resetForm.resetFields(); }}
                >
                  重置密码
                </Button>
                {u.totp_enabled && (
                  <Popconfirm
                    title={`确定重置 ${u.username} 的两步验证？`}
                    onConfirm={() => handleResetTotp(u)}
                  >
                    <Button size="small" disabled={self}>重置两步验证</Button>
                  </Popconfirm>
                )}
                {!isPending && (
                  <Popconfirm
                    title={`确定删除用户 ${u.username}？此操作不可撤销，将删除其全部数据。`}
                    onConfirm={() => handleDelete(u)}
                  >
                    <Button size="small" danger disabled={self}>删除</Button>
                  </Popconfirm>
                )}
              </Space>
            </Card>
          );
        })}
      </div>

      {/* Create user modal */}
      <Modal
        open={createOpen}
        title="新建用户"
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
        okText="创建"
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input placeholder="用户名（字母、数字、下划线）" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名（可选）">
            <Input placeholder="昵称" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="user">
            <Select
              options={[
                { label: '普通用户', value: 'user' },
                { label: '管理员', value: 'admin' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Reset password modal */}
      <Modal
        open={!!resetPwOpen}
        title={`重置密码：${resetPwOpen?.username}`}
        onCancel={() => { setResetPwOpen(null); resetForm.resetFields(); }}
        onOk={() => resetForm.submit()}
        okText="重置"
        destroyOnClose
      >
        <Form form={resetForm} layout="vertical" onFinish={handleResetPw}>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
            ]}
          >
            <Input.Password placeholder="至少 8 位" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

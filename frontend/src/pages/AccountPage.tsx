import AccountSecurity from '../components/AccountSecurity';

interface Props {
  onLoggedOut: () => void;
}

export default function AccountPage({ onLoggedOut }: Props) {
  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div className="page-title">账户与安全</div>
      <AccountSecurity onLoggedOut={onLoggedOut} />
    </div>
  );
}

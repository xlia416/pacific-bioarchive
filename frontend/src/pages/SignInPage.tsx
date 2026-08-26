import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { signIn } from '../auth/cognito';

export function SignInPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [challenge, setChallenge] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await signIn(form.email, form.password, () => setChallenge(true));
      navigate('/');
    } catch (err: any) {
      setError(err?.message ?? '登录失败');
    }
  };

  const forceReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      // 临时密码登录后要求改密：这里先记录，落地时用 respondToNewPassword
      alert(`改密为 ${newPassword.length} 位（TODO: respondToNewPassword 落地）`);
      setChallenge(false);
      navigate('/');
    } catch (err: any) {
      setError(err?.message ?? '改密失败');
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>登录</h1>
        {!challenge ? (
          <form onSubmit={submit}>
            <input placeholder="邮箱" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <input type="password" placeholder="密码" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            {error && <div className="error">{error}</div>}
            <button type="submit">登录</button>
          </form>
        ) : (
          <form onSubmit={forceReset}>
            <p className="muted">首次登录需设置新密码</p>
            <input type="password" placeholder="新密码" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
            {error && <div className="error">{error}</div>}
            <button type="submit">设置密码</button>
          </form>
        )}
        <p className="muted">
          还没账号？<Link to="/signup">去注册</Link>
        </p>
      </div>
    </div>
  );
}
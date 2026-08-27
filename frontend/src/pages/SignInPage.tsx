import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { completeNewPassword, signIn, startGoogleSignIn } from '../auth/cognito';
import { config } from '../config';

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
      await completeNewPassword(newPassword);
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
        {config.GOOGLE_IDP_ENABLED && <>
          <div className="divider"><span>或</span></div>
          <button className="secondary full" type="button" onClick={() => void startGoogleSignIn().catch((err) => setError(err.message))}>
            使用 Google 登录
          </button>
        </>}
      </div>
    </div>
  );
}

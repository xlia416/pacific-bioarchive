import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { signUp, confirmSignUp } from '../auth/cognito';

export function SignUpPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', givenName: '', familyName: '', password: '' });
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await signUp(form.email, form.password, form.givenName, form.familyName);
      setNeedsCode(true);
    } catch (err: any) {
      setError(err?.message ?? '注册失败');
    }
  };

  const confirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await confirmSignUp(form.email, code);
      navigate('/signin');
    } catch (err: any) {
      setError(err?.message ?? '验证失败');
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>Pacific BioArchive</h1>
        <p className="muted">注册以使用 ✔（未登录访问将重定向到这里）</p>
        {!needsCode ? (
          <form onSubmit={submit}>
            <input placeholder="邮箱" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <input placeholder="名" value={form.givenName} onChange={(e) => setForm({ ...form, givenName: e.target.value })} required />
            <input placeholder="姓" value={form.familyName} onChange={(e) => setForm({ ...form, familyName: e.target.value })} required />
            <input type="password" placeholder="密码" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">注册</button>
          </form>
        ) : (
          <form onSubmit={confirm}>
            <p className="muted">验证码已发到 {form.email}</p>
            <input placeholder="6 位验证码" value={code} onChange={(e) => setCode(e.target.value)} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">确认注册</button>
          </form>
        )}
        <p className="muted">
          已有账号？<Link to="/signin">去登录</Link>
        </p>
      </div>
    </div>
  );
}

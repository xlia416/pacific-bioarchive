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
      setError(err?.message ?? 'Registration failed');
    }
  };

  const confirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await confirmSignUp(form.email, code);
      navigate('/signin');
    } catch (err: any) {
      setError(err?.message ?? 'Verification failed');
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>Pacific BioArchive</h1>
        <p className="muted">Create an account to access the protected wildlife archive.</p>
        {!needsCode ? (
          <form onSubmit={submit}>
            <input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <input placeholder="Given name" value={form.givenName} onChange={(e) => setForm({ ...form, givenName: e.target.value })} required />
            <input placeholder="Family name" value={form.familyName} onChange={(e) => setForm({ ...form, familyName: e.target.value })} required />
            <input type="password" placeholder="Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">Create account</button>
          </form>
        ) : (
          <form onSubmit={confirm}>
            <p className="muted">We sent a verification code to {form.email}</p>
            <input placeholder="6-digit verification code" value={code} onChange={(e) => setCode(e.target.value)} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">Verify account</button>
          </form>
        )}
        <p className="muted">
          Already registered? <Link to="/signin">Sign in</Link>
        </p>
      </div>
    </div>
  );
}

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
      setError(err?.message ?? 'Sign in failed');
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
      setError(err?.message ?? 'Password update failed');
    }
  };

  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>Sign in</h1>
        {!challenge ? (
          <form onSubmit={submit}>
            <input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <input type="password" placeholder="Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">Sign in</button>
          </form>
        ) : (
          <form onSubmit={forceReset}>
            <p className="muted">Set a new password to complete your first sign-in.</p>
            <input type="password" placeholder="New password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
            {error && <div className="error">{error}</div>}
            <button className="full" type="submit">Set password</button>
          </form>
        )}
        <p className="muted">
          New here? <Link to="/signup">Create an account</Link>
        </p>
        {config.GOOGLE_IDP_ENABLED && <>
          <div className="divider"><span>or</span></div>
          <button className="secondary full" type="button" onClick={() => void startGoogleSignIn().catch((err) => setError(err.message))}>
            Continue with Google
          </button>
        </>}
      </div>
    </div>
  );
}

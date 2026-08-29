import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { completeOAuthCallback } from '../auth/cognito';

export function OAuthCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState('');
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const oauthError = params.get('error_description') || params.get('error');
    if (oauthError || !code) { setError(oauthError || 'Missing OAuth authorization code'); return; }
    completeOAuthCallback(code, params.get('state')).then(() => navigate('/', { replace: true }))
      .catch((err) => setError(err?.message || 'Google sign-in failed'));
  }, [navigate]);
  return <div className="splash">{error ? <span className="error">{error}</span> : <><span className="spinner" /> Completing Google sign-in…</>}</div>;
}

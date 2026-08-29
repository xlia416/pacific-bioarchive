import { CognitoUser, CognitoUserPool, CognitoUserAttribute, AuthenticationDetails } from 'amazon-cognito-identity-js';
import type { CognitoUserSession } from 'amazon-cognito-identity-js';
import { config } from '../config';

const poolData = {
  UserPoolId: config.USER_POOL_ID,
  ClientId: config.USER_POOL_CLIENT_ID,
};
const userPool = new CognitoUserPool(poolData);
let challengedUser: CognitoUser | null = null;
const OAUTH_ACCESS_TOKEN = 'pba.oauth.accessToken';
const OAUTH_CODE_VERIFIER = 'pba.oauth.codeVerifier';
const OAUTH_STATE = 'pba.oauth.state';

function currentUser() {
  return userPool.getCurrentUser();
}

/** 拿到当前登录用户的 access token（去调用受保护 API）。Cognito 内部用 localStorage，无需额外 polyfill。 */
export function getAccessToken(): Promise<string | null> {
  const oauthToken = localStorage.getItem(OAUTH_ACCESS_TOKEN);
  if (oauthToken) {
    try {
      const encoded = oauthToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=');
      const payload = JSON.parse(atob(padded));
      if (Number(payload.exp) * 1000 > Date.now()) return Promise.resolve(oauthToken);
    } catch {
      // Fall through to the Cognito SDK session.
    }
    localStorage.removeItem(OAUTH_ACCESS_TOKEN);
  }
  return new Promise((resolve) => {
    const u = currentUser();
    if (!u) return resolve(null);
    u.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session?.isValid()) return resolve(null);
      resolve(session.getAccessToken().getJwtToken());
    });
  });
}

/** 注册：用户名=email。返回待确认用户。 */
export function signUp(email: string, password: string, givenName: string, familyName: string) {
  return new Promise<CognitoUser>((resolve, reject) => {
    const attrs = [
      new CognitoUserAttribute({ Name: 'email', Value: email }),
      new CognitoUserAttribute({ Name: 'given_name', Value: givenName }),
      new CognitoUserAttribute({ Name: 'family_name', Value: familyName }),
    ];
    userPool.signUp(email, password, attrs, [], (err, result) => {
      if (err) return reject(err);
      resolve(result?.user ?? new CognitoUser({ Username: email, Pool: userPool }));
    });
  });
}

/** 邮箱验证码确认注册。 */
export function confirmSignUp(email: string, code: string) {
  return new Promise<void>((resolve, reject) => {
    const u = new CognitoUser({ Username: email, Pool: userPool });
    u.confirmRegistration(code, true, (err) => (err ? reject(err) : resolve()));
  });
}

/** 登录；强制改密时回调 onNewPasswordRequired。 */
export function signIn(username: string, password: string, onNewPasswordRequired?: () => void) {
  return new Promise<CognitoUserSession>((resolve, reject) => {
    const u = new CognitoUser({ Username: username, Pool: userPool });
    const auth = new AuthenticationDetails({ Username: username, Password: password });
    u.authenticateUser(auth, {
      onSuccess: (session) => resolve(session),
      onFailure: (err) => reject(err),
      newPasswordRequired: () => {
        challengedUser = u;
        if (onNewPasswordRequired) onNewPasswordRequired();
        else reject(new Error('NEW_PASSWORD_REQUIRED'));
      },
    });
  });
}

export function completeNewPassword(newPassword: string) {
  return new Promise<CognitoUserSession>((resolve, reject) => {
    if (!challengedUser) return reject(new Error('No password challenge is active. Please sign in again.'));
    challengedUser.completeNewPasswordChallenge(newPassword, {}, {
      onSuccess: (session) => { challengedUser = null; resolve(session); },
      onFailure: reject,
    });
  });
}

function base64Url(bytes: Uint8Array) {
  let binary = '';
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function startGoogleSignIn() {
  if (!config.COGNITO_DOMAIN || !config.GOOGLE_IDP_ENABLED) throw new Error('Google sign-in is not configured.');
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(48)));
  const state = base64Url(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = base64Url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  sessionStorage.setItem(OAUTH_CODE_VERIFIER, verifier);
  sessionStorage.setItem(OAUTH_STATE, state);
  const params = new URLSearchParams({
    client_id: config.USER_POOL_CLIENT_ID, response_type: 'code', scope: 'openid email profile',
    redirect_uri: config.OAUTH_REDIRECT_URI, identity_provider: 'Google',
    code_challenge_method: 'S256', code_challenge: challenge, state,
  });
  window.location.assign(`${config.COGNITO_DOMAIN}/oauth2/authorize?${params}`);
}

export async function completeOAuthCallback(code: string, returnedState: string | null) {
  const verifier = sessionStorage.getItem(OAUTH_CODE_VERIFIER);
  const expectedState = sessionStorage.getItem(OAUTH_STATE);
  if (!verifier) throw new Error('The OAuth session has expired. Please start sign-in again.');
  if (!returnedState || !expectedState || returnedState !== expectedState) throw new Error('OAuth state validation failed. Please start sign-in again.');
  const response = await fetch(`${config.COGNITO_DOMAIN}/oauth2/token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'authorization_code', client_id: config.USER_POOL_CLIENT_ID,
      code, redirect_uri: config.OAUTH_REDIRECT_URI, code_verifier: verifier }),
  });
  const body = await response.json();
  if (!response.ok || !body.access_token) throw new Error(body.error_description || body.error || 'OAuth token exchange failed');
  localStorage.setItem(OAUTH_ACCESS_TOKEN, body.access_token);
  sessionStorage.removeItem(OAUTH_CODE_VERIFIER);
  sessionStorage.removeItem(OAUTH_STATE);
}

export function signOut() {
  localStorage.removeItem(OAUTH_ACCESS_TOKEN);
  sessionStorage.removeItem(OAUTH_CODE_VERIFIER);
  sessionStorage.removeItem(OAUTH_STATE);
  currentUser()?.signOut();
}

export function isSignedIn(): Promise<boolean> {
  return getAccessToken().then((t) => t !== null);
}

import { CognitoUser, CognitoUserPool, CognitoUserAttribute, AuthenticationDetails } from 'amazon-cognito-identity-js';
import type { CognitoUserSession } from 'amazon-cognito-identity-js';
import { config } from '../config';

const poolData = {
  UserPoolId: config.USER_POOL_ID,
  ClientId: config.USER_POOL_CLIENT_ID,
};
const userPool = new CognitoUserPool(poolData);

function currentUser() {
  return userPool.getCurrentUser();
}

/** 拿到当前登录用户的 access token（去调用受保护 API）。Cognito 内部用 localStorage，无需额外 polyfill。 */
export function getAccessToken(): Promise<string | null> {
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
        if (onNewPasswordRequired) onNewPasswordRequired();
        else reject(new Error('NEW_PASSWORD_REQUIRED'));
      },
    });
  });
}

export function signOut() {
  currentUser()?.signOut();
}

export function isSignedIn(): Promise<boolean> {
  return getAccessToken().then((t) => t !== null);
}
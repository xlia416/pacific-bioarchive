import { useEffect, useState } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { isSignedIn } from './auth/cognito';
import { SignUpPage } from './pages/SignUpPage';
import { SignInPage } from './pages/SignInPage';
import { Dashboard } from './pages/Dashboard';

/** 路由守卫：作业要求未登录用户只能看到注册页（其余一律重定向到 /signup）。 */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const location = useLocation();

  useEffect(() => {
    let alive = true;
    isSignedIn().then((v) => alive && setAuthed(v));
    return () => {
      alive = false;
    };
  }, [location]);

  if (authed === null) return <div className="splash">加载中…</div>;
  if (!authed) return <Navigate to="/signup" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <div className="app">
      <Routes>
        <Route path="/signup" element={<SignUpPage />} />
        <Route path="/signin" element={<SignInPage />} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <Dashboard />
            </AuthGuard>
          }
        />
      </Routes>
    </div>
  );
}

export default App;
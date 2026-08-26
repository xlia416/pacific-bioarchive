import { useNavigate } from 'react-router-dom';
import { signOut } from '../auth/cognito';
import { UploadPanel } from '../components/UploadPanel';

export function Dashboard() {
  const navigate = useNavigate();
  return (
    <div className="dash">
      <header className="topbar">
        <span className="brand">Pacific BioArchive</span>
        <button
          onClick={() => {
            signOut();
            navigate('/signup');
          }}
        >
          退出登录
        </button>
      </header>
      <main>
        <UploadPanel />
        {/* Gallery + BulkTag + Query + Notifications 面板在后续轨道接入 */}
      </main>
    </div>
  );
}
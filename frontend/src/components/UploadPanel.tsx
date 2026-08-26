import { useState } from 'react';
import { api, sha256 } from '../api/client';

export function UploadPanel() {
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'duplicate' | 'error'>('idle');
  const [msg, setMsg] = useState('');

  const onFile = async (file: File) => {
    setMsg('');
    try {
      setStatus('uploading');
      const checksum = await sha256(file);
      let upload;
      try {
        upload = await api.presignUpload({
          filename: file.name,
          checksum,
          contentType: file.type,
        });
      } catch (e: any) {
        if (e?.message === 'DUPLICATE') {
          setStatus('duplicate');
          setMsg('检测到重复文件：该内容已存在（去重成功）。');
          return;
        }
        throw e;
      }
      await fetch(upload.uploadUrl, { method: 'PUT', body: file });
      setStatus('processing');
      setMsg('处理中（冷启动约 60–90 秒）…即将自动检测物种并生成缩略图');
    } catch (e: any) {
      setStatus('error');
      setMsg(`上传失败：${e?.message ?? e}`);
    }
  };

  return (
    <section className="card">
      <h2>上传媒体</h2>
      <p className="muted">支持图片与视频；上传后自动去重、识别物种、生成缩略图。</p>
      <label className="dropzone">
        点击选择或拖拽文件
        <input
          type="file"
          hidden
          accept="image/*,video/*"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
          }}
        />
      </label>
      {status !== 'idle' && <div className={`status ${status}`}>{msg}</div>}
    </section>
  );
}

export default UploadPanel;
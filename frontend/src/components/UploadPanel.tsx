import { useState } from 'react';
import { api, ApiError, poll, sha256 } from '../api/client';

export function UploadPanel({ onComplete }: { onComplete?: () => void }) {
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'duplicate' | 'error'>('idle');
  const [msg, setMsg] = useState('');

  const onFile = async (file: File) => {
    setMsg('');
    try {
      setStatus('uploading');
      const checksum = await sha256(file);
      const contentType = file.type || 'application/octet-stream';
      let upload;
      try {
        upload = await api.presignUpload({
          filename: file.name,
          checksum,
          contentType,
        });
      } catch (e: any) {
        if (e?.message === 'DUPLICATE') {
          setStatus('duplicate');
          setMsg('检测到重复文件：该内容已存在（去重成功）。');
          return;
        }
        throw e;
      }
      const put = await fetch(upload.uploadUrl, { method: 'PUT', headers: { 'Content-Type': contentType }, body: file });
      if (!put.ok) throw new Error(`S3 upload failed: ${put.status}`);
      setStatus('processing');
      setMsg('处理中：正在识别物种并生成缩略图…');
      const record = await poll(
        () => api.getFile(upload.fileId),
        (value) => value.status === 'processed' || value.status === 'failed',
      );
      if (record.status === 'failed') throw new Error(record.error || '媒体处理失败');
      setStatus('idle');
      setMsg(`处理完成：${Object.entries(record.tags || {}).map(([tag, count]) => `${tag}:${count}`).join(', ')}`);
      onComplete?.();
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setStatus('duplicate');
        setMsg('检测到重复文件：该内容已存在（去重成功）。');
        return;
      }
      setStatus('error');
      setMsg(`上传失败：${e?.message ?? e}`);
    }
  };

  return (
    <section className="card upload-panel">
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
      {msg && <div className={`status ${status}`}>{msg}</div>}
    </section>
  );
}

export default UploadPanel;

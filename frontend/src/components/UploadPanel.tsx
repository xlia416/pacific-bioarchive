import { useState } from 'react';
import { api, ApiError, poll, sha256, uploadToPresignedUrl } from '../api/client';

export function UploadPanel({ onComplete }: { onComplete?: () => void }) {
  const [status, setStatus] = useState<'idle' | 'hashing' | 'uploading' | 'processing' | 'complete' | 'duplicate' | 'error'>('idle');
  const [msg, setMsg] = useState('');
  const [progress, setProgress] = useState(0);

  const onFile = async (file: File) => {
    setMsg('');
    try {
      setStatus('hashing');
      setMsg(`Calculating checksum for ${file.name}…`);
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
          setMsg('Duplicate detected: this file already exists.');
          return;
        }
        throw e;
      }
      setStatus('uploading');
      setProgress(0);
      setMsg(`Uploading ${file.name}…`);
      await uploadToPresignedUrl(upload.uploadUrl, file, contentType, setProgress);
      setStatus('processing');
      setMsg('Processing: detecting species and generating a thumbnail…');
      const record = await poll(
        () => api.getFile(upload.fileId),
        (value) => value.status === 'processed' || value.status === 'failed',
      );
      if (record.status === 'failed') throw new Error(record.error || 'Media processing failed');
      setStatus('complete');
      setMsg(`Processing complete: ${Object.entries(record.tags || {}).map(([tag, count]) => `${tag}:${count}`).join(', ') || 'no species detected'}`);
      onComplete?.();
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setStatus('duplicate');
        setMsg('Duplicate detected: this file already exists.');
        return;
      }
      setStatus('error');
      setMsg(`Upload failed: ${e?.message ?? e}`);
    }
  };

  return (
    <section className="card upload-panel">
      <h2>Upload media</h2>
      <p className="muted">Images and videos are deduplicated, classified and given a thumbnail automatically.</p>
      <label className={`dropzone ${status === 'hashing' || status === 'uploading' || status === 'processing' ? 'disabled' : ''}`}>
        Choose an image or video
        <input
          type="file"
          hidden
          accept="image/*,video/*"
          disabled={status === 'hashing' || status === 'uploading' || status === 'processing'}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
          }}
        />
      </label>
      {status === 'uploading' && <div className="progress-track" aria-label={`Upload ${progress}%`}><span style={{ width: `${progress}%` }} /></div>}
      {msg && <div className={`status ${status}`}>{msg}</div>}
    </section>
  );
}

export default UploadPanel;

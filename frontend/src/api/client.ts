import { config } from '../config';
import { getAccessToken } from '../auth/cognito';

/** 带 JWT 的 fetch 封装：命中 401 抛错，供路由守卫跳转登录。 */
export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(`${config.API_BASE}${path}`, { ...init, headers });
}

/** 前端计算 SHA-256 校验和（去重用）。 */
export async function sha256(file: File | Blob): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export type Lifecycle = {
  /** 上传阶段：拿到预签名 URL 后直传。重复上传抛 409。 */
  presignUpload: (opts: { filename: string; checksum: string; contentType: string }) => Promise<{
    uploadUrl: string;
    fileId: string;
  }>;
  getFile: (checksum: string) => Promise<any>;
};

export const api: Lifecycle = {
  async presignUpload({ filename, checksum, contentType }) {
    const res = await authedFetch('/upload/presign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, checksum, contentType }),
    });
    if (res.status === 409) throw new Error('DUPLICATE');
    if (!res.ok) throw new Error(`presign failed: ${res.status}`);
    return res.json();
  },
  async getFile(checksum) {
    const res = await authedFetch(`/files/${checksum}`);
    if (!res.ok) throw new Error(`getFile failed: ${res.status}`);
    return res.json();
  },
};
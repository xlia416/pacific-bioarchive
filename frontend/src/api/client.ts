import { config } from '../config';
import { getAccessToken } from '../auth/cognito';

export type Tags = Record<string, number>;
export type FileRecord = {
  checksum: string;
  filename?: string;
  file_type?: 'image' | 'video';
  status?: string;
  tags?: Tags;
  oss_key?: string;
  thumbnail_oss_key?: string;
  oss_url?: string;
  thumbnail_oss_url?: string;
  url?: string;
  full_url?: string;
  error?: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(`${config.API_BASE}${path}`, { ...init, headers });
}

async function jsonResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, (body as any)?.error || `HTTP ${response.status}`, body);
  return body as T;
}

async function awsJson<T>(path: string, init: RequestInit = {}) {
  return jsonResponse<T>(await authedFetch(path, init));
}

async function aliyunJson<T>(path: string, init: RequestInit = {}) {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return jsonResponse<T>(await fetch(`${config.ALIYUN_QUERY_BASE}${path}`, { ...init, headers }));
}

export async function sha256(file: File | Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export const api = {
  async presignUpload(opts: { filename: string; checksum: string; contentType: string }) {
    const response = await authedFetch('/upload/presign', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 409) throw new ApiError(409, 'DUPLICATE', body);
    if (!response.ok) throw new ApiError(response.status, (body as any)?.error || 'presign failed', body);
    return { uploadUrl: (body as any).upload_url as string, fileId: (body as any).file_id as string };
  },
  getFile: (checksum: string) => awsJson<FileRecord>(`/files/${encodeURIComponent(checksum)}`),
  listFiles: () => awsJson<FileRecord[]>('/files'),
  bulkTags(checksums: string[], tags: string[], operation: 0 | 1) {
    return awsJson<{ updated: number; ignored: number }>('/tags/bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls: checksums, tags, operation }),
    });
  },
  deleteFiles(checksums: string[]) {
    return awsJson<{ deleted: number }>('/files/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ urls: checksums }),
    });
  },
  subscribe(email: string, tags: string[]) {
    return awsJson<{ subscription_arn: string; watch_tags: string[] }>('/notifications/subscribe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, tags }),
    });
  },
  async queryByFile(file: File) {
    return jsonResponse<{ job_id: string; status: string }>(await authedFetch('/query/file', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream', 'X-Filename': file.name },
      body: file,
    }));
  },
  getQueryJob(jobId: string) {
    return awsJson<{ job_id: string; status: string; tags?: Tags; matches?: FileRecord[]; error?: string }>(
      `/query/jobs/${encodeURIComponent(jobId)}`,
    );
  },
  async queryTags(conditions: Record<string, number | null>) {
    const body = await aliyunJson<{ results: FileRecord[] }>('/query/tags', {
      method: 'POST', body: JSON.stringify(conditions),
    });
    return body.results;
  },
  queryByThumbnail(url: string) {
    return aliyunJson<FileRecord>(`/query/by-thumbnail?url=${encodeURIComponent(url)}`);
  },
};

export async function poll<T>(load: () => Promise<T>, done: (value: T) => boolean, timeoutMs = 15 * 60_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = await load();
    if (done(value)) return value;
    await new Promise((resolve) => window.setTimeout(resolve, 5000));
  }
  throw new Error('processing timed out');
}

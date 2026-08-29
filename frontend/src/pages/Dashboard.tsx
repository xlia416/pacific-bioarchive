import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, FileRecord, poll } from '../api/client';
import { signOut } from '../auth/cognito';
import { UploadPanel } from '../components/UploadPanel';

function tagText(tags?: Record<string, number>) {
  return Object.entries(tags || {}).map(([tag, count]) => `${tag}:${count}`).join(', ') || '无标签';
}

function TagChips({ tags }: { tags?: Record<string, number> }) {
  const entries = Object.entries(tags || {});
  if (!entries.length) return <span className="tag-chip empty-chip">无标签</span>;
  return <>{entries.map(([tag, count]) => <span className="tag-chip" key={tag} title={`${tag}: ${count}`}>{tag} ×{count}</span>)}</>;
}

function ResultCards({ files, selectable = false, selected = new Set<string>(), onToggle }: {
  files: FileRecord[]; selectable?: boolean; selected?: Set<string>; onToggle?: (checksum: string) => void;
}) {
  const [copyState, setCopyState] = useState<{ checksum: string; ok: boolean } | null>(null);

  const copyThumbnail = async (file: FileRecord, url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopyState({ checksum: file.checksum, ok: true });
    } catch {
      setCopyState({ checksum: file.checksum, ok: false });
    }
    window.setTimeout(() => setCopyState((current) => current?.checksum === file.checksum ? null : current), 1800);
  };

  if (!files.length) return <p className="empty">暂无结果</p>;
  return <div className="media-grid">{files.map((file) => {
    const thumbnailUrl = file.file_type === 'image' ? (file.url || file.thumbnail_oss_url) : undefined;
    const feedback = copyState?.checksum === file.checksum ? copyState : null;
    return <article className="media-card" key={file.checksum}>
      <div className="preview">
        {file.file_type === 'video' && file.url
          ? <video controls preload="metadata" src={file.url} />
          : file.url ? <a href={file.full_url || file.url} target="_blank" rel="noreferrer"><img src={file.url} alt={file.filename || file.checksum} /></a>
          : <span>{file.status || '等待处理'}</span>}
      </div>
      <div className="media-meta">
        {selectable && <input aria-label={`选择 ${file.filename || file.checksum}`} type="checkbox" checked={selected.has(file.checksum)} onChange={() => onToggle?.(file.checksum)} />}
        <div>
          <strong title={file.filename || file.checksum}>{file.filename || `${file.file_type || 'media'} 文件`}</strong>
          <small title={file.checksum}>{file.checksum}</small>
        </div>
      </div>
      <div className="tags"><TagChips tags={file.tags} /></div>
      <div className="media-actions">
        {thumbnailUrl && <button className="copy-button secondary" type="button" title={thumbnailUrl} onClick={() => void copyThumbnail(file, thumbnailUrl)}>
          {feedback ? (feedback.ok ? '已复制' : '复制失败，请右键复制') : '复制缩略图 URL'}
        </button>}
        {file.full_url && <a className="text-link" href={file.full_url} target="_blank" rel="noreferrer">打开完整媒体</a>}
      </div>
      {file.error && <p className="error">{file.error}</p>}
    </article>;
  })}</div>;
}

function QueryPanel() {
  const [tagInput, setTagInput] = useState('Sus_scrofa:1');
  const [thumbnail, setThumbnail] = useState('');
  const [results, setResults] = useState<FileRecord[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const queryTags = async () => {
    setBusy(true); setMessage('');
    try {
      const conditions: Record<string, number | null> = {};
      tagInput.split(',').map((part) => part.trim()).filter(Boolean).forEach((part) => {
        const [name, rawCount] = part.split(':').map((value) => value.trim());
        if (name) conditions[name] = rawCount ? Number(rawCount) : null;
      });
      setResults(await api.queryTags(conditions));
    } catch (err: any) { setMessage(err.message); } finally { setBusy(false); }
  };

  const queryThumbnail = async () => {
    setBusy(true); setMessage('');
    try {
      const requestedThumbnail = thumbnail.trim();
      const found = await api.queryByThumbnail(requestedThumbnail);
      setResults([{ ...found, url: requestedThumbnail, thumbnail_oss_url: requestedThumbnail }]);
      setMessage('已找到对应的完整图片');
    }
    catch (err: any) { setResults([]); setMessage(err.message); }
    finally { setBusy(false); }
  };

  const queryFile = async (file: File) => {
    setBusy(true); setMessage('正在分析查询文件…');
    try {
      const queued = await api.queryByFile(file);
      const job = await poll(() => api.getQueryJob(queued.job_id), (value) => value.status === 'completed' || value.status === 'failed');
      if (job.status === 'failed') throw new Error(job.error || '查询处理失败');
      setResults(await api.queryTags(job.tags || {}));
      setMessage(`识别标签：${tagText(job.tags)}`);
    } catch (err: any) { setMessage(err.message); } finally { setBusy(false); }
  };

  return <section className="panel query-panel">
    <div className="panel-heading"><div><h2>媒体查询</h2><p>支持标签 AND、数量、缩略图 URL 和查询文件。</p></div></div>
    <div className="query-grid">
      <form onSubmit={(e) => { e.preventDefault(); void queryTags(); }}>
        <div className="field"><label htmlFor="tag-query">标签与最小数量</label><input id="tag-query" value={tagInput} onChange={(e) => setTagInput(e.target.value)} placeholder="dingo:2, cat:1" /></div>
        <button disabled={busy}>查询标签</button>
      </form>
      <form onSubmit={(e) => { e.preventDefault(); void queryThumbnail(); }}>
        <div className="field"><label htmlFor="thumbnail-query">缩略图 URL</label><input id="thumbnail-query" value={thumbnail} onChange={(e) => setThumbnail(e.target.value)} placeholder="https://.../thumb.jpg" required /></div>
        <button disabled={busy}>反查原图</button>
      </form>
      <div className="file-query"><span className="field-label">按文件中的物种查询</span><label className="file-button">选择查询文件<input hidden type="file" accept="image/*,video/*" onChange={(e) => { const file = e.target.files?.[0]; if (file) void queryFile(file); }} /></label></div>
    </div>
    {message && <p className={message.includes('失败') ? 'error' : 'notice'}>{message}</p>}
    <ResultCards files={results} />
  </section>;
}

function ManagementPanel({ selected, onChanged }: { selected: string[]; onChanged: () => void }) {
  const [tags, setTags] = useState('research');
  const [email, setEmail] = useState('');
  const [watchTags, setWatchTags] = useState('Sus_scrofa');
  const [message, setMessage] = useState('');
  const parsedTags = (value: string) => value.split(',').map((tag) => tag.trim()).filter(Boolean);

  const mutate = async (operation: 0 | 1) => {
    if (!selected.length) return setMessage('请先在文件库选择文件');
    try {
      const result = await api.bulkTags(selected, parsedTags(tags), operation);
      setMessage(`已更新 ${result.updated} 个文件，忽略 ${result.ignored} 个不存在的标签`); onChanged();
    } catch (err: any) { setMessage(err.message); }
  };

  const remove = async () => {
    if (!selected.length) return setMessage('请先选择文件');
    if (!window.confirm(`确定删除 ${selected.length} 个文件及其跨云副本？`)) return;
    try { const result = await api.deleteFiles(selected); setMessage(`已删除 ${result.deleted} 个文件`); onChanged(); }
    catch (err: any) { setMessage(err.message); }
  };

  const subscribe = async (e: React.FormEvent) => {
    e.preventDefault();
    try { const result = await api.subscribe(email, parsedTags(watchTags)); setMessage(`确认邮件已发送：${result.watch_tags.join(', ')}`); }
    catch (err: any) { setMessage(err.message); }
  };

  return <section className="panel management-panel">
    <div className="panel-heading"><div><h2>批量管理与通知</h2><p>已选 {selected.length} 个文件</p></div></div>
    <div className="management-grid">
      <div className="management-block">
        <div className="field"><label htmlFor="bulk-tags">标签（逗号分隔）</label><input id="bulk-tags" value={tags} onChange={(e) => setTags(e.target.value)} /></div>
        <div className="button-row"><button type="button" onClick={() => void mutate(1)}>添加标签</button><button type="button" className="secondary" onClick={() => void mutate(0)}>删除标签</button><button type="button" className="danger" onClick={() => void remove()}>删除文件</button></div>
      </div>
      <form onSubmit={subscribe}>
        <div className="field"><label htmlFor="notification-email">邮件通知</label><input id="notification-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" required /></div>
        <div className="field"><label htmlFor="notification-tags">关注标签</label><input id="notification-tags" value={watchTags} onChange={(e) => setWatchTags(e.target.value)} placeholder="Sus_scrofa, dingo" required /></div>
        <button>订阅标签</button>
      </form>
    </div>
    {message && <p className="notice">{message}</p>}
  </section>;
}

export function Dashboard() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [records, signed] = await Promise.all([api.listFiles(), api.queryTags({}).catch(() => [])]);
      const signedById = new Map(signed.map((item) => [item.checksum, item]));
      setFiles(records.sort((a, b) => (b.checksum || '').localeCompare(a.checksum || '')).map((record) => ({ ...record, ...signedById.get(record.checksum) })));
      setSelected((current) => new Set([...current].filter((id) => records.some((file) => file.checksum === id))));
    } catch (err: any) { setError(err.message); } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  const selectedIds = useMemo(() => [...selected], [selected]);
  const filteredFiles = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return files;
    return files.filter((file) => [file.filename, file.checksum, ...Object.keys(file.tags || {})]
      .some((value) => value?.toLowerCase().includes(query)));
  }, [files, filter]);
  const allFilteredSelected = filteredFiles.length > 0 && filteredFiles.every((file) => selected.has(file.checksum));

  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next;
  });
  const selectFiltered = () => setSelected((current) => {
    const next = new Set(current); filteredFiles.forEach((file) => next.add(file.checksum)); return next;
  });

  return <div className="dash">
    <header className="topbar"><div><span className="brand">Pacific BioArchive</span><small>Multi-cloud wildlife media platform</small></div>
      <button className="secondary" onClick={() => { signOut(); navigate('/signup'); }}>退出登录</button></header>
    <main className="dashboard-grid">
      <UploadPanel onComplete={refresh} />
      <ManagementPanel selected={selectedIds} onChanged={() => { setSelected(new Set()); void refresh(); }} />
      <QueryPanel />
      <section className="panel library-panel">
        <div className="panel-heading library-heading">
          <div><h2>媒体库</h2><p>共 {files.length} 项 · 当前显示 {filteredFiles.length} 项 · 已选 {selected.size} 项</p></div>
          <div className="library-tools">
            <input aria-label="筛选媒体" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="按文件名、标签或 checksum 筛选" />
            <div className="button-row compact">
              <button type="button" className="secondary" disabled={!filteredFiles.length || allFilteredSelected} onClick={selectFiltered}>全选当前结果</button>
              <button type="button" className="secondary" disabled={!selected.size} onClick={() => setSelected(new Set())}>清空选择</button>
              <button type="button" className="secondary" onClick={() => void refresh()}>{loading ? '刷新中…' : '刷新'}</button>
            </div>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        <ResultCards files={filteredFiles} selectable selected={selected} onToggle={toggle} />
      </section>
    </main>
  </div>;
}

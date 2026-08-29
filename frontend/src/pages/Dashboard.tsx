import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError, FileRecord, poll } from '../api/client';
import { signOut } from '../auth/cognito';
import { UploadPanel } from '../components/UploadPanel';

type Feedback = { kind: 'success' | 'error' | 'info'; text: string } | null;

function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.') {
  if (error instanceof ApiError && error.status === 404) return 'No media matches this request.';
  if (error instanceof ApiError && error.status === 400) return error.message || 'The request is invalid.';
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function tagText(tags?: Record<string, number>) {
  return Object.entries(tags || {}).map(([tag, count]) => `${tag}:${count}`).join(', ') || 'none';
}

function TagChips({ tags }: { tags?: Record<string, number> }) {
  const entries = Object.entries(tags || {});
  if (!entries.length) return <span className="tag-chip empty-chip">No tags</span>;
  return <>{entries.map(([tag, count]) => <span className="tag-chip" key={tag} title={`${tag}: ${count}`}>{tag} ×{count}</span>)}</>;
}

function MediaPreview({ file }: { file: FileRecord }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [file.url]);
  if (failed) return <div className="preview-state error-preview"><strong>Preview unavailable</strong><small>The secure link may have expired. Refresh and try again.</small></div>;
  if (!file.url) {
    const processing = file.status === 'pending' || file.status === 'processing';
    return <div className="preview-state">{processing && <span className="spinner" />}<strong>{processing ? 'Processing media…' : 'Preview unavailable'}</strong></div>;
  }
  if (file.file_type === 'video') return <video controls preload="metadata" src={file.url} onError={() => setFailed(true)} />;
  return <a href={file.full_url || file.url} target="_blank" rel="noreferrer">
    <img src={file.url} alt={file.filename || `Thumbnail ${file.checksum}`} onError={() => setFailed(true)} />
  </a>;
}

function ResultCards({ files, selectable = false, selected = new Set<string>(), onToggle, emptyText = 'No results found.' }: {
  files: FileRecord[]; selectable?: boolean; selected?: Set<string>; onToggle?: (checksum: string) => void; emptyText?: string;
}) {
  const [copyState, setCopyState] = useState<{ checksum: string; ok: boolean } | null>(null);
  const copyThumbnail = async (file: FileRecord, url: string) => {
    try { await navigator.clipboard.writeText(url); setCopyState({ checksum: file.checksum, ok: true }); }
    catch { setCopyState({ checksum: file.checksum, ok: false }); }
    window.setTimeout(() => setCopyState((current) => current?.checksum === file.checksum ? null : current), 1800);
  };

  if (!files.length) return <p className="empty">{emptyText}</p>;
  return <div className="media-grid">{files.map((file) => {
    const thumbnailUrl = file.file_type === 'image' ? (file.url || file.thumbnail_oss_url) : undefined;
    const feedback = copyState?.checksum === file.checksum ? copyState : null;
    return <article className="media-card" key={file.checksum}>
      <div className="preview"><MediaPreview file={file} /></div>
      <div className="media-meta">
        {selectable && <input aria-label={`Select ${file.filename || file.checksum}`} type="checkbox" checked={selected.has(file.checksum)} onChange={() => onToggle?.(file.checksum)} />}
        <div><strong title={file.filename || file.checksum}>{file.filename || `${file.file_type || 'media'} file`}</strong><small title={file.checksum}>{file.checksum}</small></div>
      </div>
      <div className="tags"><TagChips tags={file.tags} /></div>
      <div className="media-actions">
        {thumbnailUrl && <button className="copy-button secondary" type="button" title={thumbnailUrl} onClick={() => void copyThumbnail(file, thumbnailUrl)}>{feedback ? (feedback.ok ? 'Copied' : 'Copy failed') : 'Copy thumbnail URL'}</button>}
        {file.full_url && <a className="text-link" href={file.full_url} target="_blank" rel="noreferrer">Open full media</a>}
      </div>
      {file.error && <p className="error">{file.error}</p>}
    </article>;
  })}</div>;
}

function QueryPanel() {
  const [tagInput, setTagInput] = useState('Sus_scrofa:1');
  const [thumbnail, setThumbnail] = useState('');
  const [results, setResults] = useState<FileRecord[]>([]);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState<'tags' | 'thumbnail' | 'file' | null>(null);

  const queryTags = async () => {
    setBusy('tags'); setFeedback(null); setResults([]);
    try {
      const conditions: Record<string, number | null> = {};
      tagInput.split(',').map((part) => part.trim()).filter(Boolean).forEach((part) => {
        const [name, rawCount] = part.split(':').map((value) => value.trim());
        const count = rawCount ? Number(rawCount) : null;
        if (name && (count === null || (Number.isFinite(count) && count >= 1))) conditions[name] = count;
      });
      const found = await api.queryTags(conditions);
      setResults(found);
      setFeedback({ kind: found.length ? 'success' : 'info', text: found.length ? `Found ${found.length} matching item${found.length === 1 ? '' : 's'}.` : 'No media matches these tags.' });
    } catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'Tag query failed.') }); }
    finally { setBusy(null); }
  };

  const queryThumbnail = async () => {
    setBusy('thumbnail'); setFeedback(null); setResults([]);
    try {
      const found = await api.queryByThumbnail(thumbnail.trim());
      setResults([found]);
      setFeedback({ kind: 'success', text: 'Original image found. Fresh secure links are shown below.' });
    } catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'Thumbnail lookup failed.') }); }
    finally { setBusy(null); }
  };

  const queryFile = async (file: File) => {
    setBusy('file'); setFeedback({ kind: 'info', text: `Analysing ${file.name}…` }); setResults([]);
    try {
      const queued = await api.queryByFile(file);
      const job = await poll(() => api.getQueryJob(queued.job_id), (value) => value.status === 'completed' || value.status === 'failed');
      if (job.status === 'failed') throw new Error(job.error || 'Query-file processing failed.');
      const found = await api.queryTags(job.tags || {});
      setResults(found);
      setFeedback({ kind: found.length ? 'success' : 'info', text: `Detected tags: ${tagText(job.tags)}. ${found.length} archive match${found.length === 1 ? '' : 'es'}.` });
    } catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'File query failed.') }); }
    finally { setBusy(null); }
  };

  return <section className="panel query-panel">
    <div className="panel-heading"><div><h2>Media queries</h2><p>Search by AND tags, counts, a thumbnail URL or species detected in a file.</p></div></div>
    <div className="query-grid">
      <form onSubmit={(event) => { event.preventDefault(); void queryTags(); }}><div className="field"><label htmlFor="tag-query">Tags and minimum counts</label><input id="tag-query" value={tagInput} onChange={(event) => setTagInput(event.target.value)} placeholder="dingo:2, cat:1" /></div><button disabled={busy !== null}>{busy === 'tags' ? 'Searching…' : 'Search tags'}</button></form>
      <form onSubmit={(event) => { event.preventDefault(); void queryThumbnail(); }}><div className="field"><label htmlFor="thumbnail-query">Thumbnail URL</label><input id="thumbnail-query" value={thumbnail} onChange={(event) => setThumbnail(event.target.value)} placeholder="https://.../thumb.jpg" required /></div><button disabled={busy !== null}>{busy === 'thumbnail' ? 'Looking up…' : 'Find original'}</button></form>
      <div className="file-query"><span className="field-label">Search by species in a file</span><label className={`file-button ${busy ? 'disabled' : ''}`}>{busy === 'file' ? <><span className="spinner" /> Analysing file…</> : 'Choose a query file'}<input hidden type="file" accept="image/*,video/*" disabled={busy !== null} onChange={(event) => { const file = event.target.files?.[0]; if (file) void queryFile(file); event.target.value = ''; }} /></label></div>
    </div>
    {feedback && <p className={`feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.text}</p>}
    {busy && <div className="query-loading"><span className="spinner" /> Request in progress…</div>}
    {!busy && <ResultCards files={results} emptyText={feedback ? 'No result cards to display.' : 'Run a query to see results.'} />}
  </section>;
}

function ManagementPanel({ selected, onChanged }: { selected: string[]; onChanged: () => void }) {
  const [tags, setTags] = useState('research');
  const [email, setEmail] = useState('');
  const [watchTags, setWatchTags] = useState('Sus_scrofa');
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);
  const parsedTags = (value: string) => value.split(',').map((tag) => tag.trim()).filter(Boolean);

  const mutate = async (operation: 0 | 1) => {
    if (!selected.length) return setFeedback({ kind: 'error', text: 'Select at least one item in the media library first.' });
    setBusy(true); setFeedback(null);
    try { const result = await api.bulkTags(selected, parsedTags(tags), operation); setFeedback({ kind: 'success', text: `Updated ${result.updated} item${result.updated === 1 ? '' : 's'}; ignored ${result.ignored} missing tag${result.ignored === 1 ? '' : 's'}.` }); onChanged(); }
    catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'Tag update failed.') }); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!selected.length) return setFeedback({ kind: 'error', text: 'Select at least one item first.' });
    if (!window.confirm(`Delete ${selected.length} selected item${selected.length === 1 ? '' : 's'} and all cross-cloud copies?`)) return;
    setBusy(true); setFeedback(null);
    try { const result = await api.deleteFiles(selected); setFeedback({ kind: 'success', text: `Deleted ${result.deleted} item${result.deleted === 1 ? '' : 's'}.` }); onChanged(); }
    catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'Delete failed.') }); }
    finally { setBusy(false); }
  };
  const subscribe = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setFeedback(null);
    try { const result = await api.subscribe(email, parsedTags(watchTags)); setFeedback({ kind: 'success', text: `Confirmation email sent for: ${result.watch_tags.join(', ')}.` }); }
    catch (error) { setFeedback({ kind: 'error', text: errorMessage(error, 'Subscription failed.') }); }
    finally { setBusy(false); }
  };

  return <section className="panel management-panel">
    <div className="panel-heading"><div><h2>Bulk management & notifications</h2><p>{selected.length} item{selected.length === 1 ? '' : 's'} selected</p></div></div>
    <div className="management-grid">
      <div className="management-block"><div className="field"><label htmlFor="bulk-tags">Tags (comma separated)</label><input id="bulk-tags" value={tags} onChange={(event) => setTags(event.target.value)} /></div><div className="button-row"><button disabled={busy} type="button" onClick={() => void mutate(1)}>Add tags</button><button disabled={busy} type="button" className="secondary" onClick={() => void mutate(0)}>Remove tags</button><button disabled={busy} type="button" className="danger" onClick={() => void remove()}>Delete files</button></div></div>
      <form onSubmit={subscribe}><div className="field"><label htmlFor="notification-email">Email notifications</label><input id="notification-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" required /></div><div className="field"><label htmlFor="notification-tags">Watched tags</label><input id="notification-tags" value={watchTags} onChange={(event) => setWatchTags(event.target.value)} placeholder="Sus_scrofa, dingo" required /></div><button disabled={busy}>Subscribe to tags</button></form>
    </div>
    {feedback && <p className={`feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.text}</p>}
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
      const records = await api.listFiles();
      const ordered = records.sort((a, b) => (b.checksum || '').localeCompare(a.checksum || ''));
      try {
        const signed = await api.queryTags({});
        const signedById = new Map(signed.map((item) => [item.checksum, item]));
        setFiles(ordered.map((record) => ({ ...record, ...signedById.get(record.checksum) })));
      } catch (error) {
        setFiles(ordered);
        setError(`Media records loaded, but secure previews are temporarily unavailable: ${errorMessage(error)}`);
      }
      setSelected((current) => new Set([...current].filter((id) => records.some((file) => file.checksum === id))));
    } catch (error) { setFiles([]); setError(errorMessage(error, 'The media library could not be loaded.')); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  const selectedIds = useMemo(() => [...selected], [selected]);
  const filteredFiles = useMemo(() => { const query = filter.trim().toLowerCase(); if (!query) return files; return files.filter((file) => [file.filename, file.checksum, ...Object.keys(file.tags || {})].some((value) => value?.toLowerCase().includes(query))); }, [files, filter]);
  const allFilteredSelected = filteredFiles.length > 0 && filteredFiles.every((file) => selected.has(file.checksum));
  const toggle = (id: string) => setSelected((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const selectFiltered = () => setSelected((current) => { const next = new Set(current); filteredFiles.forEach((file) => next.add(file.checksum)); return next; });

  return <div className="dash">
    <header className="topbar"><div><span className="brand">Pacific BioArchive</span><small>Multi-cloud wildlife media platform</small></div><button className="secondary" onClick={() => { signOut(); navigate('/signup'); }}>Sign out</button></header>
    <main className="dashboard-grid">
      <UploadPanel onComplete={refresh} />
      <ManagementPanel selected={selectedIds} onChanged={() => { setSelected(new Set()); void refresh(); }} />
      <QueryPanel />
      <section className="panel library-panel">
        <div className="panel-heading library-heading"><div><h2>Media library</h2><p>{files.length} total · {filteredFiles.length} shown · {selected.size} selected</p></div><div className="library-tools"><input aria-label="Filter media" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter by filename, tag or checksum" /><div className="button-row compact"><button type="button" className="secondary" disabled={!filteredFiles.length || allFilteredSelected} onClick={selectFiltered}>Select shown</button><button type="button" className="secondary" disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear selection</button><button type="button" className="secondary" disabled={loading} onClick={() => void refresh()}>{loading ? 'Refreshing…' : 'Refresh'}</button></div></div></div>
        {error && <p className="feedback error" role="alert">{error}</p>}
        {loading && !files.length ? <div className="library-loading"><span className="spinner" /> Loading media library…</div> : <ResultCards files={filteredFiles} selectable selected={selected} onToggle={toggle} emptyText={filter ? 'No items match this filter.' : 'No media has been uploaded yet.'} />}
      </section>
    </main>
  </div>;
}

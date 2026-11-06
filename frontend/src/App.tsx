import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Activity, ArrowDownUp, ArrowLeft, ArrowRight, AudioLines, Check, CheckCheck, ChevronLeft, ChevronRight, Database, FileAudio2, FolderOpen, Headphones, Info, ListMusic, Pencil, Play, Plus, RefreshCw, Search, Settings2, SlidersHorizontal, Volume2, X } from 'lucide-react'
import { apiUrl, duration, number, size, useApi, type AudioRecord, type Dataset, type RecordPage, type Playback } from './api'
import { DatasetForm, ErrorNotice, Skeleton, SubtitleEditor, SyncDialog } from './components'

import AudioLibrary from './AudioLibrary'

type DatasetPlayback = { dataset: Dataset; record: AudioRecord }

function Library({ version, onAdd, onConfigure }: { version: number; onAdd: () => void; onConfigure: (dataset: Dataset) => void }) {
  const [reload, setReload] = useState(0)
  const source = useApi<{ items: Dataset[] }>('/datasets', version + reload)
  const [query, setQuery] = useState('')
  const [order, setOrder] = useState('newest')
  const datasets = useMemo(() => {
    const filtered = (source.data?.items ?? []).filter(item => `${item.name} ${item.storage_dir}`.toLowerCase().includes(query.toLowerCase()))
    return order === 'name' ? [...filtered].sort((a, b) => a.name.localeCompare(b.name)) : filtered
  }, [source.data, query, order])
  const totalRecords = source.data?.items.reduce((sum, dataset) => sum + dataset.record_count, 0) ?? 0
  return <>
    <div className="page-heading"><div><h1>数据集库 <span className="heading-count">{source.data?.items.length ?? '—'}</span></h1><p>让音频与字幕有序归档，从这里开始管理你的语料。</p></div><button className="button primary" onClick={onAdd}><Plus size={18} />添加数据集</button></div>
    <section className="library-panel" aria-label="数据集列表">
      <div className="section-tab"><div><ListMusic size={18} /><strong>全部数据集</strong><span>{source.data?.items.length ?? 0}</span></div><p>共 {number(totalRecords)} 条音频记录</p></div>
      <div className="table-toolbar"><label className="search-input"><Search size={17} /><input aria-label="搜索数据集" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索数据集名称或目录…" /></label><div className="toolbar-right"><label className="select-control"><ArrowDownUp size={15} /><select aria-label="数据集排序" value={order} onChange={event => setOrder(event.target.value)}><option value="newest">最近添加</option><option value="name">名称排序</option></select></label><button className="icon-button" aria-label="刷新数据集" onClick={() => setReload(previous => previous + 1)} disabled={source.loading}><RefreshCw size={17} className={source.loading ? 'spin' : ''} /></button></div></div>
      {source.error ? <ErrorNotice message={source.error} retry={() => setReload(previous => previous + 1)} /> : source.loading ? <Skeleton rows={3} /> : datasets.length ? <div className="table-scroll"><table className="dataset-table"><thead><tr><th>数据集</th><th>存储目录</th><th className="numeric">音频记录</th><th>字幕覆盖</th><th>操作</th></tr></thead><tbody>{datasets.map(dataset => {
        const coverage = dataset.record_count ? Math.round(dataset.subtitle_count / dataset.record_count * 100) : 0
        return <tr key={dataset.id}><td><Link className="dataset-name" to={`/datasets/${dataset.id}`}><span className="dataset-icon"><AudioLines size={24} /></span><span><strong>{dataset.name}</strong><small>ID {dataset.id} <span>·</span> WAV 音频</small></span></Link></td><td><div className="storage-cell"><code title={dataset.storage_dir}>{dataset.storage_dir}</code><small><i className={`status-dot ${dataset.storage_available ? '' : 'offline'}`} />{dataset.storage_available ? '本地目录可用' : '目录不可用，请检查配置'}</small></div></td><td className="numeric record-count">{number(dataset.record_count)}<small>条记录</small></td><td><span className="coverage"><CheckCheck size={15} />{coverage}%</span><small className="coverage-caption">{number(dataset.subtitle_count)} 条有字幕</small></td><td><div className="row-actions"><button className="icon-button" aria-label={`配置 ${dataset.name}`} onClick={() => onConfigure(dataset)}><Settings2 size={17} /></button><Link className="icon-button open-link" aria-label={`查看 ${dataset.name} 明细`} to={`/datasets/${dataset.id}`}><ArrowRight size={18} /></Link></div></td></tr>
      })}</tbody></table></div> : <div className="empty-state"><FolderOpen size={36} /><h2>{query ? '没有匹配的数据集' : '你的语料库，从第一份数据开始'}</h2><p>{query ? '试试其他名称或目录关键词。' : '连接本地音频目录，添加字幕清单，即可开始整理与试听。'}</p><button className="button secondary" onClick={query ? () => setQuery('') : onAdd}>{query ? '清除搜索' : '添加第一个数据集'}</button></div>}
      <div className="table-footer"><span>{source.data ? `${datasets.length} 个数据集` : '正在读取数据集'}<span className="footer-separator">·</span>SQLite 本地存储</span><span><Check size={13} />源文件保留在原目录</span></div>
    </section>
    <section className="getting-started"><div className="guide-heading"><h2>从目录到可用的语料</h2><p>只管理索引与字幕，让原始音频保持原样。</p></div><div className="guide-steps"><div><span className="guide-icon"><FolderOpen size={21} /></span><div><h3>连接本地目录</h3><p>填写数据集根目录与音频子目录。</p></div></div><ChevronRight className="guide-arrow" size={18} /><div><span className="guide-icon"><ListMusic size={21} /></span><div><h3>关联字幕清单</h3><p>可选导入 UTF-8 字幕，自动匹配音频。</p></div></div><ChevronRight className="guide-arrow" size={18} /><div><span className="guide-icon"><Headphones size={21} /></span><div><h3>浏览与校对</h3><p>搜索明细、试听音频并编辑字幕。</p></div></div></div></section>
    <div className="workspace-note"><Info size={15} /><p>路径指向后端服务器上的文件。当前导入支持 WAV 音频与「音频标识:字幕」格式的文本清单。</p></div>
  </>
}

function Details({ version, onConfigure, onSync, onEdit, onPlay, playing }: {
  version: number; onConfigure: (dataset: Dataset) => void; onSync: (dataset: Dataset) => void
  onEdit: (dataset: Dataset, record: AudioRecord) => void; onPlay: (value: DatasetPlayback) => void; playing: Playback | null
}) {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const [refresh, setRefresh] = useState(0)
  const q = params.get('q') ?? ''
  const subtitle = ['present', 'missing'].includes(params.get('subtitle') ?? '') ? params.get('subtitle')! : 'all'
  const page = Math.max(1, Math.min(10000000, Number(params.get('page')) || 1))
  const pageSize = [10, 20, 50, 100].includes(Number(params.get('page_size'))) ? Number(params.get('page_size')) : 20
  const [search, setSearch] = useState(q)
  const dataset = useApi<Dataset>(`/datasets/${id}`, version + refresh)
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize), q, subtitle })
  const records = useApi<RecordPage>(`/datasets/${id}/records?${query}`, version + refresh)
  useEffect(() => setSearch(q), [q])
  useEffect(() => {
    if (search === q) return
    const timeout = setTimeout(() => setParams(previous => {
      const next = new URLSearchParams(previous); next.delete('page')
      if (search) next.set('q', search); else next.delete('q')
      return next
    }, { replace: true }), 300)
    return () => clearTimeout(timeout)
  }, [search, q, setParams])
  function change(key: string, value: string) {
    setParams(previous => { const next = new URLSearchParams(previous); next.delete('page'); next.set(key, value); return next })
  }
  if (dataset.error) return <><Link className="back-link" to="/datasets"><ArrowLeft size={16} />返回数据集库</Link><ErrorNotice message={dataset.error} retry={() => setRefresh(previous => previous + 1)} /></>
  if (!dataset.data) return <Skeleton rows={7} />
  const current = dataset.data
  const total = records.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const visiblePages = Array.from(new Set([1, ...Array.from({ length: 3 }, (_, index) => page - 1 + index).filter(value => value > 1 && value < pages), pages])).sort((a, b) => a - b)
  return <>
    <Link className="back-link" to="/datasets"><ArrowLeft size={15} />返回数据集库</Link>
    <div className="page-heading detail-heading"><div className="detail-title"><span className="dataset-icon large"><AudioLines size={29} /></span><div><h1>{current.name}</h1><p><code>ID {current.id}</code><span>·</span>{current.detail_table}</p></div></div><div className="heading-actions"><button className="button secondary" onClick={() => onSync(current)}><RefreshCw size={16} />重新导入</button><button className="button secondary" onClick={() => onConfigure(current)}><Settings2 size={17} />数据集配置</button></div></div>
    <section className="dataset-summary" aria-label="数据集信息"><div className="summary-count"><span>音频记录</span><strong>{number(current.record_count)}<small>条</small></strong></div><div className="summary-count"><span>已有字幕</span><strong>{number(current.subtitle_count)}<small>条</small></strong></div><div className="summary-storage"><span><FolderOpen size={14} />存储目录</span><code title={`${current.storage_dir}/${current.audio_subdir}`}>{current.storage_dir}/{current.audio_subdir}</code><small><i className={`status-dot ${current.storage_available ? '' : 'offline'}`} />{current.storage_available ? '目录可用' : '目录不可用'}<span>·</span>WAV 音频</small></div></section>
    <section className="records-panel" aria-label="音频明细">
      <div className="section-tab"><div><FileAudio2 size={18} /><strong>音频明细</strong><span>{number(current.record_count)}</span></div><p>试听音频，校对每一条字幕</p></div>
      <div className="table-toolbar"><label className="search-input"><Search size={17} /><input aria-label="搜索音频或字幕" placeholder="搜索音频文件名或字幕内容…" value={search} onChange={event => setSearch(event.target.value)} maxLength={500} />{search ? <button className="icon-button small" aria-label="清除明细搜索" onClick={() => setSearch('')}><X size={14} /></button> : null}</label><div className="toolbar-right"><label className="select-control"><SlidersHorizontal size={15} /><select aria-label="字幕筛选" value={subtitle} onChange={event => change('subtitle', event.target.value)}><option value="all">全部字幕状态</option><option value="present">有字幕</option><option value="missing">无字幕</option></select></label><button className="icon-button" aria-label="刷新明细" disabled={records.loading} onClick={() => setRefresh(previous => previous + 1)}><RefreshCw size={17} className={records.loading ? 'spin' : ''} /></button></div></div>
      {records.error ? <ErrorNotice message={records.error} retry={() => setRefresh(previous => previous + 1)} /> : records.loading ? <Skeleton rows={10} /> : records.data?.items.length ? <div className="table-scroll"><table className="records-table"><thead><tr><th className="id-column">ID</th><th>音频文件</th><th className="subtitle-column">字幕内容</th><th className="duration-column">时长</th><th className="size-column">大小</th><th className="edit-column">操作</th></tr></thead><tbody>{records.data.items.map(record => <tr key={record.id} className={playing?.key === `dataset:${current.id}:${record.id}` ? 'selected-row' : ''}><td className="mono muted">{String(record.id).padStart(4, '0')}</td><td><div className="audio-cell"><button className="play-button" disabled={!record.audio_available} aria-label={`试听 ${record.audio_name}`} onClick={() => onPlay({ dataset: current, record })}>{playing?.key === `dataset:${current.id}:${record.id}` ? <Volume2 size={15} /> : <Play size={13} fill="currentColor" />}</button><span className="mono filename">{record.audio_name}</span></div></td><td><p className={`subtitle-text ${record.subtitle ? '' : 'missing-subtitle'}`} lang={record.subtitle && /[\u3040-\u30ff]/.test(record.subtitle) ? 'ja' : undefined}>{record.subtitle || '暂无字幕'}</p>{!record.audio_available ? <small className="file-warning">音频文件不可用</small> : null}</td><td className="mono duration-column muted">{duration(record.duration_seconds)}</td><td className="size-column muted">{size(record.size_bytes)}</td><td><button className="icon-button" aria-label={`编辑 ${record.audio_name} 字幕`} onClick={() => onEdit(current, record)}><Pencil size={15} /></button></td></tr>)}</tbody></table></div> : <div className="empty-state"><Search size={32} /><h2>没有匹配的音频记录</h2><p>换一个关键词或字幕筛选条件，继续查找。</p>{q || subtitle !== 'all' ? <button className="button secondary" onClick={() => { setSearch(''); setParams({}) }}>清除筛选</button> : null}</div>}
      <div className="pagination"><span>{total ? `第 ${Math.min((page - 1) * pageSize + 1, total)}–${Math.min(page * pageSize, total)} 条，共 ${number(total)} 条` : '共 0 条记录'}</span><div className="pagination-controls"><label>每页 <select aria-label="每页条数" value={pageSize} onChange={event => change('page_size', event.target.value)}>{[10, 20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</select> 条</label><nav aria-label="明细分页"><button className="page-button" disabled={page <= 1 || records.loading} aria-label="上一页" onClick={() => change('page', String(page - 1))}><ChevronLeft size={16} /></button>{visiblePages.map((value, index) => <span className="page-item" key={value}>{index > 0 && value - visiblePages[index - 1] > 1 ? <span className="ellipsis">…</span> : null}<button className={`page-button ${page === value ? 'active' : ''}`} aria-label={`第 ${value} 页`} aria-current={page === value ? 'page' : undefined} disabled={records.loading} onClick={() => change('page', String(value))}>{value}</button></span>)}<button className="page-button" disabled={page >= pages || records.loading} aria-label="下一页" onClick={() => change('page', String(page + 1))}><ChevronRight size={16} /></button></nav></div></div>
    </section>
  </>
}

function Player({ value, onClose }: { value: Playback; onClose: () => void }) {
  const [failed, setFailed] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const src = apiUrl(value.path)
  useEffect(() => { setFailed(false) }, [src])
  return <section className="audio-player" aria-label="音频播放器"><div className="player-file"><span className="player-icon"><AudioLines size={22} /></span><div><strong className="mono">{value.title}</strong><small>{value.subtitle}{failed ? ' · 音频加载失败，请检查源文件' : ' · 音频试听'}</small></div></div><audio ref={audio} key={src} controls autoPlay preload="metadata" src={src} onError={() => setFailed(true)} aria-label={`播放 ${value.title}`} /><button className="icon-button" aria-label="关闭播放器" onClick={() => { audio.current?.pause(); onClose() }}><X size={19} /></button></section>
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [version, setVersion] = useState(0)
  const health = useApi<{ status: string }>('/health', version)
  const [form, setForm] = useState<Dataset | 'new' | null>(null)
  const [editing, setEditing] = useState<{ dataset: Dataset; record: AudioRecord } | null>(null)
  const [syncing, setSyncing] = useState<Dataset | null>(null)
  const [playing, setPlaying] = useState<Playback | null>(null)
  const [toast, setToast] = useState('')
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer) }, [toast])
  function updated(message: string) { setVersion(previous => previous + 1); setToast(message) }
  return <div className={`app-layout ${playing ? 'has-player' : ''}`}>
    <a className="skip-link" href="#main-content">跳转到主要内容</a>
    <aside className="sidebar"><Link to="/datasets" className="brand"><span className="brand-mark"><AudioLines size={25} /></span><span><strong>声库<span className="brand-period">.</span></strong><small>AUDIO DATASET STUDIO</small></span></Link><div className="sidebar-section-label">工作空间</div><nav className="side-navigation"><NavLink to="/datasets" className="nav-link"><Database size={18} /><span>数据集库</span></NavLink><NavLink to="/audios" className="nav-link"><FileAudio2 size={18} /><span>音频注册</span></NavLink></nav><div className="sidebar-description"><AudioLines size={34} strokeWidth={1.2} /><p>每一段声音，<br />都值得被好好整理。</p></div><div className="sidebar-footer"><span className={`status-dot ${health.error ? 'offline' : ''}`} /><div><strong>{health.loading ? '正在连接…' : health.error ? '后端未连接' : '本地工作空间'}</strong><small>SQLite · 文件保存在本地</small></div></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><span className="mobile-brand"><AudioLines size={21} />声库</span><span className="desktop-crumb">工作空间</span><ChevronRight size={13} /><Link to={location.pathname.startsWith('/audios') ? '/audios' : '/datasets'}>{location.pathname.startsWith('/audios') ? '音频注册' : '数据集'}</Link></div><span className={`connection-status ${health.error ? 'disconnected' : ''}`}><Activity size={14} />{health.loading ? '正在连接' : health.error ? 'API 未连接' : '本地服务已连接'}</span></header>
      <nav className="mobile-navigation" aria-label="工作空间导航"><NavLink to="/datasets">数据集库</NavLink><NavLink to="/audios">音频注册</NavLink></nav><main id="main-content" className="main-content"><Routes><Route path="/datasets" element={<Library version={version} onAdd={() => setForm('new')} onConfigure={setForm} />} /><Route path="/datasets/:id" element={<Details key={location.pathname} version={version} onConfigure={setForm} onSync={setSyncing} onEdit={(dataset, record) => setEditing({ dataset, record })} onPlay={({ dataset, record }) => setPlaying({ key: `dataset:${dataset.id}:${record.id}`, title: record.audio_name, subtitle: dataset.name, path: `/datasets/${dataset.id}/records/${record.id}/audio` })} playing={playing} />} /><Route path="/audios" element={<AudioLibrary onPlay={setPlaying} playingKey={playing?.key} onStop={() => setPlaying(null)} onNotice={setToast} />} /><Route path="*" element={<Navigate to="/datasets" replace />} /></Routes><footer className="page-footer"><span>声库 · 语音数据集管理</span><span>本地管理，专注于数据。</span></footer></main>
    </div>
    {form ? <DatasetForm key={form === 'new' ? 'new' : form.id} dataset={form === 'new' ? undefined : form} onClose={() => setForm(null)} onSaved={dataset => { setForm(null); updated(form === 'new' ? '数据集已添加，音频明细已导入。' : '数据集配置已保存。'); navigate(`/datasets/${dataset.id}`) }} /> : null}
    {editing ? <SubtitleEditor dataset={editing.dataset} record={editing.record} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); updated('字幕已保存到数据库。') }} /> : null}
    {syncing ? <SyncDialog dataset={syncing} onClose={() => setSyncing(null)} onSynced={message => { setSyncing(null); updated(message) }} /> : null}
    {playing ? <Player value={playing} onClose={() => setPlaying(null)} /> : null}
    <div className={`toast ${toast ? 'visible' : ''}`} role="status" aria-live="polite">{toast ? <><Check size={17} />{toast}</> : null}</div>
  </div>
}

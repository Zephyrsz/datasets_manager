import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FileAudio2, Info, LoaderCircle, Pencil, Play, Plus, RefreshCw, Save, Search, Trash2, Volume2 } from 'lucide-react'
import { duration, number, request, size, useApi, type AudioAsset, type AudioConfig, type AudioPage, type Playback } from './api'
import { Drawer, ErrorNotice, Skeleton } from './components'

const kindLabel = { source: '原始长音频', reference: '参考音频' }

function AudioForm({ audio, onClose, onSaved }: { audio?: AudioAsset; onClose: () => void; onSaved: () => void }) {
  const [values, setValues] = useState<AudioConfig>({
    name: audio?.name ?? '', file_path: audio?.file_path ?? '', kind: audio?.kind ?? 'source',
    speaker: audio?.speaker ?? '', language: audio?.language ?? '',
    reference_text: audio?.reference_text ?? '', notes: audio?.notes ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  function field(key: keyof AudioConfig, value: string) { setValues(previous => ({ ...previous, [key]: value })) }
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      await request<AudioAsset>(audio ? `/audios/${audio.id}` : '/audios', {
        method: audio ? 'PUT' : 'POST', body: JSON.stringify(values),
      })
      onSaved()
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Drawer title={audio ? '编辑音频登记' : '注册音频'} subtitle={audio ? `配置 ${audio.name} · ID ${audio.id}` : '登记一个本地文件，为后续处理或声音克隆做准备。'} onClose={onClose} busy={busy}>
    <form className="drawer-form" onSubmit={submit}>
      <div className="drawer-body audio-form">
        <label>音频名称 <span className="required">*</span><input autoFocus required maxLength={160} value={values.name} onChange={event => field('name', event.target.value)} placeholder="例如 井上和访谈 · 原始录音" disabled={busy} /></label>
        <fieldset className="audio-purpose" disabled={busy}><legend>音频用途 <span className="required">*</span></legend>
          <label><input type="radio" name="audio-kind" value="source" checked={values.kind === 'source'} onChange={() => field('kind', 'source')} /><span><strong>原始长音频</strong><small>供后续转写、分句与数据集制作使用</small></span></label>
          <label><input type="radio" name="audio-kind" value="reference" checked={values.kind === 'reference'} onChange={() => field('kind', 'reference')} /><span><strong>参考音频</strong><small>供语音克隆与 TTS 模型使用</small></span></label>
        </fieldset>
        <label>音频文件路径 <span className="required">*</span><input className="mono" required maxLength={4096} value={values.file_path} onChange={event => field('file_path', event.target.value)} placeholder="/Users/你的用户名/Audio/recording.m4a" disabled={busy} /><small>填写后端服务器上的绝对路径。支持 M4A、WAV、MP3、FLAC 等音频；保存时读取文件信息。</small></label>
        {values.kind === 'reference' ? <section className="reference-fields" aria-label="参考音频信息">
          <h3>参考信息 <span className="optional">选填</span></h3>
          <div className="audio-field-pair"><label>说话人<input maxLength={160} value={values.speaker ?? ''} onChange={event => field('speaker', event.target.value)} placeholder="姓名或声音名称" disabled={busy} /></label><label>语言<input maxLength={80} value={values.language ?? ''} onChange={event => field('language', event.target.value)} placeholder="例如 ja、zh、en" disabled={busy} /></label></div>
          <label>音频对应文本<textarea rows={4} maxLength={20000} value={values.reference_text ?? ''} onChange={event => field('reference_text', event.target.value)} placeholder="填写这段音频实际说出的内容" disabled={busy} /><small>部分克隆模型需要与音频一致的原文；也可以稍后补充。登记时不自动转写。</small></label>
        </section> : null}
        <label>备注 <span className="optional">选填</span><textarea className="audio-notes" rows={3} maxLength={4000} value={values.notes ?? ''} onChange={event => field('notes', event.target.value)} placeholder="记录来源、内容或使用说明" disabled={busy} /></label>
        <div className="form-note"><Info size={17} /><p>音频保留在原位置。每个路径只登记一次，每条音频只能选择一种用途；后续可编辑配置。</p></div>
        {error ? <ErrorNotice message={error} /> : null}
      </div>
      <footer className="drawer-footer"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>取消</button><button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}{busy ? '正在检查并保存…' : audio ? '保存配置' : '注册音频'}</button></footer>
    </form>
  </Drawer>
}

function RemoveAudio({ audio, onClose, onRemoved }: { audio: AudioAsset; onClose: () => void; onRemoved: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function remove() {
    setBusy(true); setError('')
    try { await request(`/audios/${audio.id}`, { method: 'DELETE' }); onRemoved() }
    catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Drawer title="移除音频登记" subtitle={audio.name} onClose={onClose} compact busy={busy}>
    <div className="drawer-body"><p className="confirm-copy">移除后，此音频将不再出现在注册列表中。原始音频文件会保留，你可以随时重新登记。</p>{error ? <ErrorNotice message={error} /> : null}</div>
    <footer className="drawer-footer"><button className="button secondary" onClick={onClose} disabled={busy}>取消</button><button className="button primary" onClick={remove} disabled={busy}>{busy ? '正在移除…' : '移除登记'}</button></footer>
  </Drawer>
}

export default function AudioLibrary({ onPlay, playingKey, onStop, onNotice }: {
  onPlay: (value: Playback) => void; playingKey?: string; onStop: () => void; onNotice: (message: string) => void
}) {
  const [params, setParams] = useSearchParams()
  const kind = ['source', 'reference'].includes(params.get('kind') ?? '') ? params.get('kind')! : 'all'
  const page = Math.max(1, Math.min(10000000, Number(params.get('page')) || 1))
  const q = params.get('q') ?? ''
  const [search, setSearch] = useState(q)
  const [reload, setReload] = useState(0)
  const [form, setForm] = useState<AudioAsset | 'new' | null>(null)
  const [removing, setRemoving] = useState<AudioAsset | null>(null)
  const query = new URLSearchParams({ kind, page: String(page), page_size: '20', q })
  const source = useApi<AudioPage>(`/audios?${query}`, reload)
  const total = source.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / 20))
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
  useEffect(() => {
    if (!source.loading && source.data && page > pages) {
      setParams(previous => { const next = new URLSearchParams(previous); next.set('page', String(pages)); return next }, { replace: true })
    }
  }, [source.loading, source.data, page, pages, setParams])
  function changeKind(value: string) {
    setParams(previous => { const next = new URLSearchParams(previous); next.delete('page'); next.set('kind', value); return next })
  }
  return <>
    <div className="page-heading"><div><h1>音频注册</h1><p>管理单个音频，为后续处理和语音克隆保留可用素材。</p></div><button className="button primary" onClick={() => setForm('new')}><Plus size={18} />注册音频</button></div>
    <section className="library-panel" aria-label="已注册音频">
      <div className="audio-filter-bar"><div className="audio-filter-tabs" role="group" aria-label="按音频用途筛选">{[['all', '全部音频'], ['source', '原始长音频'], ['reference', '参考音频']].map(([value, label]) => <button key={value} className={kind === value ? 'active' : ''} aria-pressed={kind === value} onClick={() => changeKind(value)}>{label}</button>)}</div><span>{number(total)} 条登记</span></div>
      <div className="table-toolbar"><label className="search-input"><Search size={17} /><input aria-label="搜索已注册音频" placeholder="搜索名称、路径、说话人或文本…" value={search} maxLength={500} onChange={event => setSearch(event.target.value)} /></label><button className="icon-button" aria-label="刷新音频登记" onClick={() => setReload(value => value + 1)} disabled={source.loading}><RefreshCw size={17} className={source.loading ? 'spin' : ''} /></button></div>
      {source.error ? <ErrorNotice message={source.error} retry={() => setReload(value => value + 1)} /> : source.loading ? <Skeleton rows={4} /> : source.data?.items.length ? <div className="table-scroll"><table className="audio-assets-table"><thead><tr><th>音频与文件位置</th><th>用途</th><th>参考信息</th><th>音频信息</th><th>操作</th></tr></thead><tbody>{source.data.items.map(audio => <tr key={audio.id} className={playingKey === `audio:${audio.id}` ? 'selected-row' : ''}>
        <td><div className="asset-title"><FileAudio2 size={19} /><strong title={audio.name}>{audio.name}</strong></div><code className="asset-path" title={audio.file_path}>{audio.file_path}</code><small className={`asset-status ${audio.file_available ? '' : 'file-warning'}`}><i className={`status-dot ${audio.file_available ? '' : 'offline'}`} />{audio.file_available ? `ID ${audio.id} · ${audio.codec}` : '文件不可用，请编辑路径'}</small></td>
        <td><span className={`audio-kind ${audio.kind}`}>{kindLabel[audio.kind]}</span></td>
        <td><div className="asset-reference"><strong>{audio.speaker || (audio.kind === 'source' ? '后续处理素材' : '未填写说话人')}{audio.language ? ` · ${audio.language}` : ''}</strong><p title={audio.reference_text || audio.notes || undefined}>{audio.reference_text || audio.notes || (audio.kind === 'reference' ? '可编辑补充参考文本' : '可用于转写与分句')}</p></div></td>
        <td><span className="mono">{duration(audio.duration_seconds)}</span><small className="asset-meta">{size(audio.size_bytes)} · {audio.sample_rate / 1000} kHz<br />{audio.channels === 1 ? '单声道' : `${audio.channels} 声道`}</small></td>
        <td><div className="row-actions"><button className="icon-button" disabled={!audio.file_available} aria-label={`试听 ${audio.name}`} onClick={() => onPlay({ key: `audio:${audio.id}`, title: audio.name, subtitle: kindLabel[audio.kind], path: `/audios/${audio.id}/file` })}>{playingKey === `audio:${audio.id}` ? <Volume2 size={16} /> : <Play size={15} />}</button><button className="icon-button" aria-label={`编辑 ${audio.name}`} onClick={() => setForm(audio)}><Pencil size={15} /></button><button className="icon-button" aria-label={`移除 ${audio.name} 登记`} onClick={() => setRemoving(audio)}><Trash2 size={15} /></button></div></td>
      </tr>)}</tbody></table></div> : <div className="empty-state"><FileAudio2 size={36} /><h2>{q || kind !== 'all' ? '没有匹配的音频' : '先登记一段声音'}</h2><p>{q || kind !== 'all' ? '试试其他关键词，或切换音频用途。' : '添加原始长音频供后续处理，或保存用于语音克隆的参考音频。'}</p><button className="button secondary" onClick={q || kind !== 'all' ? () => { setSearch(''); setParams({}) } : () => setForm('new')}>{q || kind !== 'all' ? '清除筛选' : '注册第一个音频'}</button></div>}
      <div className="pagination"><span>{total ? `第 ${(page - 1) * 20 + 1}–${Math.min(page * 20, total)} 条，共 ${number(total)} 条` : '共 0 条登记'}</span><nav className="audio-pager" aria-label="音频登记分页"><button className="page-button" disabled={page <= 1 || source.loading} aria-label="上一页音频" onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('page', String(page - 1)); return next })}><ChevronLeft size={16} /></button><span>{page} / {pages}</span><button className="page-button" disabled={page >= pages || source.loading} aria-label="下一页音频" onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('page', String(page + 1)); return next })}><ChevronRight size={16} /></button></nav></div>
    </section>
    <div className="workspace-note"><Info size={15} /><p>原始长音频用于后续处理；参考音频用于语音克隆与 TTS。每条登记仅有一种用途，音频文件保留在原位置。</p></div>
    {form ? <AudioForm key={form === 'new' ? 'new' : form.id} audio={form === 'new' ? undefined : form} onClose={() => setForm(null)} onSaved={() => { if (form !== 'new' && playingKey === `audio:${form.id}`) onStop(); setForm(null); setReload(value => value + 1); onNotice(form === 'new' ? '音频已注册。' : '音频配置已保存。') }} /> : null}
    {removing ? <RemoveAudio audio={removing} onClose={() => setRemoving(null)} onRemoved={() => { if (playingKey === `audio:${removing.id}`) onStop(); setRemoving(null); setReload(value => value + 1); onNotice('音频登记已移除，原始文件已保留。') }} /> : null}
  </>
}

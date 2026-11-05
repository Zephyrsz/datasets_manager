import { useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react'
import { AlertCircle, Check, FolderOpen, Info, LoaderCircle, RefreshCw, Save, X } from 'lucide-react'
import { request, type Dataset, type DatasetConfig, type AudioRecord } from './api'

export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error-notice" role="alert"><AlertCircle size={18} /><span>{message}</span>{retry ? <button className="text-button" onClick={retry}>重试</button> : null}</div>
}

export function Skeleton({ rows = 5 }: { rows?: number }) {
  return <div className="skeleton-list" aria-label="正在加载" role="status">{Array.from({ length: rows }, (_, i) => <div className="skeleton-row" key={i}><i /><span /><b /></div>)}</div>
}

export function Drawer({ title, subtitle, children, onClose, busy = false, compact = false }: {
  title: string; subtitle: string; children: ReactNode; onClose: () => void; busy?: boolean; compact?: boolean
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog className={`drawer-dialog ${compact ? 'compact-dialog' : ''}`} ref={dialog}
    aria-labelledby="drawer-title" aria-describedby="drawer-subtitle"
    onCancel={event => { event.preventDefault(); if (!busy) onClose() }}
    onClick={event => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <div className="drawer-panel">
      <header className="drawer-header"><div><h2 id="drawer-title">{title}</h2><p id="drawer-subtitle">{subtitle}</p></div><button type="button" className="icon-button" aria-label="关闭面板" disabled={busy} onClick={onClose}><X size={20} /></button></header>
      {children}
    </div>
  </dialog>
}

export function DatasetForm({ dataset, onClose, onSaved }: { dataset?: Dataset; onClose: () => void; onSaved: (dataset: Dataset) => void }) {
  const [values, setValues] = useState<DatasetConfig>({
    name: dataset?.name ?? '', storage_dir: dataset?.storage_dir ?? '',
    audio_subdir: dataset?.audio_subdir ?? 'wav', transcript_path: dataset?.transcript_path ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  function field(key: keyof DatasetConfig, value: string) { setValues(previous => ({ ...previous, [key]: value })) }
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const result = await request<Dataset>(dataset ? `/datasets/${dataset.id}` : '/datasets', {
        method: dataset ? 'PUT' : 'POST', body: JSON.stringify({ ...values, transcript_path: values.transcript_path?.trim() || null }),
      })
      onSaved(result)
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Drawer title={dataset ? '数据集配置' : '添加数据集'} subtitle={dataset ? `正在配置 ${dataset.name} · ID ${dataset.id}` : '连接本地语料，将音频与字幕整理到声库。'} busy={busy} onClose={onClose}>
    <form className="drawer-form" onSubmit={submit}>
      <div className="drawer-body">
        <div className="form-section-label">基本信息</div>
        <label>数据集名称 <span className="required">*</span><input autoFocus required maxLength={160} value={values.name} onChange={event => field('name', event.target.value)} placeholder="例如 jsut/basic5000" disabled={busy} /><small>使用容易识别的唯一名称，后续可随时修改。</small></label>
        <div className="form-section-label second">文件位置</div>
        <label>数据集根目录 <span className="required">*</span><div className="input-with-icon"><FolderOpen size={17} /><input required className="mono" value={values.storage_dir} onChange={event => field('storage_dir', event.target.value)} placeholder="/path/to/your/dataset" disabled={busy} /></div><small>填写后端服务器上的绝对路径。</small></label>
        <label>音频子目录 <span className="required">*</span><input required className="mono" value={values.audio_subdir} onChange={event => field('audio_subdir', event.target.value)} placeholder="wav" disabled={busy} /><small>相对于根目录，当前支持此目录中的 WAV 文件。根目录本身填写「.」。</small></label>
        <label>字幕清单 <span className="optional">选填</span><input className="mono" value={values.transcript_path ?? ''} onChange={event => field('transcript_path', event.target.value)} placeholder="transcript_utf8.txt" disabled={busy} /><small>绝对路径或相对根目录的路径。UTF-8 编码，每行「音频标识:字幕」。</small></label>
        <div className="form-note"><Info size={17} /><p>{dataset ? '保存只更新配置，不修改已有字幕。需要从源文件更新明细时，请在数据集页面执行「重新导入」。' : '提交后将校验目录并导入音频记录。字幕清单留空时，字幕保存为空；提供清单时，音频与字幕必须一一对应。'}</p></div>
        {error ? <ErrorNotice message={error} /> : null}
      </div>
      <footer className="drawer-footer"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>取消</button><button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={17} className="spin" /> : dataset ? <Save size={17} /> : <Check size={17} />}{busy ? (dataset ? '正在保存…' : '校验并导入中…') : (dataset ? '保存配置' : '添加并导入')}</button></footer>
    </form>
  </Drawer>
}

export function SubtitleEditor({ record, dataset, onClose, onSaved }: { record: AudioRecord; dataset: Dataset; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState(record.subtitle ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await request(`/datasets/${dataset.id}/records/${record.id}`, { method: 'PATCH', body: JSON.stringify({ subtitle: value || null }) })
      onSaved()
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Drawer title="编辑字幕" subtitle={record.audio_name} onClose={onClose} busy={busy}>
    <form className="drawer-form" onSubmit={save}><div className="drawer-body">
      <div className="record-reference"><span className="muted">记录 ID</span><code>#{record.id}</code><span className="muted">所属数据集</span><strong>{dataset.name}</strong></div>
      <label>字幕内容<textarea autoFocus rows={9} value={value} maxLength={20000} onChange={event => setValue(event.target.value)} disabled={busy} placeholder="输入对应音频的字幕，留空表示暂无字幕。" /><small>保留原文语言与标点。留空将存为 NULL。</small></label>
      <div className="form-note"><Info size={17} /><p>修改仅保存在数据库中，不改写原始字幕文件。重新导入源文件时，手动修改的内容可能被覆盖。</p></div>
      {error ? <ErrorNotice message={error} /> : null}
    </div><footer className="drawer-footer"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>取消</button><button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}保存字幕</button></footer></form>
  </Drawer>
}

export function SyncDialog({ dataset, onClose, onSynced }: { dataset: Dataset; onClose: () => void; onSynced: (message: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function sync() {
    setBusy(true); setError('')
    try {
      const result = await request<{ inserted_records: number; updated_records: number }>(`/datasets/${dataset.id}/sync`, { method: 'POST' })
      onSynced(`导入完成：新增 ${result.inserted_records} 条，更新 ${result.updated_records} 条。`)
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Drawer title="重新导入数据集" subtitle={dataset.name} onClose={onClose} busy={busy} compact>
    <div className="drawer-body"><p className="confirm-copy">将重新读取音频目录与字幕清单，添加新记录并同步字幕。已有记录 ID 保持不变。</p><div className="warning-note"><AlertCircle size={18} /><p>源字幕会覆盖数据库中的手动修改。如果未配置字幕清单，已有字幕会被清空。此操作不修改源文件。</p></div>{error ? <ErrorNotice message={error} /> : null}</div>
    <footer className="drawer-footer"><button className="button secondary" onClick={onClose} disabled={busy}>取消</button><button className="button primary" onClick={sync} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}{busy ? '导入中…' : '确认重新导入'}</button></footer>
  </Drawer>
}

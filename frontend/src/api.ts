import { useEffect, useState } from 'react'

export interface Dataset {
  id: number
  name: string
  storage_dir: string
  audio_subdir: string
  transcript_path: string | null
  created_at: string
  detail_table: string
  record_count: number
  subtitle_count: number
  storage_available: boolean
}

export interface AudioRecord {
  id: number
  audio_name: string
  subtitle: string | null
  audio_available: boolean
  size_bytes: number | null
  duration_seconds: number | null
}

export interface RecordPage {
  items: AudioRecord[]
  total: number
  page: number
  page_size: number
}

export interface DatasetConfig {
  name: string
  storage_dir: string
  audio_subdir: string
  transcript_path: string | null
}

export interface AudioConfig {
  name: string
  file_path: string
  kind: 'source' | 'reference'
  speaker: string | null
  language: string | null
  reference_text: string | null
  notes: string | null
}

export interface AudioAsset extends AudioConfig {
  id: number
  duration_seconds: number
  size_bytes: number
  sample_rate: number
  channels: number
  codec: string
  created_at: string
  updated_at: string
  file_available: boolean
}

export interface AudioPage {
  items: AudioAsset[]
  total: number
  page: number
  page_size: number
}

export interface Playback {
  key: string
  title: string
  subtitle: string
  path: string
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? '/api'

export function apiUrl(path: string) { return `${API_BASE}${path}` }

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
    })
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new Error('无法连接后端服务，请确认 API 已启动后重试。')
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(typeof error.detail === 'string' ? error.detail : `请求未完成（${response.status}），请检查输入后重试。`)
  }
  return response.json() as Promise<T>
}

export function useApi<T>(path: string | null, version = 0) {
  const [state, setState] = useState<{ data?: T; error: string; loading: boolean }>({ error: '', loading: true })
  useEffect(() => {
    if (!path) { setState({ error: '', loading: false }); return }
    const controller = new AbortController()
    setState(previous => ({ ...previous, error: '', loading: true }))
    request<T>(path, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setState({ data, error: '', loading: false }) })
      .catch(error => { if (!controller.signal.aborted) setState({ error: error.message, loading: false }) })
    return () => controller.abort()
  }, [path, version])
  return state
}

export function number(value: number) { return value.toLocaleString('zh-CN') }
export function duration(value: number | null) {
  if (value === null) return '—'
  const total = Math.floor(value)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
export function size(value: number | null) {
  if (value === null) return '—'
  return value < 1048576 ? `${(value / 1024).toFixed(0)} KB` : `${(value / 1048576).toFixed(1)} MB`
}

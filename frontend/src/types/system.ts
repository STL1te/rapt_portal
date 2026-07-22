export type SystemJob = {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  created_at: string
  started_at: string | null
  finished_at: string | null
  result: Record<string, unknown> | null
  error: string | null
}

export type SystemJobHistoryPage = {
  items: SystemJob[]
  page: number
  page_size: number
  total: number
}

export type SyncResult = {
  status: string
  hydrometers?: number
  active_sessions?: number
  count?: number
}

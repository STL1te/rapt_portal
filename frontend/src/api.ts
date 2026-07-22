export type Hydrometer = {
  id: string
  name: string | null
  gravity: number | null
  temperature: number | null
  battery: number | null
  rssi: number | null
  active_session_id: string | null
  updated_at: string | null
}

export type Session = {
  id: string
  hydrometer_id: string
  name: string | null
  yeast_id: string | null
  yeast_name: string | null
  yeast_product_id: string | null
  yeast_attenuation: number | null
  yeast_min_temperature: number | null
  yeast_max_temperature: number | null
  target_final_gravity: number | null
  start_date: string | null
  end_date: string | null
  original_gravity: number | null
  final_gravity: number | null
  current_gravity: number | null
  active: boolean
  abv: number | null
  attenuation: number | null
}

// RAPT Pill (hydrometer) telemetry — device-specific, not a shared base type
export type HydrometerTelemetryPoint = {
  timestamp: string
  gravity: number | null
  gravity_velocity: number | null
  temperature: number | null
  battery: number | null
  rssi: number | null
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

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

export type BrewZilla = {
  id: string
  name: string | null
  temperature: number | null
  target_temperature: number | null
  heating_enabled: boolean | null
  heating_utilisation: number | null
  pump_enabled: boolean | null
  pump_utilisation: number | null
  rssi: number | null
  active_session_id: string | null
  updated_at: string | null
}

export type BrewStep = {
  id?: string | null
  order: number
  name: string | null
  controlType: string | null
  endType: string | null
  durationType: string | null
  temperature: number | null
  length: number | null // seconds
  heatingUtilisation: number | null
}

export type BrewProfile = {
  name: string | null
  steps: BrewStep[]
  alerts: unknown[] | null
}

export type BrewSession = {
  id: string
  brewzilla_id: string
  name: string | null
  profile_id: string | null
  start_date: string | null
  end_date: string | null
  active: boolean
  current_step_id: string | null
  current_step_name: string | null
  current_step_order: number | null
  current_step_progress: number | null
  session_progress: number | null
  total_steps: number | null
  last_telemetry_at: string | null
  latest_temperature: number | null
  latest_target_temperature: number | null
  latest_wort_temperature: number | null
  latest_heating_run_time: number | null
  latest_aux_run_time: number | null
  delta_to_target: number | null
  wort_delta_to_target: number | null
  step_target_temperature: number | null
  profile?: BrewProfile | null
}

export type BrewTelemetryPoint = {
  timestamp: string
  temperature: number | null // element/kettle temp
  target_temperature: number | null
  control_device_temperature: number | null // external probe (wort)
  heating_run_time: number | null
  heating_starts: number | null
  auxillary_run_time: number | null
  auxillary_starts: number | null
  profile_step_id: string | null
  profile_step_progress: number | null
  profile_session_time: number | null
}

export type Yeast = {
  id: string
  name: string | null
  product_id: string | null
  laboratory: string | null
  type: string | null
  form: string | null
  min_temperature: number | null
  max_temperature: number | null
  flocculation: string | null
  attenuation: number | null
  notes: string | null
  is_global: boolean
  archived: boolean
}

export type SyncResult = {
  status: string
  hydrometers?: number
  active_sessions?: number
  count?: number
}

export const getHydrometers = () => get<Hydrometer[]>('/api/hydrometers')
export const getHydrometerSessions = (hydrometerId: string) =>
  get<Session[]>(`/api/hydrometers/${hydrometerId}/sessions`)
export const getHydrometerSession = (sessionId: string) =>
  get<Session>(`/api/hydrometer-sessions/${sessionId}`)
export const getHydrometerTelemetry = (sessionId: string) =>
  get<HydrometerTelemetryPoint[]>(`/api/hydrometer-sessions/${sessionId}/telemetry`)

export const getBrewzillas = () => get<BrewZilla[]>('/api/brewzillas')
export const getBrewSessions = (brewzillaId: string, includeShort = false) =>
  get<BrewSession[]>(`/api/brewzillas/${brewzillaId}/sessions?include_short=${includeShort}`)
export const getBrewSession = (sessionId: string) =>
  get<BrewSession>(`/api/brew-sessions/${sessionId}`)
export const getBrewTelemetry = (sessionId: string) =>
  get<BrewTelemetryPoint[]>(`/api/brew-sessions/${sessionId}/telemetry`)

export const getYeasts = () => get<Yeast[]>('/api/yeasts')
export const triggerSync = () => post<SystemJob>('/api/sync')
export const triggerPortalDataSync = (portalToken: string, force = false) =>
  post<SystemJob>('/api/portal_data_sync', { portal_token: portalToken, force })
export const triggerYeastSync = (portalToken: string) =>
  post<SystemJob>('/api/sync_yeasts', { portal_token: portalToken })
export const getActiveSystemJobs = () => get<SystemJob[]>('/api/system-jobs')
export const getSystemJobHistory = (page = 1, pageSize = 20) =>
  get<SystemJobHistoryPage>(`/api/system-jobs/history?page=${page}&page_size=${pageSize}`)
export const getSystemJob = (jobId: string) => get<SystemJob>(`/api/system-jobs/${jobId}`)

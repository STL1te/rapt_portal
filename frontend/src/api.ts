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
  profile?: BrewProfile | null
}

export type BrewTelemetryPoint = {
  timestamp: string
  temperature: number | null // element/kettle temp
  target_temperature: number | null
  min_target_temperature: number | null
  max_target_temperature: number | null
  control_device_temperature: number | null // external probe (wort)
  heating_run_time: number | null
  heating_starts: number | null
  auxillary_run_time: number | null
  auxillary_starts: number | null
  profile_step_id: string | null
  profile_step_progress: number | null
  profile_session_time: number | null
}

export const getHydrometers = () => get<Hydrometer[]>('/api/hydrometers')
export const getSessions = (hydrometerId: string) =>
  get<Session[]>(`/api/hydrometers/${hydrometerId}/sessions`)
export const getSession = (sessionId: string) =>
  get<Session>(`/api/hydrometer-sessions/${sessionId}`)
export const getTelemetry = (sessionId: string) =>
  get<HydrometerTelemetryPoint[]>(`/api/hydrometer-sessions/${sessionId}/telemetry`)

export const getBrewzillas = () => get<BrewZilla[]>('/api/brewzillas')
export const getBrewSessions = (brewzillaId: string) =>
  get<BrewSession[]>(`/api/brewzillas/${brewzillaId}/sessions`)
export const getBrewSession = (sessionId: string) =>
  get<BrewSession>(`/api/brew-sessions/${sessionId}`)
export const getBrewTelemetry = (sessionId: string) =>
  get<BrewTelemetryPoint[]>(`/api/brew-sessions/${sessionId}/telemetry`)

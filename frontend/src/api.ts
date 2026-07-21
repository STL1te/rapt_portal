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
  active: boolean
  abv: number | null
  attenuation: number | null
}

export type TelemetryPoint = {
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

export const getHydrometers = () => get<Hydrometer[]>('/api/hydrometers')
export const getSessions = (hydrometerId: string) =>
  get<Session[]>(`/api/hydrometers/${hydrometerId}/sessions`)
export const getSession = (sessionId: string) =>
  get<Session>(`/api/sessions/${sessionId}`)
export const getTelemetry = (sessionId: string) =>
  get<TelemetryPoint[]>(`/api/sessions/${sessionId}/telemetry`)

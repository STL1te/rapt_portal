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

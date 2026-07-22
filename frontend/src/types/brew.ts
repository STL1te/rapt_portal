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

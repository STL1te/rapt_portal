// RAPT profile enums, mirrored from backend/features/profiles/enums.py (the
// canonical source — the recipe AI-wizard lives on the backend). Keep in sync.
// `as const` arrays so the union types below and any runtime consumer share them.
export const CONTROL_TYPES = ['Target', 'Ramp', 'FreeRise'] as const
export const END_TYPES = [
  'Duration',
  'Temperature',
  'Gravity',
  'GravityVelocity',
  'Manual',
] as const
export const DURATION_TYPES = [
  'Start',
  'Temperature',
  'Gravity',
  'GravityVelocity',
  'Manual',
] as const
export const VALUE_OPERATORS = ['Equals', 'LessThan', 'GreaterThan'] as const
export const ALERT_TRIGGERS = [
  'StepStart',
  'StepEnd',
  'Temperature',
  'Gravity',
  'GravityVelocity',
  'Duration',
] as const

export type ControlType = (typeof CONTROL_TYPES)[number]
export type EndType = (typeof END_TYPES)[number]
export type DurationType = (typeof DURATION_TYPES)[number]
export type ValueOperator = (typeof VALUE_OPERATORS)[number]
export type AlertTrigger = (typeof ALERT_TRIGGERS)[number]

export type ProfileAlert = {
  id: string | null
  alertText: string | null
  trigger: AlertTrigger | null
  operator: ValueOperator | null
  temperature: number | null
  gravity: number | null
}

export type ProfileStepAlert = ProfileAlert & {
  length: number | null
}

// Alerts are stored in RAPT's own order; this sorts them into firing order:
// step start → timed offset → condition (no fixed time) → step end.
const ALERT_ORDER: Record<AlertTrigger, number> = {
  StepStart: 0,
  Duration: 1,
  Temperature: 2,
  Gravity: 2,
  GravityVelocity: 2,
  StepEnd: 3,
}
export function byTriggerTime(a: ProfileAlert, b: ProfileAlert): number {
  const rank = (x: ProfileAlert) => (x.trigger ? ALERT_ORDER[x.trigger] : 9)
  const len = (x: ProfileAlert) => (x as ProfileStepAlert).length ?? 0
  return rank(a) - rank(b) || len(a) - len(b)
}

export type ProfileStep = {
  id: string | null
  name: string | null
  order: number
  controlType: ControlType | null
  endType: EndType | null
  durationType: DurationType | null
  operator: ValueOperator | null
  length: number | null // seconds
  temperature: number | null
  minTemperature: number | null
  maxTemperature: number | null
  gravity: number | null
  pumpEnabled: boolean | null
  pumpUtilisation: number | null
  heatingUtilisation: number | null
  pidEnabled: boolean | null
  sensorDifferential: number | null
  alerts: ProfileStepAlert[]
}

// list view (no steps)
export type ProfileListItem = {
  id: string
  name: string | null
  description: string | null
  public: boolean
  rating: number | null
  profile_type_id: string | null
  profile_type_name: string | null
  step_count: number
  archived: boolean
  draft: boolean
  updated_at: string | null
}

export type Profile = ProfileListItem & {
  steps: ProfileStep[]
  alerts: ProfileAlert[]
}

export type ProfileType = { id: string; name: string | null }

// Mirrors backend/features/recipes/brewzilla_overrides.py BrewZillaOverrides —
// device-process choices for compiling an imported recipe. All optional: an unset
// field falls back to the compiler's own default.
export type BrewZillaOverrides = {
  include_temperature_alerts?: boolean
  include_sparge?: boolean
  include_mash_out?: boolean
  heat_power_pct?: number
  rest_power_pct?: number
  mash_pid_enabled?: boolean
  mash_in_temperature_c?: number
}

export type RecipeSourceFormat = 'brewfather_json' | 'beerxml' | 'beerjson'

// editor payload for create/update (backend ProfileIn)
export type ProfileInput = {
  name: string
  description: string | null
  public: boolean
  profile_type_id: string | null
  profile_type_name: string | null
  steps: ProfileStep[]
  alerts: ProfileAlert[]
}

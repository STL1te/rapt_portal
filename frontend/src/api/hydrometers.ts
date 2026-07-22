import type { Hydrometer, HydrometerTelemetryPoint, Session } from '@/types'
import { get } from './client'

export const getHydrometers = () => get<Hydrometer[]>('/api/hydrometers')
export const getHydrometerSessions = (hydrometerId: string) =>
  get<Session[]>(`/api/hydrometers/${hydrometerId}/sessions`)
export const getHydrometerSession = (sessionId: string) =>
  get<Session>(`/api/hydrometer-sessions/${sessionId}`)
export const getHydrometerTelemetry = (sessionId: string) =>
  get<HydrometerTelemetryPoint[]>(`/api/hydrometer-sessions/${sessionId}/telemetry`)

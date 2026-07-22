import type { BrewSession, BrewTelemetryPoint, BrewZilla } from '@/types'
import { get } from './client'

export const getBrewzillas = () => get<BrewZilla[]>('/api/brewzillas')
export const getBrewSessions = (brewzillaId: string, includeShort = false) =>
  get<BrewSession[]>(`/api/brewzillas/${brewzillaId}/sessions?include_short=${includeShort}`)
export const getBrewSession = (sessionId: string) =>
  get<BrewSession>(`/api/brew-sessions/${sessionId}`)
export const getBrewTelemetry = (sessionId: string) =>
  get<BrewTelemetryPoint[]>(`/api/brew-sessions/${sessionId}/telemetry`)

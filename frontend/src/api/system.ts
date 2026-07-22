import type { SystemJob, SystemJobHistoryPage } from '@/types'
import { get, post } from './client'

export const triggerSync = () => post<SystemJob>('/api/sync')
export const triggerPortalDataSync = (portalToken: string, force = false) =>
  post<SystemJob>('/api/portal_data_sync', { portal_token: portalToken, force })
export const triggerYeastSync = (portalToken: string) =>
  post<SystemJob>('/api/sync_yeasts', { portal_token: portalToken })
export const triggerProfileSync = (portalToken: string) =>
  post<SystemJob>('/api/sync_profiles', { portal_token: portalToken })
export const getActiveSystemJobs = () => get<SystemJob[]>('/api/system-jobs')
export const getSystemJobHistory = (page = 1, pageSize = 20) =>
  get<SystemJobHistoryPage>(`/api/system-jobs/history?page=${page}&page_size=${pageSize}`)
export const getSystemJob = (jobId: string) => get<SystemJob>(`/api/system-jobs/${jobId}`)

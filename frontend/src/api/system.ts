import type { SystemJob, SystemJobHistoryPage } from '@/types'
import { get, post } from './client'

export const triggerSync = () => post<SystemJob>('/api/sync')
export const triggerPortalDataSync = (force = false) =>
  post<SystemJob>('/api/portal_data_sync', { force })
export const triggerYeastSync = () => post<SystemJob>('/api/sync_yeasts')
export const triggerProfileSync = () => post<SystemJob>('/api/sync_profiles')
export const getRaptAuth = () => get<{ connected: boolean }>('/api/rapt_auth')
export const getRaptAuthUrl = () => get<{ url: string }>('/api/rapt_auth/url')
export const connectRaptAuth = (code: string) =>
  post<{ connected: boolean }>('/api/rapt_auth', { code })
export const getActiveSystemJobs = () => get<SystemJob[]>('/api/system-jobs')
export const getSystemJobHistory = (page = 1, pageSize = 20) =>
  get<SystemJobHistoryPage>(`/api/system-jobs/history?page=${page}&page_size=${pageSize}`)
export const getSystemJob = (jobId: string) => get<SystemJob>(`/api/system-jobs/${jobId}`)

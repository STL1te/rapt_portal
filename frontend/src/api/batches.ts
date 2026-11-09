import type { Batch, BatchInput } from '@/types'
import { del, get, post, put } from './client'

export const getBatches = () => get<Batch[]>('/api/batches')
export const getBatch = (id: number | string) => get<Batch>(`/api/batches/${id}`)
export const createBatch = (input: BatchInput) => post<Batch>('/api/batches', input)
export const updateBatch = (id: number, input: BatchInput) =>
  put<Batch>(`/api/batches/${id}`, input)
export const deleteBatch = (id: number) => del(`/api/batches/${id}`)
export const addBatchVolume = (id: number, recorded_on: string, volume_l: number) =>
  post<Batch>(`/api/batches/${id}/volumes`, { recorded_on, volume_l })
export const deleteBatchVolume = (id: number, volumeId: number) =>
  del<Batch>(`/api/batches/${id}/volumes/${volumeId}`)

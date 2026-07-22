import type { Yeast } from '@/types'
import { get } from './client'

export const getYeasts = () => get<Yeast[]>('/api/yeasts')

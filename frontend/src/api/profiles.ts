import type { Profile, ProfileListItem } from '@/types'
import { get } from './client'

export const getProfiles = () => get<ProfileListItem[]>('/api/profiles')
export const getProfile = (id: string) => get<Profile>(`/api/profiles/${id}`)

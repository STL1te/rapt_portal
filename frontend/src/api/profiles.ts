import type {
  BrewZillaOverrides,
  Profile,
  ProfileInput,
  ProfileListItem,
  ProfileType,
  RecipeSourceFormat,
  SystemJob,
} from '@/types'
import { get, post } from './client'

export const getProfiles = () => get<ProfileListItem[]>('/api/profiles')
export const getProfile = (id: string) => get<Profile>(`/api/profiles/${id}`)
export const getProfileTypes = () => get<ProfileType[]>('/api/profile-types')

export const createProfile = (input: ProfileInput) => post<Profile>('/api/profiles', input)

export async function updateProfile(id: string, input: ProfileInput): Promise<Profile> {
  const r = await fetch(`/api/profiles/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export async function deleteProfile(id: string): Promise<void> {
  const r = await fetch(`/api/profiles/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
}

export const uploadProfile = (id: string, portalToken: string) =>
  post<SystemJob>(`/api/profiles/${id}/upload`, { portal_token: portalToken })

export const importProfile = (
  format: RecipeSourceFormat,
  content: string,
  overrides?: BrewZillaOverrides,
  // The server composes one alert text per rest — it is the side that knows how many
  // rests the file has and what each is called.
  options: { restEndAlerts?: boolean } = {},
) =>
  post<ProfileInput>('/api/profiles/import', {
    format,
    content,
    overrides,
    rest_end_alerts: options.restEndAlerts ?? false,
  })

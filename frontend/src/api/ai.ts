import type { AiConversation, AiSubjectType, AiTurn } from '@/types'
import type { ProfileInput } from '@/types'
import { post } from './client'

export const openAiConversation = (
  subjectType: AiSubjectType,
  subjectId: string,
  locale: string,
  signal?: AbortSignal,
) =>
  post<AiConversation>(
    '/api/ai/conversations/open',
    { subject_type: subjectType, subject_id: subjectId, locale },
    { signal },
  )

export const sendAiMessage = (conversationId: string, content: string, signal?: AbortSignal) =>
  post<AiTurn>(`/api/ai/conversations/${conversationId}/messages`, { content }, { signal })

export const resetAiConversation = (conversationId: string, locale: string, signal?: AbortSignal) =>
  post<AiConversation>(`/api/ai/conversations/${conversationId}/reset`, { locale }, { signal })

export type RecipeGenerationStage =
  | 'generating'
  | 'checking_structure'
  | 'checking_recipe'
  | 'repairing'
  | 'checking_fixed_structure'
  | 'checking_fixed_recipe'

type RecipeGenerationEvent =
  | { type: 'progress'; stage: RecipeGenerationStage }
  | { type: 'result'; profile: ProfileInput }
  | { type: 'error'; message: string }

export async function generateProfile(
  description: string,
  onProgress: (stage: RecipeGenerationStage) => void,
  signal?: AbortSignal,
): Promise<ProfileInput> {
  const response = await fetch('/api/ai/recipe-wizard/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
    signal,
  })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  if (!response.body) throw new Error('Recipe generation stream is unavailable')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let profile: ProfileInput | null = null

  const consume = (line: string) => {
    if (!line.trim()) return
    const event = JSON.parse(line) as RecipeGenerationEvent
    if (event.type === 'progress') onProgress(event.stage)
    if (event.type === 'result') profile = event.profile
    if (event.type === 'error') throw new Error(event.message)
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    lines.forEach(consume)
    if (done) break
  }
  consume(buffer)
  if (!profile) throw new Error('Recipe generation finished without a result')
  return profile
}

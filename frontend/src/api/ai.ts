import type { AiConversation, AiSubjectType, AiTurn } from '@/types'
import type { ProfileInput } from '@/types'
import { post } from './client'

export const openAiConversation = (
  subjectType: AiSubjectType,
  subjectId: string,
  signal?: AbortSignal,
) =>
  post<AiConversation>(
    '/api/ai/conversations/open',
    { subject_type: subjectType, subject_id: subjectId },
    { signal },
  )

export const sendAiMessage = (conversationId: string, content: string, signal?: AbortSignal) =>
  post<AiTurn>(`/api/ai/conversations/${conversationId}/messages`, { content }, { signal })

export const resetAiConversation = (conversationId: string, signal?: AbortSignal) =>
  post<AiConversation>(`/api/ai/conversations/${conversationId}/reset`, undefined, { signal })

export const generateProfile = (description: string, signal?: AbortSignal) =>
  post<ProfileInput>('/api/ai/recipe-wizard', { description }, { signal })

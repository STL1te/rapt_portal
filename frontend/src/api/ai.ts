import type { AiAssessment, AiAssessmentRequest, AiChatMessage, RecipeReviewRequest } from '@/types'
import { post } from './client'

export const assessSession = (request: AiAssessmentRequest) =>
  post<AiAssessment>('/api/ai/assessments', request)

export const reviewRecipe = (request: RecipeReviewRequest) =>
  post<AiAssessment>('/api/ai/recipe-review', request)

// Держим в синхроне с DEFAULT_QUESTIONS в backend/features/ai/services.py.
const SESSION_DEFAULT_QUESTIONS = {
  fermentation: { active: 'Как идёт брожение?', done: 'Как прошло брожение?' },
  brew: { active: 'Как идёт варка?', done: 'Как прошла варка?' },
} as const

// AiAssistant-пропсы для сессии: дефолтный вопрос + обёртка над assessSession.
export function sessionAssistant(
  kind: 'brew' | 'fermentation',
  sessionId: string,
  completed: boolean,
) {
  return {
    defaultQuestion: SESSION_DEFAULT_QUESTIONS[kind][completed ? 'done' : 'active'],
    ask: (question: string | null, history: AiChatMessage[]) =>
      assessSession({ kind, session_id: sessionId, question, history }),
  }
}

// AiAssistant-пропсы для проверки рецепта.
export function recipeAssistant(profileId: string) {
  return {
    defaultQuestion: 'Проверь рецепт, всё ли с ним ок?',
    ask: (question: string | null, history: AiChatMessage[]) =>
      reviewRecipe({ profile_id: profileId, question, history }),
  }
}

import type { AiAssessment, AiAssessmentRequest } from '@/types'
import { post } from './client'

export const assessSession = (request: AiAssessmentRequest) =>
  post<AiAssessment>('/api/ai/assessments', request)

export type AiChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type AiAssessmentRequest = {
  kind: 'brew' | 'fermentation'
  session_id: string
  question: string | null
  history: AiChatMessage[]
}

export type AiAssessment = {
  answer: string
  model: string
  question: string
}

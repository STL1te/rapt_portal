export type AiSubjectType = 'brew_session' | 'fermentation_session' | 'profile'

export type AiMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type AiConversation = {
  id: string
  subject_type: AiSubjectType
  subject_id: string
  model: string
  messages: AiMessage[]
}

export type AiTurn = {
  user_message: AiMessage
  assistant_message: AiMessage
  model: string
}

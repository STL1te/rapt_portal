import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { assessSession, type AiChatMessage } from '@/api'

type Props = {
  kind: 'brew' | 'fermentation'
  sessionId: string
  completed: boolean
  open: boolean
  onClose: () => void
}

// Держим в синхроне с DEFAULT_QUESTIONS в backend/features/ai/services.py.
const DEFAULT_QUESTIONS = {
  fermentation: { active: 'Как идёт брожение?', done: 'Как прошло брожение?' },
  brew: { active: 'Как идёт варка?', done: 'Как прошла варка?' },
} as const

export default function AiAssistant({ kind, sessionId, completed, open, onClose }: Props) {
  const [messages, setMessages] = useState<AiChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const swipeStartY = useRef<number | null>(null)

  const ask = useCallback(
    async (nextQuestion: string | null, history: AiChatMessage[]) => {
      const sentQuestion = nextQuestion ?? DEFAULT_QUESTIONS[kind][completed ? 'done' : 'active']
      const nextMessages = [...history, { role: 'user' as const, content: sentQuestion }]
      setMessages(nextMessages)
      setQuestion('')
      setIsLoading(true)
      setError(null)
      try {
        const assessment = await assessSession({
          kind,
          session_id: sessionId,
          question: nextQuestion,
          history,
        })
        setMessages([
          ...history,
          { role: 'user', content: assessment.question },
          { role: 'assistant', content: assessment.answer },
        ])
      } catch (requestError) {
        setError(String(requestError))
      } finally {
        setIsLoading(false)
      }
    },
    [kind, sessionId, completed],
  )

  useEffect(() => {
    if (!open || started.current) return
    started.current = true
    void ask(null, [])
  }, [ask, open])

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ block: 'end' })
  }, [messages, isLoading])

  if (!open) return null

  return (
    <div className="ai-chat-layer" role="dialog" aria-modal="true" aria-label="AI-ассистент">
      <button
        type="button"
        className="ai-chat-backdrop"
        aria-label="Закрыть чат"
        onClick={onClose}
      />
      <section className={`ai-chat-window${isFullscreen ? ' fullscreen' : ''}`}>
        <header
          className="ai-chat-head"
          onPointerDown={(event) => {
            if (event.pointerType === 'touch') swipeStartY.current = event.clientY
          }}
          onPointerUp={(event) => {
            if (swipeStartY.current != null && event.clientY - swipeStartY.current > 100) onClose()
            swipeStartY.current = null
          }}
        >
          <div>
            <i className="fa-solid fa-wand-magic-sparkles" />
            <span>AI-ассистент</span>
          </div>
          <div className="ai-chat-head-actions">
            <button
              type="button"
              onClick={() => setIsFullscreen((value) => !value)}
              aria-label={isFullscreen ? 'Уменьшить окно' : 'Развернуть на весь экран'}
              title={isFullscreen ? 'Уменьшить окно' : 'Развернуть на весь экран'}
            >
              <i
                className={`fa-solid ${isFullscreen ? 'fa-down-left-and-up-right-to-center' : 'fa-expand'}`}
              />
            </button>
            <button type="button" onClick={onClose} aria-label="Закрыть чат" title="Закрыть чат">
              <i className="fa-solid fa-xmark" />
            </button>
          </div>
        </header>

        <div className="ai-chat-messages" aria-live="polite">
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={`ai-bubble ${message.role}`}>
              {message.role === 'assistant' ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              ) : (
                message.content
              )}
            </article>
          ))}
          {isLoading && (
            <div className="ai-chat-loading">
              <span /> <span /> <span /> AI-ассистент думает…
            </div>
          )}
          {error && <p className="error">Не удалось получить ответ: {error}</p>}
          <div ref={messagesEnd} />
        </div>

        <form
          className="ai-chat-compose"
          onSubmit={(event) => {
            event.preventDefault()
            if (question.trim() && !isLoading) void ask(question.trim(), messages)
          }}
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                if (question.trim() && !isLoading) void ask(question.trim(), messages)
              }
            }}
            placeholder="Сообщение AI-ассистенту…"
            maxLength={2000}
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !question.trim()} aria-label="Отправить">
            <i className="fa-solid fa-arrow-up" />
          </button>
        </form>
      </section>
    </div>
  )
}

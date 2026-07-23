import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AiAssessment, AiChatMessage } from '@/api'

type Props = {
  open: boolean
  onClose: () => void
  // Текст реплики пользователя, показываемый на автозапуск (модель получает
  // расширенную директиву на бэке).
  defaultQuestion: string
  // Обёртка над конкретным эндпоинтом (assessSession / reviewRecipe). null =
  // дефолтный запрос.
  ask: (question: string | null, history: AiChatMessage[]) => Promise<AiAssessment>
}

export default function AiAssistant({ open, onClose, defaultQuestion, ask }: Props) {
  const [messages, setMessages] = useState<AiChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const swipeStartY = useRef<number | null>(null)

  const send = useCallback(
    async (nextQuestion: string | null, history: AiChatMessage[]) => {
      const shownQuestion = nextQuestion ?? defaultQuestion
      const nextMessages = [...history, { role: 'user' as const, content: shownQuestion }]
      setMessages(nextMessages)
      setQuestion('')
      setIsLoading(true)
      setError(null)
      try {
        const assessment = await ask(nextQuestion, history)
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
    [ask, defaultQuestion],
  )

  useEffect(() => {
    if (!open || started.current) return
    started.current = true
    void send(null, [])
  }, [send, open])

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
            if (question.trim() && !isLoading) void send(question.trim(), messages)
          }}
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                if (question.trim() && !isLoading) void send(question.trim(), messages)
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

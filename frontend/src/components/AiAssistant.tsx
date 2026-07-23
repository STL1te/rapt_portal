import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { openAiConversation, resetAiConversation, sendAiMessage } from '@/api'
import type { AiConversation, AiMessage, AiSubjectType } from '@/types'

type Props = {
  open: boolean
  onClose: () => void
  subjectType: AiSubjectType
  subjectId: string
}

type PendingUserMessage = {
  role: 'user'
  content: string
}

export default function AiAssistant({ open, onClose, subjectType, subjectId }: Props) {
  const [conversation, setConversation] = useState<AiConversation | null>(null)
  const [visibleMessages, setVisibleMessages] = useState<AiMessage[]>([])
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isBootstrapping, setIsBootstrapping] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingUserMessage, setPendingUserMessage] = useState<PendingUserMessage | null>(null)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const swipeStartY = useRef<number | null>(null)

  const subjectKey = `${subjectType}:${subjectId}`
  const loadedSubjectKey = useMemo(
    () => (conversation ? `${conversation.subject_type}:${conversation.subject_id}` : null),
    [conversation],
  )

  useEffect(() => {
    if (!open) return
    if (loadedSubjectKey === subjectKey && conversation) return

    const controller = new AbortController()
    let cancelled = false

    setIsBootstrapping(true)
    setError(null)
    setPendingUserMessage(null)
    setShowResetConfirm(false)

    void openAiConversation(subjectType, subjectId, controller.signal)
      .then((nextConversation) => {
        if (cancelled) return
        setConversation(nextConversation)
        setVisibleMessages(nextConversation.messages)
      })
      .catch((requestError) => {
        if (cancelled || controller.signal.aborted) return
        setError(String(requestError))
      })
      .finally(() => {
        if (!cancelled) setIsBootstrapping(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [conversation, loadedSubjectKey, open, subjectId, subjectKey, subjectType])

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ block: 'end' })
  }, [conversation, isLoading, isBootstrapping, pendingUserMessage])

  if (!open) return null

  async function handleSend(rawQuestion: string) {
    const trimmed = rawQuestion.trim()
    if (!trimmed || !conversation || isLoading || isBootstrapping || isResetting) return

    const preservedText = trimmed
    setQuestion('')
    setIsLoading(true)
    setError(null)
    setPendingUserMessage({ role: 'user', content: preservedText })
    try {
      const turn = await sendAiMessage(conversation.id, preservedText)
      setConversation((current) =>
        current
          ? {
              ...current,
              messages: [...current.messages, turn.user_message, turn.assistant_message],
            }
          : current,
      )
      setVisibleMessages((current) => [...current, turn.user_message, turn.assistant_message])
      setPendingUserMessage(null)
    } catch (requestError) {
      setPendingUserMessage(null)
      setQuestion(preservedText)
      setError(String(requestError))
    } finally {
      setIsLoading(false)
    }
  }

  async function handleReset() {
    if (!conversation || isLoading || isBootstrapping || isResetting) return

    setIsResetting(true)
    setShowResetConfirm(false)
    setError(null)
    setPendingUserMessage(null)
    setQuestion('')
    setVisibleMessages([])
    try {
      const resetConversation = await resetAiConversation(conversation.id)
      setConversation(resetConversation)
      setVisibleMessages(resetConversation.messages)
    } catch (requestError) {
      setError(String(requestError))
      setVisibleMessages(conversation.messages)
    } finally {
      setIsResetting(false)
    }
  }

  const shownMessages: Array<AiMessage | PendingUserMessage> = pendingUserMessage
    ? [...visibleMessages, pendingUserMessage]
    : visibleMessages

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
              onClick={() => setShowResetConfirm((value) => !value)}
              disabled={!conversation || isLoading || isBootstrapping || isResetting}
              aria-label="Начать новый чат"
              title="Начать новый чат"
            >
              <i className="fa-solid fa-rotate-left" />
            </button>
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

        {showResetConfirm && !isResetting && (
          <div className="ai-chat-inline-confirm" role="alert">
            <p>Начать новый чат? Текущая история этого ассистента будет очищена.</p>
            <div className="ai-chat-inline-confirm-actions">
              <button type="button" className="confirm" onClick={() => void handleReset()}>
                Начать заново
              </button>
              <button type="button" className="cancel" onClick={() => setShowResetConfirm(false)}>
                Отмена
              </button>
            </div>
          </div>
        )}

        <div className="ai-chat-messages" aria-live="polite">
          {isBootstrapping && !visibleMessages.length ? (
            <div className="ai-chat-loading">
              <span /> <span /> <span /> AI-ассистент думает…
            </div>
          ) : null}
          {shownMessages.map((message, index) => (
            <article
              key={'id' in message ? message.id : `pending-${index}`}
              className={`ai-bubble ${message.role}`}
            >
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
          {isResetting && (
            <div className="ai-chat-loading">
              <span /> <span /> <span /> AI-ассистент начинает новый чат…
            </div>
          )}
          {error && <p className="error">Не удалось получить ответ: {error}</p>}
          <div ref={messagesEnd} />
        </div>

        <form
          className="ai-chat-compose"
          onSubmit={(event) => {
            event.preventDefault()
            void handleSend(question)
          }}
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void handleSend(question)
              }
            }}
            placeholder="Сообщение AI-ассистенту…"
            maxLength={2000}
            disabled={isLoading || isBootstrapping || isResetting || !conversation}
          />
          <button
            type="submit"
            disabled={
              isLoading || isBootstrapping || isResetting || !conversation || !question.trim()
            }
            aria-label="Отправить"
          >
            <i className="fa-solid fa-arrow-up" />
          </button>
        </form>
      </section>
    </div>
  )
}

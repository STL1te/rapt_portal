import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { openAiConversation, resetAiConversation, sendAiMessage } from '@/api'
import { parseUtc } from '@/lib/fmt'
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

type WindowRect = { top: number; left: number; width: number; height: number }

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const messageTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

function formatMessageTime(iso: string): string {
  return messageTimeFormatter.format(new Date(parseUtc(iso)))
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
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [windowRect, setWindowRect] = useState<WindowRect | null>(null)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const swipeStartY = useRef<number | null>(null)
  const windowElementRef = useRef<HTMLElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const dragState = useRef<{
    startX: number
    startY: number
    startTop: number
    startLeft: number
    width: number
    height: number
  } | null>(null)
  const resizeState = useRef<{
    startX: number
    startY: number
    startTop: number
    startLeft: number
    startWidth: number
    startHeight: number
  } | null>(null)

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

    void openAiConversation(subjectType, subjectId, navigator.language, controller.signal)
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

  useEffect(() => {
    if (!isMenuOpen) return
    function handleOutsideClick(event: PointerEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setIsMenuOpen(false)
    }
    document.addEventListener('pointerdown', handleOutsideClick)
    return () => document.removeEventListener('pointerdown', handleOutsideClick)
  }, [isMenuOpen])

  useEffect(() => {
    return () => {
      window.removeEventListener('pointermove', handleDragMove)
      window.removeEventListener('pointerup', handleDragEnd)
      window.removeEventListener('pointermove', handleResizeMove)
      window.removeEventListener('pointerup', handleResizeEnd)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!open) return null

  function currentRect(): WindowRect {
    if (windowRect) return windowRect
    const box = windowElementRef.current?.getBoundingClientRect()
    return box
      ? { top: box.top, left: box.left, width: box.width, height: box.height }
      : { top: 0, left: 0, width: 420, height: 640 }
  }

  function handleHeaderPointerDown(event: ReactPointerEvent<HTMLElement>) {
    if (event.pointerType === 'touch') {
      swipeStartY.current = event.clientY
      return
    }
    if (isFullscreen || (event.target as HTMLElement).closest('button')) return
    const rect = currentRect()
    dragState.current = {
      startX: event.clientX,
      startY: event.clientY,
      startTop: rect.top,
      startLeft: rect.left,
      width: rect.width,
      height: rect.height,
    }
    window.addEventListener('pointermove', handleDragMove)
    window.addEventListener('pointerup', handleDragEnd)
  }

  function handleDragMove(event: PointerEvent) {
    const drag = dragState.current
    if (!drag) return
    setWindowRect({
      top: clamp(drag.startTop + (event.clientY - drag.startY), 8, window.innerHeight - 80),
      left: clamp(drag.startLeft + (event.clientX - drag.startX), 8, window.innerWidth - 80),
      width: drag.width,
      height: drag.height,
    })
  }

  function handleDragEnd() {
    dragState.current = null
    window.removeEventListener('pointermove', handleDragMove)
    window.removeEventListener('pointerup', handleDragEnd)
  }

  function handleResizePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (isFullscreen) return
    const rect = currentRect()
    resizeState.current = {
      startX: event.clientX,
      startY: event.clientY,
      startTop: rect.top,
      startLeft: rect.left,
      startWidth: rect.width,
      startHeight: rect.height,
    }
    window.addEventListener('pointermove', handleResizeMove)
    window.addEventListener('pointerup', handleResizeEnd)
  }

  function handleResizeMove(event: PointerEvent) {
    const start = resizeState.current
    if (!start) return
    const dx = event.clientX - start.startX
    const dy = event.clientY - start.startY
    const width = clamp(start.startWidth - dx, 320, window.innerWidth - 16)
    const height = clamp(start.startHeight - dy, 360, window.innerHeight - 16)
    setWindowRect({
      top: start.startTop + (start.startHeight - height),
      left: start.startLeft + (start.startWidth - width),
      width,
      height,
    })
  }

  function handleResizeEnd() {
    resizeState.current = null
    window.removeEventListener('pointermove', handleResizeMove)
    window.removeEventListener('pointerup', handleResizeEnd)
  }

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
      const resetConversation = await resetAiConversation(conversation.id, navigator.language)
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
      <section
        ref={windowElementRef}
        className={`ai-chat-window${isFullscreen ? ' fullscreen' : ''}`}
        style={
          windowRect && !isFullscreen
            ? {
                top: windowRect.top,
                left: windowRect.left,
                width: windowRect.width,
                height: windowRect.height,
                right: 'auto',
                bottom: 'auto',
              }
            : undefined
        }
      >
        {!isFullscreen && (
          <div
            className="ai-chat-resize-handle"
            onPointerDown={handleResizePointerDown}
            aria-hidden="true"
          />
        )}
        <header
          className="ai-chat-head"
          onPointerDown={handleHeaderPointerDown}
          onPointerUp={(event) => {
            if (swipeStartY.current != null && event.clientY - swipeStartY.current > 100) onClose()
            swipeStartY.current = null
          }}
        >
          <div className="ai-chat-head-info">
            <div className="ai-chat-head-avatar">
              <i className="fa-solid fa-wand-magic-sparkles" />
            </div>
            <div className="ai-chat-head-text">
              <span className="ai-chat-head-name">AI-ассистент</span>
              <span className="ai-chat-head-caption">Помощник RAPT Portal</span>
            </div>
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
            <div className="ai-chat-menu" ref={menuRef}>
              <button
                type="button"
                onClick={() => setIsMenuOpen((value) => !value)}
                aria-label="Меню"
                aria-expanded={isMenuOpen}
                title="Меню"
              >
                <i className="fa-solid fa-ellipsis-vertical" />
              </button>
              {isMenuOpen && (
                <div className="ai-chat-menu-panel" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!conversation || isLoading || isBootstrapping || isResetting}
                    onClick={() => {
                      setIsMenuOpen(false)
                      setShowResetConfirm(true)
                    }}
                  >
                    <i className="fa-solid fa-rotate-left" /> Очистить историю
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!windowRect}
                    onClick={() => {
                      setIsMenuOpen(false)
                      setWindowRect(null)
                    }}
                  >
                    <i className="fa-solid fa-window-restore" /> Сбросить положение и размер
                  </button>
                </div>
              )}
            </div>
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
          {shownMessages.map((message, index) => {
            const isAssistant = message.role === 'assistant'
            const createdAt = 'created_at' in message ? message.created_at : null
            return (
              <div
                key={'id' in message ? message.id : `pending-${index}`}
                className={`ai-message-row ${message.role}`}
              >
                {isAssistant && (
                  <div className="ai-message-avatar" aria-hidden="true">
                    <i className="fa-solid fa-wand-magic-sparkles" />
                  </div>
                )}
                <div className="ai-message-body">
                  <article className={`ai-bubble ${message.role}`}>
                    {isAssistant ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    ) : (
                      message.content
                    )}
                  </article>
                  {createdAt && (
                    <time className="ai-message-time" dateTime={createdAt}>
                      {formatMessageTime(createdAt)}
                    </time>
                  )}
                </div>
              </div>
            )
          })}
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

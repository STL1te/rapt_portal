import { useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  getSystemJob,
  triggerPortalDataSync,
  triggerSync,
  triggerYeastSync,
  type SystemJob,
} from '../api'
import { useTitle } from '../useTitle'

type SyncCardProps = {
  title: string
  description: string
  actionLabel: string
  disabled: boolean
  children?: ReactNode
  onRun: () => Promise<void>
}

function SyncCard({ title, description, actionLabel, disabled, children, onRun }: SyncCardProps) {
  return (
    <section className="sync-card">
      <div className="sync-card-body">
        <h3 className="panel-title">{title}</h3>
        <p className="muted">{description}</p>
        {children}
      </div>
      <button type="button" disabled={disabled} onClick={() => void onRun()}>
        {actionLabel}
      </button>
    </section>
  )
}

function statusText(job: SystemJob | null): string | null {
  if (!job) return null
  if (job.status === 'queued') return 'Задача в очереди…'
  if (job.status === 'running') return 'Синк выполняется…'
  if (job.status === 'done') return 'Синк завершён.'
  if (job.status === 'failed') return `Ошибка: ${job.error ?? 'unknown error'}`
  return null
}

export default function SystemSyncs() {
  useTitle('Системные синки')
  const queryClient = useQueryClient()
  const [portalToken, setPortalToken] = useState('')
  const [forcePortalSync, setForcePortalSync] = useState(false)
  const [job, setJob] = useState<SystemJob | null>(null)

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return

    const timer = window.setTimeout(async () => {
      try {
        const nextJob = await getSystemJob(job.id)
        setJob(nextJob)
        if (nextJob.status === 'done') {
          await queryClient.invalidateQueries({ queryKey: ['hydrometers'] })
          await queryClient.invalidateQueries({ queryKey: ['brewzillas'] })
          await queryClient.invalidateQueries({ queryKey: ['yeasts'] })
        }
      } catch (error) {
        setJob({
          ...job,
          status: 'failed',
          finished_at: new Date().toISOString(),
          error: String(error),
        })
      }
    }, 1500)

    return () => window.clearTimeout(timer)
  }, [job, queryClient])

  async function startJob(runner: () => Promise<SystemJob>) {
    setJob(await runner())
  }

  const busy = Boolean(job && ['queued', 'running'].includes(job.status))
  const message = statusText(job)

  return (
    <>
      <div className="page-head">
        <h2>Системные синки</h2>
      </div>

      <section className="panel">
        <label className="field">
          <span>Portal token</span>
          <textarea
            className="sync-token"
            rows={4}
            value={portalToken}
            onChange={(event) => setPortalToken(event.target.value)}
            placeholder="Bearer eyJ..."
          />
        </label>
        <p className="muted">
          Используется для portal data sync и sync yeasts. На сервере не сохраняется.
        </p>
        {job ? (
          <p className="muted">
            Job: {job.kind} · {job.id}
          </p>
        ) : null}
        {message ? (
          <p className={message.startsWith('Ошибка:') ? 'error' : 'muted'}>{message}</p>
        ) : null}
      </section>

      <div className="sync-card-grid">
        <SyncCard
          title="Обычный sync"
          description="Базовый синк устройств и активных сессий через обычный RAPT API."
          actionLabel="Запустить"
          disabled={busy}
          onRun={() => startJob(triggerSync)}
        />

        <SyncCard
          title="Portal data sync"
          description="Подтягивает историю profile sessions из portal-only API и обновляет локальные сессии."
          actionLabel="Запустить"
          disabled={busy || !portalToken.trim()}
          onRun={() => startJob(() => triggerPortalDataSync(portalToken, forcePortalSync))}
        >
          <label className="sync-checkbox">
            <input
              type="checkbox"
              checked={forcePortalSync}
              onChange={(event) => setForcePortalSync(event.target.checked)}
            />
            <span>Force: перекачать telemetry для всех portal sessions</span>
          </label>
        </SyncCard>

        <SyncCard
          title="Sync yeasts"
          description="Обновляет локальный каталог дрожжей из portal inventory."
          actionLabel="Запустить"
          disabled={busy || !portalToken.trim()}
          onRun={() => startJob(() => triggerYeastSync(portalToken))}
        />
      </div>
    </>
  )
}

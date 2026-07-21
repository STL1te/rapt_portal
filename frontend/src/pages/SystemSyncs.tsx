import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  getActiveSystemJobs,
  getSystemJob,
  triggerPortalDataSync,
  triggerSync,
  triggerYeastSync,
  type SystemJob,
} from '../api'
import { useTitle } from '../useTitle'

type JobKind = 'base_sync' | 'portal_sync' | 'yeast_sync'

type SyncCardProps = {
  title: string
  description: string
  actionLabel: string
  disabled: boolean
  statusText: string | null
  statusTone: 'muted' | 'error'
  children?: ReactNode
  onRun: () => Promise<void>
}

function SyncCard({
  title,
  description,
  actionLabel,
  disabled,
  statusText,
  statusTone,
  children,
  onRun,
}: SyncCardProps) {
  return (
    <section className="sync-card">
      <div className="sync-card-body">
        <h3 className="panel-title">{title}</h3>
        <p className="muted">{description}</p>
        {children}
        {statusText ? <p className={statusTone}>{statusText}</p> : null}
      </div>
      <button type="button" disabled={disabled} onClick={() => void onRun()}>
        {actionLabel}
      </button>
    </section>
  )
}

function describeJob(job: SystemJob | null): { text: string | null; tone: 'muted' | 'error' } {
  if (!job) return { text: null, tone: 'muted' }
  if (job.status === 'queued') return { text: 'Задача в очереди…', tone: 'muted' }
  if (job.status === 'running') return { text: 'Синк выполняется…', tone: 'muted' }
  if (job.status === 'done') return { text: 'Синк завершён.', tone: 'muted' }
  return { text: `Ошибка: ${job.error ?? 'unknown error'}`, tone: 'error' }
}

function isActive(job: SystemJob | null | undefined): boolean {
  return Boolean(job && (job.status === 'queued' || job.status === 'running'))
}

export default function SystemSyncs() {
  useTitle('Системные синки')
  const queryClient = useQueryClient()
  const [portalToken, setPortalToken] = useState('')
  const [forcePortalSync, setForcePortalSync] = useState(false)
  const [jobsByKind, setJobsByKind] = useState<Partial<Record<JobKind, SystemJob>>>({})

  useEffect(() => {
    let cancelled = false

    async function loadActiveJobs() {
      try {
        const jobs = await getActiveSystemJobs()
        if (cancelled) return
        setJobsByKind(() => {
          const next: Partial<Record<JobKind, SystemJob>> = {}
          for (const job of jobs) {
            if (
              job.kind === 'base_sync' ||
              job.kind === 'portal_sync' ||
              job.kind === 'yeast_sync'
            ) {
              next[job.kind] = job
            }
          }
          return next
        })
      } catch {
        if (cancelled) return
      }
    }

    void loadActiveJobs()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const activeJobs = Object.values(jobsByKind).filter(isActive)
    if (!activeJobs.length) return

    const timer = window.setTimeout(async () => {
      const updates = await Promise.all(
        activeJobs.map(async (job) => {
          try {
            return await getSystemJob(job.id)
          } catch (error) {
            return {
              ...job,
              status: 'failed' as const,
              finished_at: new Date().toISOString(),
              error: String(error),
            }
          }
        }),
      )

      setJobsByKind((current) => {
        const next = { ...current }
        for (const job of updates) {
          if (job.kind === 'base_sync' || job.kind === 'portal_sync' || job.kind === 'yeast_sync') {
            next[job.kind] = job
          }
        }
        return next
      })

      if (updates.some((job) => job.status === 'done')) {
        await queryClient.invalidateQueries({ queryKey: ['hydrometers'] })
        await queryClient.invalidateQueries({ queryKey: ['brewzillas'] })
        await queryClient.invalidateQueries({ queryKey: ['yeasts'] })
      }
    }, 1500)

    return () => window.clearTimeout(timer)
  }, [jobsByKind, queryClient])

  async function startJob(kind: JobKind, runner: () => Promise<SystemJob>) {
    const job = await runner()
    setJobsByKind((current) => ({ ...current, [kind]: job }))
  }

  const baseJob = jobsByKind.base_sync ?? null
  const portalJob = jobsByKind.portal_sync ?? null
  const yeastJob = jobsByKind.yeast_sync ?? null

  const baseState = useMemo(() => describeJob(baseJob), [baseJob])
  const portalState = useMemo(() => describeJob(portalJob), [portalJob])
  const yeastState = useMemo(() => describeJob(yeastJob), [yeastJob])

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
      </section>

      <div className="sync-card-grid">
        <SyncCard
          title="Обычный sync"
          description="Базовый синк устройств и активных сессий через обычный RAPT API."
          actionLabel="Запустить"
          disabled={isActive(baseJob)}
          statusText={baseState.text}
          statusTone={baseState.tone}
          onRun={() => startJob('base_sync', triggerSync)}
        />

        <SyncCard
          title="Portal data sync"
          description="Подтягивает историю profile sessions из portal-only API и обновляет локальные сессии."
          actionLabel="Запустить"
          disabled={isActive(portalJob) || !portalToken.trim()}
          statusText={portalState.text}
          statusTone={portalState.tone}
          onRun={() =>
            startJob('portal_sync', () => triggerPortalDataSync(portalToken, forcePortalSync))
          }
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
          disabled={isActive(yeastJob) || !portalToken.trim()}
          statusText={yeastState.text}
          statusTone={yeastState.tone}
          onRun={() => startJob('yeast_sync', () => triggerYeastSync(portalToken))}
        />
      </div>
    </>
  )
}

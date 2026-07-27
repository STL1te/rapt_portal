import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  getActiveSystemJobs,
  getSystemJobHistory,
  getSystemJob,
  triggerPortalDataSync,
  triggerProfileSync,
  triggerSync,
  triggerYeastSync,
  type SystemJob,
  type SystemJobHistoryPage,
} from '@/api'
import { useTitle } from '@/hooks/useTitle'

type JobKind = 'base_sync' | 'portal_sync' | 'yeast_sync' | 'profile_sync'

const JOB_KINDS: readonly JobKind[] = ['base_sync', 'portal_sync', 'yeast_sync', 'profile_sync']

function isJobKind(kind: string): kind is JobKind {
  return (JOB_KINDS as readonly string[]).includes(kind)
}

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

function formatStamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

function describeKind(kind: string): string {
  if (kind === 'base_sync') return 'Обычный sync'
  if (kind === 'portal_sync') return 'Portal data sync'
  if (kind === 'yeast_sync') return 'Sync yeasts'
  if (kind === 'profile_sync') return 'Sync profiles'
  return kind
}

function statusBadgeClass(status: SystemJob['status']): string {
  if (status === 'done') return 'badge sync-job-badge sync-job-badge-done'
  if (status === 'failed') return 'badge sync-job-badge sync-job-badge-failed'
  if (status === 'running') return 'badge active sync-job-badge'
  return 'badge sync-job-badge'
}

function formatJobResult(job: SystemJob): string {
  if (job.error) return job.error
  if (job.result == null) return '—'
  return JSON.stringify(job.result, null, 2)
}

export default function SystemSyncs() {
  useTitle('Системные синки')
  const queryClient = useQueryClient()
  const [portalToken, setPortalToken] = useState('')
  const [forcePortalSync, setForcePortalSync] = useState(false)
  const [jobsByKind, setJobsByKind] = useState<Partial<Record<JobKind, SystemJob>>>({})
  const [historyPage, setHistoryPage] = useState(1)
  const [history, setHistory] = useState<SystemJobHistoryPage | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadActiveJobs() {
      try {
        const jobs = await getActiveSystemJobs()
        if (cancelled) return
        setJobsByKind(() => {
          const next: Partial<Record<JobKind, SystemJob>> = {}
          for (const job of jobs) {
            if (isJobKind(job.kind)) {
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
    let cancelled = false

    async function loadHistory() {
      try {
        const next = await getSystemJobHistory(historyPage, 20)
        if (!cancelled) setHistory(next)
      } catch {
        if (!cancelled) setHistory(null)
      }
    }

    void loadHistory()
    return () => {
      cancelled = true
    }
  }, [historyPage])

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
          if (isJobKind(job.kind)) {
            next[job.kind] = job
          }
        }
        return next
      })

      if (updates.some((job) => job.status === 'done')) {
        await queryClient.invalidateQueries({ queryKey: ['hydrometers'] })
        await queryClient.invalidateQueries({ queryKey: ['brewzillas'] })
        await queryClient.invalidateQueries({ queryKey: ['yeasts'] })
        await queryClient.invalidateQueries({ queryKey: ['profiles'] })
        const next = await getSystemJobHistory(historyPage, 20)
        setHistory(next)
      }
    }, 1500)

    return () => window.clearTimeout(timer)
  }, [historyPage, jobsByKind, queryClient])

  async function startJob(kind: JobKind, runner: () => Promise<SystemJob>) {
    const job = await runner()
    setJobsByKind((current) => ({ ...current, [kind]: job }))
  }

  const baseJob = jobsByKind.base_sync ?? null
  const portalJob = jobsByKind.portal_sync ?? null
  const yeastJob = jobsByKind.yeast_sync ?? null
  const profileJob = jobsByKind.profile_sync ?? null

  const baseState = useMemo(() => describeJob(baseJob), [baseJob])
  const portalState = useMemo(() => describeJob(portalJob), [portalJob])
  const yeastState = useMemo(() => describeJob(yeastJob), [yeastJob])
  const profileState = useMemo(() => describeJob(profileJob), [profileJob])
  const totalPages = history ? Math.max(1, Math.ceil(history.total / history.page_size)) : 1

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

        <SyncCard
          title="Sync profiles"
          description="Обновляет локальную библиотеку профилей (с алертами) из portal API."
          actionLabel="Запустить"
          disabled={isActive(profileJob) || !portalToken.trim()}
          statusText={profileState.text}
          statusTone={profileState.tone}
          onRun={() => startJob('profile_sync', () => triggerProfileSync(portalToken))}
        />
      </div>

      <section className="panel system-jobs-history">
        <h3 className="panel-title">История sync jobs</h3>
        <div className="table-wrap mobile-cards">
          <table className="mobile-cards">
            <thead>
              <tr>
                <th>Тип</th>
                <th>Статус</th>
                <th>Создана</th>
                <th>Завершена</th>
                <th>Результат</th>
              </tr>
            </thead>
            <tbody>
              {history?.items.length ? (
                history.items.map((job) => (
                  <tr key={job.id}>
                    <td data-label="Тип">{describeKind(job.kind)}</td>
                    <td data-label="Статус">
                      <span className={statusBadgeClass(job.status)}>{job.status}</span>
                    </td>
                    <td data-label="Создана">{formatStamp(job.created_at)}</td>
                    <td data-label="Завершена">{formatStamp(job.finished_at)}</td>
                    <td data-label="Результат">
                      <div className="job-result">{formatJobResult(job)}</div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td data-label="Результат" colSpan={5} className="muted">
                    Нет записей
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination">
          <div className="muted">
            {history
              ? `${(history.page - 1) * history.page_size + 1}–${Math.min(history.page * history.page_size, history.total)} из ${history.total}`
              : '—'}
          </div>
          <div className="pagination-actions">
            <button
              type="button"
              disabled={historyPage <= 1}
              onClick={() => setHistoryPage((page) => page - 1)}
            >
              Назад
            </button>
            <button
              type="button"
              disabled={historyPage >= totalPages}
              onClick={() => setHistoryPage((page) => page + 1)}
            >
              Вперёд
            </button>
          </div>
        </div>
      </section>
    </>
  )
}

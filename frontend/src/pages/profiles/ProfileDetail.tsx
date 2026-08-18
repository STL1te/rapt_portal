import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { deleteProfile, getProfile, getSystemJob, uploadProfile } from '@/api'
import AiAssistant from '@/components/AiAssistant'
import MetricCard from '@/components/MetricCard'
import type { ControlType, EndType, ProfileStep, SystemJob } from '@/types'
import { byTriggerTime } from '@/types/profile'
import { stepLen, temp } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

async function pollJob(jobId: string): Promise<SystemJob> {
  for (;;) {
    const job = await getSystemJob(jobId)
    if (job.status === 'done' || job.status === 'failed') return job
    await new Promise((r) => setTimeout(r, 1500))
  }
}

// FontAwesome icons mirroring RAPT's step editor (see docs/recipes-epic.md)
const CONTROL_ICON: Partial<Record<ControlType, string>> = {
  Target: 'fa-bullseye',
  Ramp: 'fa-chart-line',
}
const END_ICON: Partial<Record<EndType, string>> = {
  Temperature: 'fa-thermometer-half',
  Duration: 'fa-clock',
  Manual: 'fa-hand-point-up',
  Gravity: 'fa-droplet',
  GravityVelocity: 'fa-droplet',
}

function stepDuration(step: { endType: string | null; length: number | null }): string {
  if (step.endType === 'Manual') return 'вручную'
  if (step.endType === 'Temperature') return 'до температуры'
  if (step.endType === 'Gravity' || step.endType === 'GravityVelocity') return 'до плотности'
  return stepLen(step.length)
}

function StepIcon({ icon, title }: { icon: string | undefined; title: string | null }) {
  if (!icon) return null
  return <i className={`fa-solid ${icon} step-icon`} title={title ?? undefined} />
}

// ponytail: "boil" = hottest timed step; no explicit boil flag in the RAPT model
function boilStep(steps: ProfileStep[]): ProfileStep | null {
  const timed = steps.filter(
    (st) => st.endType === 'Duration' && st.temperature != null && st.temperature >= 95,
  )
  return timed.sort((a, b) => (b.temperature ?? 0) - (a.temperature ?? 0))[0] ?? null
}

export default function ProfileDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['profile', id],
    queryFn: () => getProfile(id as string),
    enabled: Boolean(id),
  })
  useTitle(data?.name ?? 'Профиль')

  const location = useLocation()
  const [portalToken, setPortalToken] = useState('')
  const [busy, setBusy] = useState<'upload' | 'delete' | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  // seeded true when we land here after a new draft got the server's GUID
  const [uploaded, setUploaded] = useState(
    Boolean((location.state as { uploaded?: boolean } | null)?.uploaded),
  )

  async function upload(profileId: string) {
    setActionError(null)
    setUploaded(false)
    if (!portalToken.trim()) return setActionError('Вставьте portal token для выгрузки')
    setBusy('upload')
    try {
      const job = await uploadProfile(profileId, portalToken.trim())
      const done = await pollJob(job.id)
      if (done.status === 'failed') throw new Error(done.error ?? 'upload failed')
      await queryClient.invalidateQueries({ queryKey: ['profiles'] })
      const newId = (done.result as { new_id?: string } | null)?.new_id
      if (newId && newId !== profileId) {
        // a new draft was replaced by the server's GUID — the local id is gone,
        // so land on the real profile (carry the success flag across the nav)
        navigate(`/profiles/${newId}`, { replace: true, state: { uploaded: true } })
        return
      }
      await queryClient.invalidateQueries({ queryKey: ['profile', profileId] })
      setUploaded(true)
      setBusy(null)
    } catch (e) {
      setActionError(String(e))
      setBusy(null)
    }
  }

  async function remove(profileId: string) {
    if (!window.confirm('Удалить профиль локально?')) return
    setActionError(null)
    setBusy('delete')
    try {
      await deleteProfile(profileId)
      await queryClient.invalidateQueries({ queryKey: ['profiles'] })
      navigate('/profiles')
    } catch (e) {
      setActionError(String(e))
      setBusy(null)
    }
  }

  const back = (
    <a className="back" onClick={() => navigate('/profiles')}>
      <i className="fa-solid fa-arrow-left" /> Профили
    </a>
  )

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data)
    return (
      <div>
        {back}
        <p>Профиль не найден.</p>
      </div>
    )

  const steps = data.steps.slice().sort((a, b) => a.order - b.order)

  const timedSeconds = steps.reduce((sum, st) => sum + (st.length ?? 0), 0)
  const temps = steps.map((st) => st.temperature).filter((t): t is number => t != null)
  const peakTemp = temps.length ? Math.max(...temps) : null
  const boil = boilStep(steps)
  const totalAlerts = data.alerts.length + steps.reduce((n, st) => n + st.alerts.length, 0)

  return (
    <div>
      {back}

      <div className="page-head">
        <div>
          <h2>{data.name ?? data.id}</h2>
          <div className="muted">{data.profile_type_name ?? 'Профиль'}</div>
        </div>
        <div className="detail-badges">
          {data.draft ? <span className="badge draft-badge">черновик</span> : null}
          <span className={data.public ? 'badge active' : 'badge'}>
            {data.public ? 'публичный' : 'личный'}
          </span>
        </div>
      </div>

      <button type="button" className="assistant-button" onClick={() => setAssistantOpen(true)}>
        <i className="fa-solid fa-wand-magic-sparkles" /> AI-проверка
      </button>
      <AiAssistant
        key={data.id}
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
        subjectType="profile"
        subjectId={data.id}
      />

      <div className="profile-actions">
        <button type="button" onClick={() => navigate(`/profiles/${data.id}/edit`)}>
          <i className="fa-solid fa-pen" /> Редактировать
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={busy !== null || !data.draft}
          title={data.draft ? undefined : 'Нет локальных изменений для выгрузки'}
          onClick={() => void upload(data.id)}
        >
          <i className="fa-solid fa-cloud-arrow-up" />{' '}
          {busy === 'upload' ? 'Выгрузка…' : 'Выгрузить в RAPT'}
        </button>
        {data.draft ? (
          <button type="button" disabled={busy !== null} onClick={() => void remove(data.id)}>
            <i className="fa-solid fa-trash" /> {busy === 'delete' ? 'Удаление…' : 'Удалить'}
          </button>
        ) : null}
      </div>
      {/* only drafts can be uploaded, so the token is dead weight elsewhere */}
      {data.draft ? (
        <label className="field profile-token">
          <span>Portal token (для выгрузки в RAPT)</span>
          <textarea
            className="sync-token"
            rows={2}
            value={portalToken}
            onChange={(e) => setPortalToken(e.target.value)}
            placeholder="Bearer eyJ..."
          />
        </label>
      ) : null}
      {uploaded ? <p className="success">Профиль выгружен в RAPT ✓</p> : null}
      {actionError ? <p className="error">{actionError}</p> : null}

      <section className="stats stats-compact">
        <MetricCard label="Шагов" value={String(steps.length)} icon="fa-solid fa-list-ol" />
        <MetricCard
          label="Плановое время"
          value={timedSeconds ? stepLen(timedSeconds) : '—'}
          sub="сумма шагов с таймером"
          icon="fa-solid fa-clock"
        />
        <MetricCard
          label="Кип"
          value={boil ? stepLen(boil.length) : '—'}
          sub={boil ? `при ${temp(boil.temperature)}` : 'не найден'}
          icon="fa-solid fa-fire"
          tone="warn"
        />
        <MetricCard label="Пиковая T" value={temp(peakTemp)} icon="fa-solid fa-temperature-high" />
        <MetricCard label="Алертов" value={String(totalAlerts)} icon="fa-solid fa-bell" />
      </section>

      {data.description?.trim() ? (
        <section className="panel">
          <p className="detail-notes">{data.description}</p>
        </section>
      ) : null}

      {steps.length > 0 && (
        <section className="panel">
          <div className="table-wrap mobile-cards">
            <table className="table-in-panel mobile-cards">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Шаг</th>
                  <th>Режим</th>
                  <th>Температура</th>
                  <th>Длит.</th>
                  <th>Нагрев</th>
                  <th>Алерты</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((st) => (
                  <tr key={st.id ?? st.order}>
                    <td data-label="#"> {st.order + 1}</td>
                    <td data-label="Шаг">{st.name}</td>
                    <td data-label="Режим">
                      <StepIcon
                        icon={st.controlType ? CONTROL_ICON[st.controlType] : undefined}
                        title={st.controlType}
                      />
                      {st.controlType ?? '—'}
                    </td>
                    <td data-label="Температура">{temp(st.temperature)}</td>
                    <td data-label="Длит.">
                      <StepIcon
                        icon={st.endType ? END_ICON[st.endType] : undefined}
                        title={st.endType}
                      />
                      {stepDuration(st)}
                    </td>
                    <td data-label="Нагрев">
                      {st.heatingUtilisation == null ? '—' : `${st.heatingUtilisation}%`}
                    </td>
                    <td data-label="Алерты">
                      {st.alerts.length ? (
                        <ul className="step-alerts">
                          {st.alerts
                            .slice()
                            .sort(byTriggerTime)
                            .map((a, i) => (
                              <li key={a.id ?? i}>{a.alertText ?? a.trigger ?? '—'}</li>
                            ))}
                        </ul>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

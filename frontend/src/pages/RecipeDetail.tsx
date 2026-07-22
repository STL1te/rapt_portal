import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { getProfile } from '@/api'
import MetricCard from '@/components/MetricCard'
import type { ControlType, EndType, ProfileStep } from '@/types'
import { stepLen, temp } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

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

export default function RecipeDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['profile', id],
    queryFn: () => getProfile(id as string),
    enabled: Boolean(id),
  })
  useTitle(data?.name ?? 'Рецепт')

  const back = (
    <a className="back" onClick={() => navigate('/recipes')}>
      <i className="fa-solid fa-arrow-left" /> Рецепты
    </a>
  )

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data)
    return (
      <div>
        {back}
        <p>Рецепт не найден.</p>
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
          <span className={data.public ? 'badge active' : 'badge'}>
            {data.public ? 'публичный' : 'личный'}
          </span>
        </div>
      </div>

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
        <div className="table-wrap mobile-cards">
          <table className="mobile-cards">
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
                        {st.alerts.map((a, i) => (
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
      )}
    </div>
  )
}

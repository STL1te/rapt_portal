import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { getBrewSession } from '../api'
import BrewChart from '../components/BrewChart'
import { temp, date, durationHm, stepLen, pct } from '../fmt'
import { useTitle } from '../useTitle'

function MetricCard({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string
  value: string
  sub?: string
  icon: string
  tone?: 'ok' | 'warn' | 'quiet' | 'info'
}) {
  return (
    <div className={tone ? `stat stat-${tone}` : 'stat'}>
      <span className="stat-label">
        <i className={icon} /> {label}
      </span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

function fmtDelta(value: number | null) {
  if (value == null) return '—'
  if (Math.abs(value) < 0.05) return 'в цели'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}°C`
}

export default function BrewSessionPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const {
    data: s,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['brew-session', id],
    queryFn: () => getBrewSession(id!),
    enabled: !!id,
  })

  useTitle(s?.name ?? 'Варка')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!s) return null

  const steps = (s.profile?.steps ?? []).slice().sort((a, b) => a.order - b.order)
  const currentStepOrder = s.current_step_order
  const currentStepProgress = s.current_step_progress
  const sessionProgress = s.session_progress
  const target = s.latest_target_temperature ?? s.step_target_temperature
  const delta = s.delta_to_target
  const wortDelta = s.wort_delta_to_target
  const latestTemp = s.latest_temperature
  const latestWort =
    s.latest_wort_temperature && s.latest_wort_temperature > 0 ? s.latest_wort_temperature : null

  const tempTone =
    delta == null ? 'quiet' : Math.abs(delta) <= 0.5 ? 'ok' : Math.abs(delta) <= 2 ? 'info' : 'warn'
  const wortTone =
    wortDelta == null
      ? 'quiet'
      : Math.abs(wortDelta) <= 1
        ? 'ok'
        : Math.abs(wortDelta) <= 3
          ? 'info'
          : 'warn'

  const status = !s.active
    ? {
        tone: 'done',
        title: 'Варка завершена',
        body: 'Сессия закрыта, финальные точки уже сохранены.',
      }
    : currentStepOrder == null
      ? {
          tone: 'quiet',
          title: 'Нет активного шага',
          body: 'Сессия активна, но BrewZilla пока не отдала текущий шаг профиля.',
        }
      : delta != null && Math.abs(delta) <= 0.5
        ? {
            tone: 'active',
            title: 'Температура держится в цели',
            body: `Сейчас идёт шаг «${s.current_step_name ?? `#${currentStepOrder + 1}`}».`,
          }
        : delta != null && delta < -0.5
          ? {
              tone: 'steady',
              title: 'Идёт догрев',
              body: `Котёл пока ниже цели на ${Math.abs(delta).toFixed(1)}°C.`,
            }
          : delta != null && delta > 1.5
            ? {
                tone: 'quiet',
                title: 'Выше цели',
                body: `Котёл выше target на ${delta.toFixed(1)}°C, стоит проверить шаг и автоматику.`,
              }
            : {
                tone: 'steady',
                title: 'Шаг выполняется',
                body: `Профиль идёт, но температура ещё не стабилизировалась у цели.`,
              }

  const progressLabel = sessionProgress == null ? '—' : pct(sessionProgress * 100)
  const currentStepIndex =
    currentStepOrder == null ? null : steps.findIndex((step) => step.order === currentStepOrder)

  return (
    <div>
      <a className="back" onClick={() => navigate(`/brewzillas/${s.brewzilla_id}`)}>
        <i className="fa-solid fa-arrow-left" /> К пивоварне
      </a>
      <div className="page-head">
        <h2>{s.name ?? s.id}</h2>
        {s.active && <span className="badge active">варит</span>}
        <span className="dates">
          {date(s.start_date)} — {s.active ? 'сейчас' : date(s.end_date)}
        </span>
      </div>

      <section className="session-hero">
        <article className={`hero-card hero-status ${status.tone}`}>
          <div className="hero-label">
            <i className="fa-solid fa-wave-square" /> Статус варки
          </div>
          <div className="hero-title">{status.title}</div>
          <div className="hero-body">{status.body}</div>
          <div className="hero-meta">
            <span>Прогресс {progressLabel}</span>
            <span>Шагов {s.total_steps ?? steps.length}</span>
          </div>
        </article>

        <article className="hero-card">
          <div className="hero-label">
            <i className="fa-solid fa-list-check" /> Текущий шаг
          </div>
          <div className="hero-title">{s.current_step_name ?? '—'}</div>
          <div className="hero-body">
            {currentStepOrder == null
              ? 'BrewZilla не вернула активный шаг для этой точки.'
              : `Шаг #${currentStepOrder + 1}${currentStepProgress == null ? '' : ` · ${pct(currentStepProgress * 100)}`}`}
          </div>
          <div className="hero-meta">
            <span>Цель {temp(target)}</span>
            <span>
              Длит.{' '}
              {currentStepIndex == null ? '—' : stepLen(steps[currentStepIndex]?.length ?? null)}
            </span>
          </div>
        </article>

        <article className="hero-card">
          <div className="hero-label">
            <i className="fa-solid fa-temperature-three-quarters" /> Температурный контроль
          </div>
          <div className="hero-title">{fmtDelta(delta)}</div>
          <div className="hero-body">Показываем отклонение котла от target.</div>
          <div className="hero-meta">
            <span>Котёл {temp(latestTemp)}</span>
            <span>Сусло {temp(latestWort)}</span>
          </div>
        </article>
      </section>

      <section className="stats stats-compact">
        <MetricCard
          label="Котёл"
          value={temp(latestTemp)}
          sub={target == null ? undefined : `цель ${temp(target)}`}
          icon="fa-solid fa-fire-burner"
          tone={tempTone}
        />
        <MetricCard
          label="Отклонение котла"
          value={fmtDelta(delta)}
          sub={
            s.last_telemetry_at
              ? `обновлено ${new Date(s.last_telemetry_at).toLocaleString()}`
              : 'нет telemetry'
          }
          icon="fa-solid fa-bullseye"
          tone={tempTone}
        />
        <MetricCard
          label="Сусло"
          value={temp(latestWort)}
          sub={wortDelta == null ? 'внешний датчик неактивен' : `к target ${fmtDelta(wortDelta)}`}
          icon="fa-solid fa-flask"
          tone={wortTone}
        />
        <MetricCard
          label="Прогресс сессии"
          value={progressLabel}
          sub={currentStepOrder == null ? undefined : `шаг #${currentStepOrder + 1}`}
          icon="fa-solid fa-bars-progress"
        />
        <MetricCard
          label="Нагрев всего"
          value={stepLen(s.latest_heating_run_time)}
          sub={
            s.latest_aux_run_time == null ? undefined : `помпа ${stepLen(s.latest_aux_run_time)}`
          }
          icon="fa-solid fa-bolt"
        />
        <MetricCard
          label="Длительность"
          value={durationHm(s.start_date, s.end_date)}
          icon="fa-solid fa-clock"
        />
      </section>

      <section className="chart">
        <BrewChart sessionId={s.id} session={s} />
      </section>

      {steps.length > 0 && (
        <>
          <h2>Профиль варки</h2>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Шаг</th>
                <th>Температура</th>
                <th>Длит.</th>
                <th>Нагрев</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((st) => {
                const isCurrent = currentStepOrder != null && st.order === currentStepOrder
                const isDone = currentStepOrder != null ? st.order < currentStepOrder : !s.active
                const statusLabel = isCurrent
                  ? currentStepProgress == null
                    ? 'идёт'
                    : `${pct(currentStepProgress * 100)} шага`
                  : isDone
                    ? 'пройден'
                    : 'в очереди'

                return (
                  <tr key={st.id ?? st.order} className={isCurrent ? 'row selected' : undefined}>
                    <td>{st.order + 1}</td>
                    <td>{st.name}</td>
                    <td>{temp(st.temperature)}</td>
                    <td>{st.endType === 'Manual' ? 'вручную' : stepLen(st.length)}</td>
                    <td>{st.heatingUtilisation == null ? '—' : `${st.heatingUtilisation}%`}</td>
                    <td>{statusLabel}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

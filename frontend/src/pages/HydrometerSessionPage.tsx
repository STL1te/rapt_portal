import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { getSession, getTelemetry } from '../api'
import HydrometerChart from '../components/HydrometerChart'
import StatCards from '../components/StatCards'
import { brix, date, duration, grav, sg } from '../fmt'
import { useTitle } from '../useTitle'

function parseUtc(value: string) {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`).getTime()
}

export default function HydrometerSessionPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: s, isLoading, error } = useQuery({
    queryKey: ['hydrometer-session', id],
    queryFn: () => getSession(id!),
    enabled: !!id,
  })
  const {
    data: telemetry,
    isLoading: isTelemetryLoading,
    error: telemetryError,
  } = useQuery({
    queryKey: ['hydrometer-telemetry', id],
    queryFn: () => getTelemetry(id!),
    enabled: !!id,
  })

  useTitle(s?.name ?? 'Сессия брожения')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (isTelemetryLoading) return <p>Загрузка графика…</p>
  if (telemetryError) return <p className="error">Ошибка: {String(telemetryError)}</p>
  if (!s) return null

  const latest = telemetry?.findLast((point) => point.gravity != null || point.temperature != null) ?? null
  const latestGravity = s.current_gravity
  const latestTemp = latest?.temperature ?? null
  const latestTime = latest?.timestamp ? parseUtc(latest.timestamp) : null
  const point24h = latestTime == null
    ? null
    : [...(telemetry ?? [])].reverse().find((point) => (
        point.gravity != null && parseUtc(point.timestamp) <= latestTime - 24 * 60 * 60 * 1000
      )) ?? null
  const gravityDrop24h = latestGravity != null && point24h?.gravity != null
    ? point24h.gravity - latestGravity
    : null
  const gravityToFg = latestGravity != null && s.final_gravity != null
    ? latestGravity - s.final_gravity
    : null

  const status = !s.active
    ? { tone: 'done', title: 'Сессия завершена', body: 'Финальные показатели уже зафиксированы.' }
    : gravityDrop24h != null && gravityDrop24h >= 8
      ? { tone: 'active', title: 'Активное брожение', body: `Плотность упала на ${grav(gravityDrop24h)} за последние 24 часа.` }
      : gravityToFg != null && gravityToFg <= 0
        ? { tone: 'done', title: 'Оценка финиша догоняет', body: 'Текущая плотность уже ниже текущей оценки финиша; оценка еще может сдвинуться по новым точкам.' }
        : gravityToFg != null && gravityToFg <= 2
          ? { tone: 'done', title: 'Похоже, дображивает', body: 'Текущая плотность уже близка к оценке финальной плотности.' }
          : gravityDrop24h != null && gravityDrop24h >= 2
            ? { tone: 'steady', title: 'Брожение замедлилось', body: 'Изменения еще есть, но пик активности уже прошел.' }
            : { tone: 'quiet', title: 'Мало движения', body: 'За последние сутки изменение небольшое. Проверь температуру и последние точки.' }

  const density = (n: number | null) => `${sg(n)} SG · ${brix(n)}°Bx`
  const stats = [
    { label: 'Текущая плотность', value: grav(latestGravity), sub: density(latestGravity), icon: 'fa-solid fa-droplet' },
    {
      label: 'Изменение за 24ч',
      value: gravityDrop24h == null ? '—' : grav(gravityDrop24h),
      sub: point24h ? `было ${grav(point24h.gravity)}` : 'недостаточно данных',
      icon: 'fa-solid fa-chart-line',
    },
    {
      label: 'Температура',
      value: latestTemp == null ? '—' : `${latestTemp.toFixed(1)}°C`,
      sub: latest?.timestamp ? `обновлено ${new Date(parseUtc(latest.timestamp)).toLocaleString()}` : undefined,
      icon: 'fa-solid fa-temperature-three-quarters',
    },
    {
      label: 'Оценочный FG',
      value: grav(s.final_gravity),
      sub: gravityToFg == null
        ? density(s.final_gravity)
        : gravityToFg <= 0
          ? `текущая ниже на ${grav(Math.abs(gravityToFg))}`
          : `до оценки финиша ${grav(gravityToFg)}`,
      icon: 'fa-solid fa-droplet-slash',
    },
    { label: 'Алкоголь', value: s.abv == null ? '—' : `${s.abv.toFixed(1)}%`, icon: 'fa-solid fa-wine-bottle' },
    { label: 'Аттенюация', value: s.attenuation == null ? '—' : `${s.attenuation.toFixed(0)}%`, icon: 'fa-solid fa-percent' },
    { label: 'Длительность', value: duration(s.start_date, s.end_date), icon: 'fa-solid fa-clock' },
  ]

  return (
    <div>
      <a className="back" onClick={() => navigate(`/hydrometers/${s.hydrometer_id}`)}><i className="fa-solid fa-arrow-left" /> К прибору</a>
      <div className="page-head">
        <h2>{s.name ?? s.id}</h2>
        {s.active && <span className="badge active">активна</span>}
        <span className="dates">{date(s.start_date)} — {s.active ? 'сейчас' : date(s.end_date)}</span>
      </div>
      <section className={`fermentation-summary ${status.tone}`}>
        <div>
          <div className="fermentation-summary-title">{status.title}</div>
          <div className="fermentation-summary-body">{status.body}</div>
        </div>
        <div className="fermentation-summary-meta">
          <span>OG {grav(s.original_gravity)}</span>
          <span>Оценочный FG {grav(s.final_gravity)}</span>
        </div>
      </section>
      <StatCards stats={stats} />
      <section className="chart">
        <HydrometerChart data={telemetry ?? []} />
      </section>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getHydrometerSession, getHydrometerTelemetry } from '@/api'
import AiAssistant from '@/components/AiAssistant'
import HydrometerChart from '@/components/HydrometerChart'
import MetricCard from '@/components/MetricCard'
import { brix, date, duration, grav, sg } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

function parseUtc(value: string) {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`).getTime()
}

export default function HydrometerSessionPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [assistantOpen, setAssistantOpen] = useState(false)

  const {
    data: s,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['hydrometer-session', id],
    queryFn: () => getHydrometerSession(id!),
    enabled: !!id,
  })
  const {
    data: telemetry,
    isLoading: isTelemetryLoading,
    error: telemetryError,
  } = useQuery({
    queryKey: ['hydrometer-telemetry', id],
    queryFn: () => getHydrometerTelemetry(id!),
    enabled: !!id,
  })

  useTitle(s?.name ?? 'Сессия брожения')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (isTelemetryLoading) return <p>Загрузка графика…</p>
  if (telemetryError) return <p className="error">Ошибка: {String(telemetryError)}</p>
  if (!s) return null

  const latest =
    telemetry?.findLast((point) => point.gravity != null || point.temperature != null) ?? null
  const latestGravity = s.current_gravity
  const latestTemp = latest?.temperature ?? null
  const latestTime = latest?.timestamp ? parseUtc(latest.timestamp) : null
  const latestTelemetryLabel =
    latestTime == null ? 'нет данных' : new Date(latestTime).toLocaleString()
  const startTelemetryLabel =
    s.start_date == null ? 'нет данных' : new Date(parseUtc(s.start_date)).toLocaleString()
  const point24h =
    latestTime == null
      ? null
      : ([...(telemetry ?? [])]
          .reverse()
          .find(
            (point) =>
              point.gravity != null &&
              parseUtc(point.timestamp) <= latestTime - 24 * 60 * 60 * 1000,
          ) ?? null)
  const gravityDrop24h =
    latestGravity != null && point24h?.gravity != null ? point24h.gravity - latestGravity : null
  const gravityDrop24hLabel = gravityDrop24h == null ? null : grav(gravityDrop24h)
  const referenceFg = s.target_final_gravity ?? s.final_gravity
  const gravityToFg =
    latestGravity != null && referenceFg != null ? latestGravity - referenceFg : null

  const status = !s.active
    ? { tone: 'done', title: 'Сессия завершена', body: 'Финальные показатели уже зафиксированы.' }
    : gravityDrop24h != null && gravityDrop24h >= 8
      ? {
          tone: 'active',
          title: 'Активное брожение',
          body: `Плотность упала на ${grav(gravityDrop24h)} за последние 24 часа.`,
        }
      : gravityToFg != null && gravityToFg <= 0
        ? {
            tone: 'done',
            title: 'Финиш достигнут',
            body: 'Текущая плотность уже ниже или равна расчётной цели.',
          }
        : gravityToFg != null && gravityToFg <= 2
          ? {
              tone: 'done',
              title: 'Почти финиш',
              body: 'Текущая плотность уже очень близка к расчётному FG.',
            }
          : gravityDrop24h != null && gravityDrop24h >= 2
            ? {
                tone: 'steady',
                title: 'Брожение замедлилось',
                body: 'Изменения ещё есть, но пик активности уже прошёл.',
              }
            : {
                tone: 'quiet',
                title: 'Мало движения',
                body: 'За последние сутки изменение небольшое. Проверь температуру и последние точки.',
              }

  const density = (n: number | null) => `${sg(n)} SG · ${brix(n)}°Bx`
  const fgLabel = s.target_final_gravity == null ? 'Оценочный FG' : 'FG по дрожжам'
  const fgSub =
    gravityToFg == null
      ? density(referenceFg)
      : gravityToFg <= 0
        ? `текущая ниже на ${grav(Math.abs(gravityToFg))}`
        : `до цели ${grav(gravityToFg)}`
  const yeastSub = s.yeast_product_id
    ? `${s.yeast_product_id}${s.yeast_attenuation == null ? '' : ` · ${Math.round(s.yeast_attenuation)}% attenuation`}`
    : s.yeast_attenuation == null
      ? 'Дрожжи не указаны'
      : `${Math.round(s.yeast_attenuation)}% attenuation`
  const tempRange =
    s.yeast_min_temperature != null && s.yeast_max_temperature != null
      ? `${s.yeast_min_temperature.toFixed(1)}–${s.yeast_max_temperature.toFixed(1)}°C`
      : s.yeast_min_temperature != null
        ? `от ${s.yeast_min_temperature.toFixed(1)}°C`
        : s.yeast_max_temperature != null
          ? `до ${s.yeast_max_temperature.toFixed(1)}°C`
          : null
  const tempTone =
    latestTemp == null || tempRange == null
      ? 'quiet'
      : latestTemp >= (s.yeast_min_temperature ?? Number.NEGATIVE_INFINITY) &&
          latestTemp <= (s.yeast_max_temperature ?? Number.POSITIVE_INFINITY)
        ? 'ok'
        : 'warn'
  const attenuationDelta =
    s.attenuation != null && s.yeast_attenuation != null
      ? s.attenuation - s.yeast_attenuation
      : null
  const attenuationSub =
    s.yeast_attenuation == null
      ? undefined
      : attenuationDelta == null
        ? `цель дрожжей ${Math.round(s.yeast_attenuation)}%`
        : attenuationDelta >= 0
          ? `выше цели дрожжей на ${Math.round(attenuationDelta)}%`
          : `ниже цели дрожжей на ${Math.round(Math.abs(attenuationDelta))}%`
  const attenuationTone =
    s.attenuation == null || s.yeast_attenuation == null
      ? 'quiet'
      : Math.abs(attenuationDelta ?? 0) <= 3
        ? 'ok'
        : attenuationDelta != null && attenuationDelta < 0
          ? 'warn'
          : 'info'

  return (
    <div>
      <a className="back" onClick={() => navigate(`/hydrometers/${s.hydrometer_id}`)}>
        <i className="fa-solid fa-arrow-left" /> К прибору
      </a>
      <div className="page-head">
        <h2>{s.name ?? s.id}</h2>
        {s.active && <span className="badge active">активна</span>}
        <span className="dates">
          {date(s.start_date)} — {s.active ? 'сейчас' : date(s.end_date)}
        </span>
      </div>

      <button type="button" className="assistant-button" onClick={() => setAssistantOpen(true)}>
        <i className="fa-solid fa-wand-magic-sparkles" /> AI-ассистент
      </button>
      <AiAssistant
        key={s.id}
        kind="fermentation"
        sessionId={s.id}
        completed={!s.active}
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
      />

      <section className="session-hero">
        <article className={`hero-card hero-status ${status.tone}`}>
          <div className="hero-label">
            <i className="fa-solid fa-wave-square" /> Стадия брожения
          </div>
          <div className="hero-title">{status.title}</div>
          <div className="hero-body">{status.body}</div>
          <div className="hero-meta">
            <span>OG {grav(s.original_gravity)}</span>
            <span>Текущая {grav(latestGravity)}</span>
            <span>
              24ч {gravityDrop24hLabel == null ? '—' : `-${gravityDrop24hLabel}`}
              {point24h?.gravity != null ? ` · было ${grav(point24h.gravity)}` : ''}
            </span>
          </div>
        </article>

        <article className="hero-card">
          <div className="hero-label">
            <i className="fa-solid fa-droplet-slash" /> {fgLabel}
          </div>
          <div className="hero-title">{grav(referenceFg)}</div>
          <div className="hero-body">{fgSub}</div>
          <div className="hero-meta">
            <span>FG по телеметрии {grav(s.final_gravity)}</span>
          </div>
        </article>

        <article className="hero-card">
          <div className="hero-label">
            <i className="fa-solid fa-vial" /> Дрожжи
          </div>
          {s.yeast_id && s.yeast_name ? (
            <Link to={`/yeasts/${s.yeast_id}`} className="hero-link">
              {s.yeast_name}
            </Link>
          ) : (
            <div className="hero-title">—</div>
          )}
          <div className="hero-body">{yeastSub}</div>
        </article>
      </section>

      <section className="stats stats-compact">
        <MetricCard
          label="Начальная плотность"
          value={grav(s.original_gravity)}
          sub={density(s.original_gravity)}
          icon="fa-solid fa-vial-circle-check"
        />
        <MetricCard
          label="Текущая плотность"
          value={grav(latestGravity)}
          sub={density(latestGravity)}
          icon="fa-solid fa-droplet"
        />
        <MetricCard
          label="Температура"
          value={latestTemp == null ? '—' : `${latestTemp.toFixed(1)}°C`}
          sub={
            tempRange == null
              ? latest?.timestamp
                ? `обновлено ${new Date(parseUtc(latest.timestamp)).toLocaleString()}`
                : undefined
              : `диапазон дрожжей ${tempRange}`
          }
          icon="fa-solid fa-temperature-three-quarters"
          tone={tempTone}
        />
        <MetricCard
          label="Алкоголь"
          value={s.abv == null ? '—' : `${s.abv.toFixed(1)}%`}
          icon="fa-solid fa-wine-bottle"
        />
        <MetricCard
          label="Аттенюация"
          value={s.attenuation == null ? '—' : `${s.attenuation.toFixed(0)}%`}
          sub={attenuationSub}
          icon="fa-solid fa-percent"
          tone={attenuationTone}
        />
        <MetricCard
          label="Длительность"
          value={duration(s.start_date, s.end_date)}
          sub={`старт ${startTelemetryLabel} · последняя телеметрия ${latestTelemetryLabel}`}
          icon="fa-solid fa-clock"
        />
      </section>

      <section className="chart">
        <HydrometerChart data={telemetry ?? []} />
      </section>
    </div>
  )
}

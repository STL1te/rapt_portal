import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { getSession } from '../api'
import HydrometerChart from '../components/HydrometerChart'
import StatCards from '../components/StatCards'
import { grav, sg, brix, date, duration } from '../fmt'
import { useTitle } from '../useTitle'

export default function HydrometerSessionPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: s, isLoading, error } = useQuery({
    queryKey: ['session', id],
    queryFn: () => getSession(id!),
    enabled: !!id,
  })

  useTitle(s?.name ?? 'Сессия')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!s) return null

  const density = (n: number | null) => `${sg(n)} SG · ${brix(n)}°Bx`
  const stats = [
    { label: 'OG', value: grav(s.original_gravity), sub: density(s.original_gravity), icon: 'fa-solid fa-droplet' },
    { label: 'FG', value: grav(s.final_gravity), sub: density(s.final_gravity), icon: 'fa-solid fa-droplet-slash' },
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
      <StatCards stats={stats} />
      <section className="chart">
        <HydrometerChart sessionId={s.id} />
      </section>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { getBrewSession } from '../api'
import BrewChart from '../components/BrewChart'
import StatCards from '../components/StatCards'
import { temp, date, duration, stepLen } from '../fmt'
import { useTitle } from '../useTitle'

export default function BrewSessionPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: s, isLoading, error } = useQuery({
    queryKey: ['brew-session', id],
    queryFn: () => getBrewSession(id!),
    enabled: !!id,
  })

  useTitle(s?.name ?? 'Варка')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!s) return null

  const steps = (s.profile?.steps ?? []).slice().sort((a, b) => a.order - b.order)
  const stats = [
    { label: 'Длительность', value: duration(s.start_date, s.end_date), icon: 'fa-solid fa-clock' },
    { label: 'Шагов', value: String(steps.length), icon: 'fa-solid fa-list-ol' },
    { label: 'Макс. цель', value: temp(Math.max(...steps.map((x) => x.temperature ?? 0)) || null), icon: 'fa-solid fa-bullseye' },
  ]

  return (
    <div>
      <a className="back" onClick={() => navigate(`/brewzillas/${s.brewzilla_id}`)}><i className="fa-solid fa-arrow-left" /> К пивоварне</a>
      <div className="page-head">
        <h2>{s.name ?? s.id}</h2>
        {s.active && <span className="badge active">варит</span>}
        <span className="dates">{date(s.start_date)} — {s.active ? 'сейчас' : date(s.end_date)}</span>
      </div>

      <StatCards stats={stats} />

      <section className="chart">
        <BrewChart sessionId={s.id} />
      </section>

      {steps.length > 0 && (
        <>
          <h2>Профиль варки</h2>
          <table>
            <thead>
              <tr><th>#</th><th>Шаг</th><th>Температура</th><th>Длит.</th><th>Нагрев</th></tr>
            </thead>
            <tbody>
              {steps.map((st) => (
                <tr key={st.order}>
                  <td>{st.order + 1}</td>
                  <td>{st.name}</td>
                  <td>{temp(st.temperature)}</td>
                  <td>{st.endType === 'Manual' ? 'вручную' : stepLen(st.length)}</td>
                  <td>{st.heatingUtilisation == null ? '—' : `${st.heatingUtilisation}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

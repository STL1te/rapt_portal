import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { getHydrometers, getHydrometerSessions } from '../api'
import { date, duration, grav } from '../fmt'
import { useTitle } from '../useTitle'

export default function HydrometerDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: hydrometers } = useQuery({ queryKey: ['hydrometers'], queryFn: getHydrometers })
  const name = hydrometers?.find((h) => h.id === id)?.name
  useTitle(name ?? 'История сессий')

  const { data: sessions, isLoading, error } = useQuery({
    queryKey: ['sessions', id],
    queryFn: () => getHydrometerSessions(id!),
    enabled: !!id,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <div>
      <a className="back" onClick={() => navigate('/hydrometers')}><i className="fa-solid fa-arrow-left" /> Гидрометры</a>
      <h2>{name ? `${name} — история сессий` : 'История сессий'}</h2>
      {!sessions?.length ? (
        <p>Сессий пока нет.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Сессия</th><th>Старт</th><th>Финиш</th>
              <th>Длит.</th><th>OG</th><th>FG</th><th>Алк.</th><th>Атт.</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="row" onClick={() => navigate(`/hydrometer-sessions/${s.id}`)}>
                <td>{s.name ?? s.id}{s.active && <span className="badge active">активна</span>}</td>
                <td>{date(s.start_date)}</td>
                <td>{s.active ? '—' : date(s.end_date)}</td>
                <td>{duration(s.start_date, s.end_date)}</td>
                <td>{grav(s.original_gravity)}</td>
                <td>{grav(s.final_gravity)}</td>
                <td>{s.abv == null ? '—' : `${s.abv.toFixed(1)}%`}</td>
                <td>{s.attenuation == null ? '—' : `${s.attenuation.toFixed(0)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

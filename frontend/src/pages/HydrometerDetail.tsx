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

  const {
    data: sessions,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['sessions', id],
    queryFn: () => getHydrometerSessions(id!),
    enabled: !!id,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <div>
      <a className="back" onClick={() => navigate('/hydrometers')}>
        <i className="fa-solid fa-arrow-left" /> Гидрометры
      </a>
      <h2>{name ? `${name} — история сессий` : 'История сессий'}</h2>
      {!sessions?.length ? (
        <p>Сессий пока нет.</p>
      ) : (
        <div className="table-wrap mobile-cards">
          <table className="mobile-cards">
            <thead>
              <tr>
                <th>Сессия</th>
                <th>Старт</th>
                <th>Финиш</th>
                <th>Длит.</th>
                <th>OG</th>
                <th>FG</th>
                <th>Алк.</th>
                <th>Атт.</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.id}
                  className="row"
                  onClick={() => navigate(`/hydrometer-sessions/${s.id}`)}
                >
                  <td data-label="Сессия">
                    {s.name ?? s.id}
                    {s.active && <span className="badge active">активна</span>}
                  </td>
                  <td data-label="Старт">{date(s.start_date)}</td>
                  <td data-label="Финиш">{s.active ? '—' : date(s.end_date)}</td>
                  <td data-label="Длит.">{duration(s.start_date, s.end_date)}</td>
                  <td data-label="OG">{grav(s.original_gravity)}</td>
                  <td data-label="FG">{grav(s.final_gravity)}</td>
                  <td data-label="Алк.">{s.abv == null ? '—' : `${s.abv.toFixed(1)}%`}</td>
                  <td data-label="Атт.">
                    {s.attenuation == null ? '—' : `${s.attenuation.toFixed(0)}%`}
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

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getBrewSessions, getBrewzillas } from '@/api'
import { date, durationHm } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

export default function BrewZillaDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [includeShort, setIncludeShort] = useState(false)

  const { data: brewzillas } = useQuery({ queryKey: ['brewzillas'], queryFn: getBrewzillas })
  const name = brewzillas?.find((b) => b.id === id)?.name
  useTitle(name ?? 'Пивоварня')

  const {
    data: sessions,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['brew-sessions', id, includeShort],
    queryFn: () => getBrewSessions(id!, includeShort),
    enabled: !!id,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <div>
      <a className="back" onClick={() => navigate('/')}>
        <i className="fa-solid fa-arrow-left" /> Дашборд
      </a>
      <h2>{name ? `${name} — история варок` : 'История варок'}</h2>
      <div className="chart-toolbar">
        <span className="chart-toolbar-label">Показывать короткие варки &lt; 1 часа</span>
        <div className="chart-presets">
          <button
            type="button"
            className={`chart-preset${includeShort ? ' active' : ''}`}
            onClick={() => setIncludeShort((value) => !value)}
          >
            {includeShort ? 'включено' : 'скрыты'}
          </button>
        </div>
      </div>
      {!sessions?.length ? (
        <p>Варок пока нет.</p>
      ) : (
        <section className="panel">
          <div className="table-wrap mobile-cards">
            <table className="table-in-panel mobile-cards">
              <thead>
                <tr>
                  <th>Профиль</th>
                  <th>Старт</th>
                  <th>Финиш</th>
                  <th>Длит.</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id} className="row" onClick={() => navigate(`/brew-sessions/${s.id}`)}>
                    <td data-label="Профиль">
                      {s.name ?? s.id}
                      {s.active && <span className="badge active">варит</span>}
                    </td>
                    <td data-label="Старт">{date(s.start_date)}</td>
                    <td data-label="Финиш">{s.active ? '—' : date(s.end_date)}</td>
                    <td data-label="Длит.">{durationHm(s.start_date, s.end_date)}</td>
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

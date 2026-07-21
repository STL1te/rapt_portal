import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { getBrewSessions, getBrewzillas } from '../api'
import { date, duration } from '../fmt'
import { useTitle } from '../useTitle'

export default function BrewZillaDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: brewzillas } = useQuery({ queryKey: ['brewzillas'], queryFn: getBrewzillas })
  const name = brewzillas?.find((b) => b.id === id)?.name
  useTitle(name ?? 'Пивоварня')

  const { data: sessions, isLoading, error } = useQuery({
    queryKey: ['brew-sessions', id],
    queryFn: () => getBrewSessions(id!),
    enabled: !!id,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <div>
      <a className="back" onClick={() => navigate('/')}><i className="fa-solid fa-arrow-left" /> Дашборд</a>
      <h2>{name ? `${name} — история варок` : 'История варок'}</h2>
      {!sessions?.length ? (
        <p>Варок пока нет.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Профиль</th><th>Старт</th><th>Финиш</th><th>Длит.</th></tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="row" onClick={() => navigate(`/brew-sessions/${s.id}`)}>
                <td>{s.name ?? s.id}{s.active && <span className="badge active">варит</span>}</td>
                <td>{date(s.start_date)}</td>
                <td>{s.active ? '—' : date(s.end_date)}</td>
                <td>{duration(s.start_date, s.end_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

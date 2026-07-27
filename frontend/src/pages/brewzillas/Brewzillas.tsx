import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getBrewzillas } from '@/api'
import { pct, temp } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

export default function Brewzillas() {
  useTitle('Пивоварни')
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['brewzillas'],
    queryFn: getBrewzillas,
    refetchInterval: 60_000,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length) return <p>Пивоварен не найдено.</p>

  return (
    <>
      <div className="page-head">
        <h2>Пивоварни</h2>
        <div className="dates muted">Всего: {data.length}</div>
      </div>

      <section className="panel">
        <div className="table-wrap mobile-cards">
          <table className="table-in-panel mobile-cards">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Статус</th>
                <th>Температура</th>
                <th>Цель</th>
                <th>Нагрев</th>
              </tr>
            </thead>
            <tbody>
              {data.map((b) => (
                <tr key={b.id} className="row" onClick={() => navigate(`/brewzillas/${b.id}`)}>
                  <td data-label="Имя">{b.name ?? b.id}</td>
                  <td data-label="Статус">
                    <span className={b.active_session_id ? 'badge active' : 'badge'}>
                      {b.active_session_id ? 'варит' : 'простой'}
                    </span>
                  </td>
                  <td data-label="Температура">{temp(b.temperature)}</td>
                  <td data-label="Цель">{temp(b.target_temperature)}</td>
                  <td data-label="Нагрев">
                    {b.heating_enabled ? pct(b.heating_utilisation) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getHydrometers } from '@/api'
import { grav, pct, temp } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

export default function Hydrometers() {
  useTitle('Гидрометры')
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['hydrometers'],
    queryFn: getHydrometers,
    refetchInterval: 60_000,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length) return <p>Гидрометров не найдено.</p>

  return (
    <>
      <div className="page-head">
        <h2>Гидрометры</h2>
        <div className="dates muted">Всего: {data.length}</div>
      </div>

      <section className="panel">
        <div className="table-wrap mobile-cards">
          <table className="table-in-panel mobile-cards">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Статус</th>
                <th>Плотность</th>
                <th>Температура</th>
                <th>Батарея</th>
              </tr>
            </thead>
            <tbody>
              {data.map((h) => (
                <tr key={h.id} className="row" onClick={() => navigate(`/hydrometers/${h.id}`)}>
                  <td data-label="Имя">{h.name ?? h.id}</td>
                  <td data-label="Статус">
                    <span className={h.active_session_id ? 'badge active' : 'badge'}>
                      {h.active_session_id ? 'активна' : 'нет сессии'}
                    </span>
                  </td>
                  <td data-label="Плотность">{grav(h.gravity)}</td>
                  <td data-label="Температура">{temp(h.temperature)}</td>
                  <td data-label="Батарея">{pct(h.battery)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getHydrometers } from '../api'
import { grav, temp, pct } from '../fmt'
import { useTitle } from '../useTitle'

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
      <h2>Гидрометры</h2>
      <table>
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
              <td>{h.name ?? h.id}</td>
              <td>
                <span className={h.active_session_id ? 'badge active' : 'badge'}>
                  {h.active_session_id ? 'активна' : 'нет сессии'}
                </span>
              </td>
              <td>{grav(h.gravity)}</td>
              <td>{temp(h.temperature)}</td>
              <td>{pct(h.battery)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

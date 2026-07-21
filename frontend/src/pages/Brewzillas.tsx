import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getBrewzillas } from '../api'
import { temp, pct } from '../fmt'
import { useTitle } from '../useTitle'

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
      <h2>Пивоварни</h2>
      <table>
        <thead>
          <tr><th>Имя</th><th>Статус</th><th>Температура</th><th>Цель</th><th>Нагрев</th></tr>
        </thead>
        <tbody>
          {data.map((b) => (
            <tr key={b.id} className="row" onClick={() => navigate(`/brewzillas/${b.id}`)}>
              <td>{b.name ?? b.id}</td>
              <td>
                <span className={b.active_session_id ? 'badge active' : 'badge'}>
                  {b.active_session_id ? 'варит' : 'простой'}
                </span>
              </td>
              <td>{temp(b.temperature)}</td>
              <td>{temp(b.target_temperature)}</td>
              <td>{b.heating_enabled ? pct(b.heating_utilisation) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

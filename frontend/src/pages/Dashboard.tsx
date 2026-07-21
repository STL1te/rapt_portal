import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getHydrometers } from '../api'
import { grav, temp, pct, dbm } from '../fmt'
import { useTitle } from '../useTitle'

export default function Dashboard() {
  useTitle('Дашборд')
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
    <h2>Дашборд</h2>
    <section className="panel">
    <h3 className="panel-title"><i className="fa-solid fa-flask" /> Гидрометры</h3>
    <div className="grid">
      {data.map((h) => (
        <Link key={h.id} to={`/hydrometers/${h.id}`} className="card">
          <div className="card-head">
            <span className="name"><i className="fa-solid fa-flask" /> {h.name ?? h.id}</span>
            <span className={h.active_session_id ? 'badge active' : 'badge'}>
              {h.active_session_id ? 'активна' : 'нет сессии'}
            </span>
          </div>
          <dl className="metrics">
            <div><dt><i className="fa-solid fa-droplet" /> Плотность</dt><dd>{grav(h.gravity)}</dd></div>
            <div><dt><i className="fa-solid fa-temperature-half" /> Температура</dt><dd>{temp(h.temperature)}</dd></div>
            <div><dt><i className="fa-solid fa-battery-three-quarters" /> Батарея</dt><dd>{pct(h.battery)}</dd></div>
            <div><dt><i className="fa-solid fa-wifi" /> Сигнал</dt><dd>{dbm(h.rssi)}</dd></div>
          </dl>
        </Link>
      ))}
    </div>
    </section>
    </>
  )
}

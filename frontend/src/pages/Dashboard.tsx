import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getHydrometers, getBrewzillas } from '../api'
import { grav, temp, pct, dbm } from '../fmt'
import { useTitle } from '../useTitle'

export default function Dashboard() {
  useTitle('Дашборд')
  const hydro = useQuery({
    queryKey: ['hydrometers'],
    queryFn: getHydrometers,
    refetchInterval: 60_000,
  })
  const brew = useQuery({
    queryKey: ['brewzillas'],
    queryFn: getBrewzillas,
    refetchInterval: 60_000,
  })

  if (hydro.isLoading || brew.isLoading) return <p>Загрузка…</p>
  if (hydro.error) return <p className="error">Ошибка: {String(hydro.error)}</p>

  return (
    <>
      <h2>Дашборд</h2>

      <section className="panel">
        <h3 className="panel-title">
          <i className="fa-solid fa-flask" /> Гидрометры
        </h3>
        <div className="grid">
          {hydro.data?.map((h) => (
            <Link key={h.id} to={`/hydrometers/${h.id}`} className="card">
              <div className="card-head">
                <span className="name">
                  <i className="fa-solid fa-flask" /> {h.name ?? h.id}
                </span>
                <span className={h.active_session_id ? 'badge active' : 'badge'}>
                  {h.active_session_id ? 'активна' : 'нет сессии'}
                </span>
              </div>
              <dl className="metrics">
                <div>
                  <dt>
                    <i className="fa-solid fa-droplet" /> Плотность
                  </dt>
                  <dd>{grav(h.gravity)}</dd>
                </div>
                <div>
                  <dt>
                    <i className="fa-solid fa-temperature-half" /> Температура
                  </dt>
                  <dd>{temp(h.temperature)}</dd>
                </div>
                <div>
                  <dt>
                    <i className="fa-solid fa-battery-three-quarters" /> Батарея
                  </dt>
                  <dd>{pct(h.battery)}</dd>
                </div>
                <div>
                  <dt>
                    <i className="fa-solid fa-wifi" /> Сигнал
                  </dt>
                  <dd>{dbm(h.rssi)}</dd>
                </div>
              </dl>
            </Link>
          ))}
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">
          <i className="fa-solid fa-fire-burner" /> Пивоварни
        </h3>
        <div className="grid">
          {brew.data?.length ? (
            brew.data.map((b) => (
              <Link key={b.id} to={`/brewzillas/${b.id}`} className="card">
                <div className="card-head">
                  <span className="name">
                    <i className="fa-solid fa-fire-burner" /> {b.name ?? b.id}
                  </span>
                  <span className={b.active_session_id ? 'badge active' : 'badge'}>
                    {b.active_session_id ? 'варит' : 'простой'}
                  </span>
                </div>
                <dl className="metrics">
                  <div>
                    <dt>
                      <i className="fa-solid fa-temperature-half" /> Температура
                    </dt>
                    <dd>{temp(b.temperature)}</dd>
                  </div>
                  <div>
                    <dt>
                      <i className="fa-solid fa-bullseye" /> Цель
                    </dt>
                    <dd>{temp(b.target_temperature)}</dd>
                  </div>
                  <div>
                    <dt>
                      <i className="fa-solid fa-fire" /> Нагрев
                    </dt>
                    <dd>{b.heating_enabled ? pct(b.heating_utilisation) : '—'}</dd>
                  </div>
                  <div>
                    <dt>
                      <i className="fa-solid fa-wifi" /> Сигнал
                    </dt>
                    <dd>{dbm(b.rssi)}</dd>
                  </div>
                </dl>
              </Link>
            ))
          ) : (
            <p className="muted">Пивоварен нет.</p>
          )}
        </div>
      </section>
    </>
  )
}

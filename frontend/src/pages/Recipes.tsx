import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getProfiles } from '@/api'
import { useTitle } from '@/hooks/useTitle'

export default function Recipes() {
  useTitle('Рецепты')
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['profiles'],
    queryFn: getProfiles,
    refetchInterval: 60_000,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length)
    return <p>Рецептов не найдено. Запустите «Sync profiles» в системных синках.</p>

  return (
    <>
      <div className="page-head">
        <h2>Рецепты</h2>
        <div className="dates muted">Всего: {data.length}</div>
      </div>

      <section className="panel">
        <div className="table-wrap mobile-cards">
          <table className="table-in-panel mobile-cards">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Тип</th>
                <th>Шагов</th>
                <th>Доступ</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className="row" onClick={() => navigate(`/recipes/${p.id}`)}>
                  <td data-label="Имя">{p.name ?? p.id}</td>
                  <td data-label="Тип">{p.profile_type_name ?? '—'}</td>
                  <td data-label="Шагов">{p.step_count}</td>
                  <td data-label="Доступ">
                    <span className={p.public ? 'badge active' : 'badge'}>
                      {p.public ? 'публичный' : 'личный'}
                    </span>
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

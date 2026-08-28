import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getProfiles } from '@/api'
import { useTitle } from '@/hooks/useTitle'

export default function Profiles() {
  useTitle('Профили')
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['profiles'],
    queryFn: getProfiles,
    refetchInterval: 60_000,
  })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <>
      <div className="page-head">
        <h2>Профили</h2>
        <div className="page-head-actions">
          <span className="dates muted">Всего: {data?.length ?? 0}</span>
          <button type="button" className="btn-solid" onClick={() => navigate('/profiles/wizard')}>
            <i className="fa-solid fa-wand-magic-sparkles" /> AI-мастер
          </button>
          <button type="button" onClick={() => navigate('/profiles/import')}>
            <i className="fa-solid fa-file-import" /> Импорт
          </button>
          <button type="button" onClick={() => navigate('/profiles/new')}>
            <i className="fa-solid fa-plus" /> Новый профиль
          </button>
        </div>
      </div>

      {!data?.length ? (
        <p>Профилей не найдено. Запустите «Sync profiles» в системных синках.</p>
      ) : (
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
                  <tr key={p.id} className="row" onClick={() => navigate(`/profiles/${p.id}`)}>
                    <td data-label="Имя">
                      {p.name ?? p.id}
                      {p.draft ? <span className="badge draft-badge">черновик</span> : null}
                    </td>
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
      )}
    </>
  )
}

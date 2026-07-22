import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { getYeasts } from '@/api'
import { temp } from '@/lib/fmt'
import { useTitle } from '@/hooks/useTitle'

type StatIcon =
  | 'fa-industry'
  | 'fa-hashtag'
  | 'fa-tag'
  | 'fa-box'
  | 'fa-temperature-half'
  | 'fa-percent'
  | 'fa-cloud'
  | 'fa-toggle-on'

function renderTempRange(min: number | null, max: number | null) {
  if (min == null && max == null) return '—'
  if (min != null && max != null) return `${temp(min)} — ${temp(max)}`
  return temp(min ?? max)
}

function stat(label: string, value: string, icon: StatIcon) {
  return (
    <article className="detail-card">
      <div className="detail-label">
        <i className={`fa-solid ${icon}`} /> {label}
      </div>
      <div className="detail-value">{value}</div>
    </article>
  )
}

export default function YeastDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['yeasts'],
    queryFn: getYeasts,
  })

  const yeast = data?.find((item) => item.id === id)
  useTitle(yeast?.name ?? 'Дрожжи')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!yeast) {
    return (
      <div>
        <a className="back" onClick={() => navigate('/yeasts')}>
          <i className="fa-solid fa-arrow-left" /> Дрожжи
        </a>
        <p>Штамм не найден.</p>
      </div>
    )
  }

  return (
    <div>
      <a className="back" onClick={() => navigate('/yeasts')}>
        <i className="fa-solid fa-arrow-left" /> Дрожжи
      </a>

      <div className="page-head">
        <div>
          <h2>{yeast.name ?? yeast.id}</h2>
          <div className="muted">
            {yeast.laboratory ?? 'Без лаборатории'}
            {yeast.product_id ? ` · ${yeast.product_id}` : ''}
          </div>
        </div>
        <div className="detail-badges">
          {yeast.type ? <span className="badge active">{yeast.type}</span> : null}
          {yeast.form ? <span className="badge">{yeast.form}</span> : null}
          {yeast.is_global ? <span className="badge">global</span> : null}
        </div>
      </div>

      <section className="detail-grid">
        {stat('Лаборатория', yeast.laboratory ?? '—', 'fa-industry')}
        {stat('Код продукта', yeast.product_id ?? '—', 'fa-hashtag')}
        {stat('Тип', yeast.type ?? '—', 'fa-tag')}
        {stat('Форма', yeast.form ?? '—', 'fa-box')}
        {stat(
          'Температурный диапазон',
          renderTempRange(yeast.min_temperature, yeast.max_temperature),
          'fa-temperature-half',
        )}
        {stat(
          'Аттенюация',
          yeast.attenuation == null ? '—' : `${Math.round(yeast.attenuation)}%`,
          'fa-percent',
        )}
        {stat('Флокуляция', yeast.flocculation ?? '—', 'fa-cloud')}
        {stat('Статус', yeast.archived ? 'Archived' : 'Active', 'fa-toggle-on')}
      </section>

      <section className="panel">
        <h3 className="panel-title">
          <i className="fa-solid fa-note-sticky" /> Описание
        </h3>
        <p className="detail-notes">{yeast.notes?.trim() || 'Описание не заполнено.'}</p>
      </section>
    </div>
  )
}

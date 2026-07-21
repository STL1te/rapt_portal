import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getYeasts, type Yeast } from '../api'
import { temp } from '../fmt'
import { useTitle } from '../useTitle'

const PAGE_SIZE = 12
const SORT_OPTIONS = [
  { value: 'laboratory', label: 'Лаборатория' },
  { value: 'name', label: 'Название' },
  { value: 'type', label: 'Тип' },
  { value: 'attenuation', label: 'Аттенюация' },
  { value: 'temperature', label: 'Температура' },
] as const

type SortKey = typeof SORT_OPTIONS[number]['value']

function normalizeSearch(value: string) {
  return value
    .toLocaleLowerCase()
    .replace(/[^a-zа-яё0-9]+/gi, '')
}

function yeastSearchText(yeast: Yeast) {
  return [
    yeast.name,
    yeast.product_id,
    yeast.laboratory,
    yeast.type,
    yeast.form,
    yeast.flocculation,
    yeast.notes,
  ]
    .filter(Boolean)
    .join(' ')
    .toLocaleLowerCase()
}

function matchesSearch(yeast: Yeast, query: string) {
  if (!query) return true

  const raw = yeastSearchText(yeast)
  if (raw.includes(query)) return true

  const normalizedQuery = normalizeSearch(query)
  if (!normalizedQuery) return true

  return normalizeSearch(raw).includes(normalizedQuery)
}

function getPageTokens(currentPage: number, totalPages: number): Array<number | 'ellipsis'> {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1)
  }

  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, 'ellipsis', totalPages]
  }

  if (currentPage >= totalPages - 3) {
    return [1, 'ellipsis', totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
  }

  return [1, 'ellipsis', currentPage - 1, currentPage, currentPage + 1, 'ellipsis', totalPages]
}

function compareText(a: string | null, b: string | null) {
  return (a ?? '').localeCompare(b ?? '', 'ru', { sensitivity: 'base' })
}

function compareNumber(a: number | null, b: number | null) {
  return (a ?? Number.NEGATIVE_INFINITY) - (b ?? Number.NEGATIVE_INFINITY)
}

function tempRange(yeast: Yeast) {
  if (yeast.min_temperature == null && yeast.max_temperature == null) return '—'
  if (yeast.min_temperature != null && yeast.max_temperature != null) {
    return `${temp(yeast.min_temperature)} — ${temp(yeast.max_temperature)}`
  }
  return temp(yeast.min_temperature ?? yeast.max_temperature)
}

export default function Yeasts() {
  useTitle('Дрожжи')
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [formFilter, setFormFilter] = useState('all')
  const [sortBy, setSortBy] = useState<SortKey>('laboratory')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)

  const { data, isLoading, error } = useQuery({
    queryKey: ['yeasts'],
    queryFn: getYeasts,
  })

  const typeOptions = useMemo(
    () => Array.from(new Set((data ?? []).map((item) => item.type).filter((value): value is string => Boolean(value)))).sort(),
    [data],
  )
  const formOptions = useMemo(
    () => Array.from(new Set((data ?? []).map((item) => item.form).filter((value): value is string => Boolean(value)))).sort(),
    [data],
  )

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    const items = (data ?? []).filter((item) => {
      if (typeFilter !== 'all' && item.type !== typeFilter) return false
      if (formFilter !== 'all' && item.form !== formFilter) return false
      if (!matchesSearch(item, query)) return false
      return true
    })

    items.sort((a, b) => {
      let result = 0
      switch (sortBy) {
        case 'name':
          result = compareText(a.name, b.name)
          break
        case 'type':
          result = compareText(a.type, b.type) || compareText(a.name, b.name)
          break
        case 'attenuation':
          result = compareNumber(a.attenuation, b.attenuation) || compareText(a.name, b.name)
          break
        case 'temperature':
          result = compareNumber(a.min_temperature, b.min_temperature) || compareText(a.name, b.name)
          break
        case 'laboratory':
        default:
          result = compareText(a.laboratory, b.laboratory) || compareText(a.name, b.name)
          break
      }
      return sortDir === 'asc' ? result : -result
    })

    return items
  }, [data, formFilter, search, sortBy, sortDir, typeFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return filtered.slice(start, start + PAGE_SIZE)
  }, [currentPage, filtered])
  const pageTokens = useMemo(() => getPageTokens(currentPage, totalPages), [currentPage, totalPages])

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <>
      <div className="page-head">
        <h2>Дрожжи</h2>
        <div className="dates muted">Всего: {data?.length ?? 0}</div>
      </div>

      <section className="panel">
        <div className="toolbar">
          <label className="field field-search">
            <span>Поиск</span>
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
              placeholder="Название, код, лаборатория"
            />
          </label>

          <label className="field">
            <span>Тип</span>
            <select
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value)
                setPage(1)
              }}
            >
              <option value="all">Все</option>
              {typeOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>

          <label className="field">
            <span>Форма</span>
            <select
              value={formFilter}
              onChange={(event) => {
                setFormFilter(event.target.value)
                setPage(1)
              }}
            >
              <option value="all">Все</option>
              {formOptions.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>

          <label className="field">
            <span>Сортировка</span>
            <select
              value={sortBy}
              onChange={(event) => {
                setSortBy(event.target.value as SortKey)
                setPage(1)
              }}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="field field-compact">
            <span>Порядок</span>
            <select
              value={sortDir}
              onChange={(event) => {
                setSortDir(event.target.value as 'asc' | 'desc')
                setPage(1)
              }}
            >
              <option value="asc">По возрастанию</option>
              <option value="desc">По убыванию</option>
            </select>
          </label>
        </div>

        {!filtered.length ? (
          <p className="muted">Ничего не найдено.</p>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Лаборатория</th>
                  <th>Тип</th>
                  <th>Форма</th>
                  <th>Температура</th>
                  <th>Аттенюация</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((yeast) => (
                  <tr key={yeast.id} className="row" onClick={() => navigate(`/yeasts/${yeast.id}`)}>
                    <td>
                      <div className="table-title">{yeast.name ?? yeast.id}</div>
                      <div className="table-subtitle">{yeast.product_id ?? yeast.id}</div>
                    </td>
                    <td>{yeast.laboratory ?? '—'}</td>
                    <td>{yeast.type ?? '—'}</td>
                    <td>{yeast.form ?? '—'}</td>
                    <td>{tempRange(yeast)}</td>
                    <td>{yeast.attenuation == null ? '—' : `${Math.round(yeast.attenuation)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="pagination">
              <span className="muted">
                {filtered.length} записей · страница {currentPage} из {totalPages}
              </span>
              <div className="pagination-actions">
                <button type="button" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                  Назад
                </button>
                {pageTokens.map((token, index) => (
                  token === 'ellipsis' ? (
                    <span key={`ellipsis-${index}`} className="pagination-ellipsis">…</span>
                  ) : (
                    <button
                      key={token}
                      type="button"
                      className={token === currentPage ? 'page-button active' : 'page-button'}
                      onClick={() => setPage(token)}
                    >
                      {token}
                    </button>
                  )
                ))}
                <button type="button" disabled={currentPage >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
                  Далее
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </>
  )
}

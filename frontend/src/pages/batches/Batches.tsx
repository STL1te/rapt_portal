import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { createBatch, getBatches } from '@/api'
import type { Batch } from '@/types'
import { batchStatus, day, dayFmt, phases, STATUS, today, type BatchStatus } from '@/lib/batch'
import { useTitle } from '@/hooks/useTitle'
import BatchForm from './BatchForm'

const DAY_MS = 86_400_000

export function StatusBadge({ status }: { status: BatchStatus }) {
  return (
    <span
      className="badge batch-badge"
      style={{ '--c': STATUS[status].color } as React.CSSProperties}
    >
      {STATUS[status].label}
    </span>
  )
}

// ponytail: all batches share one time axis; past a year or two of history the bars get thin —
// add a range picker when that happens.
function Gantt({ batches }: { batches: Batch[] }) {
  const navigate = useNavigate()
  const now = today()
  const rows = [...batches].reverse().map((b) => ({ b, segments: phases(b, now) }))
  const start = Math.min(...batches.map((b) => day(b.bottled_on))) - 3 * DAY_MS
  const end =
    Math.max(day(now), ...rows.flatMap((r) => r.segments.map((s) => day(s.to)))) + 3 * DAY_MS
  const pos = (t: number) => ((t - start) / (end - start)) * 100

  // Weeks while a few months fit, month starts beyond that. At most five ticks so the labels
  // fit a phone, and none at the right edge where the track would cut the label.
  const weekly = end - start <= 120 * DAY_MS
  const stepWeeks = Math.ceil((end - start) / (7 * DAY_MS) / 5)
  const stepMonths = Math.ceil((end - start) / (30 * DAY_MS) / 5)
  const s = new Date(start)
  const ticks: number[] = []
  for (
    let t = weekly ? new Date(start) : new Date(s.getFullYear(), s.getMonth() + 1, 1);
    pos(t.getTime()) < 88;
    t = weekly
      ? new Date(t.getTime() + stepWeeks * 7 * DAY_MS)
      : new Date(t.getFullYear(), t.getMonth() + stepMonths, 1)
  )
    ticks.push(t.getTime())
  const tickLabel = (t: number) =>
    new Date(t).toLocaleDateString(
      undefined,
      weekly ? { day: 'numeric', month: 'short' } : { month: 'short', year: '2-digit' },
    )

  return (
    <section className="panel">
      <div className="batch-legend">
        {(Object.keys(STATUS) as BatchStatus[])
          .filter((s) => s !== 'finished')
          .map((s) => (
            <span key={s}>
              <i style={{ background: STATUS[s].color }} /> {STATUS[s].label}
            </span>
          ))}
        <span className="muted">бледные — завершённые</span>
      </div>
      <div className="gantt">
        <div className="gantt-row gantt-axis">
          <div />
          <div className="gantt-track">
            {ticks.map((t) => (
              <span key={t} style={{ left: `${pos(t)}%` }}>
                {tickLabel(t)}
              </span>
            ))}
          </div>
        </div>
        {rows.map(({ b, segments }) => (
          <div
            key={b.id}
            className={`gantt-row row${b.finished_on ? ' finished' : ''}`}
            onClick={() => navigate(`/batches/${b.id}`)}
          >
            <div className="gantt-name" title={b.name}>
              {b.name}
            </div>
            <div className="gantt-track">
              {segments.map((s) => (
                <span
                  key={s.status}
                  className="gantt-bar"
                  title={`${STATUS[s.status].label}: ${dayFmt(s.from)} — ${dayFmt(s.to)}`}
                  style={{
                    left: `${pos(day(s.from))}%`,
                    width: `${pos(day(s.to)) - pos(day(s.from))}%`,
                    background: STATUS[s.status].color,
                  }}
                />
              ))}
              <i className="gantt-today" style={{ left: `${pos(day(now))}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function Batches() {
  useTitle('Партии')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const { data, isLoading, error } = useQuery({ queryKey: ['batches'], queryFn: getBatches })

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>

  return (
    <>
      <div className="page-head">
        <h2>Партии</h2>
        <div className="page-head-actions">
          {creating ? null : (
            <button type="button" className="btn-solid" onClick={() => setCreating(true)}>
              <i className="fa-solid fa-plus" /> Новая партия
            </button>
          )}
        </div>
      </div>

      {creating ? (
        <BatchForm
          submitLabel="Создать"
          onCancel={() => setCreating(false)}
          onSubmit={async (input) => {
            const batch = await createBatch(input)
            await queryClient.invalidateQueries({ queryKey: ['batches'] })
            navigate(`/batches/${batch.id}`)
          }}
        />
      ) : null}

      {!data?.length ? (
        <p className="muted">Партий пока нет.</p>
      ) : (
        <>
          <Gantt batches={data} />
          <section className="panel">
            <div className="table-wrap mobile-cards">
              <table className="table-in-panel mobile-cards">
                <thead>
                  <tr>
                    <th>Партия</th>
                    <th>Статус</th>
                    <th>Розлив</th>
                    <th>Газация до</th>
                    <th>Созревание до</th>
                    <th>Остаток</th>
                    <th>Окончание</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((b) => (
                    <tr key={b.id} className="row" onClick={() => navigate(`/batches/${b.id}`)}>
                      <td data-label="Партия">{b.name}</td>
                      <td data-label="Статус">
                        <StatusBadge status={batchStatus(b)} />
                      </td>
                      <td data-label="Розлив">{dayFmt(b.bottled_on)}</td>
                      <td data-label="Газация до">{dayFmt(b.carbonation_until)}</td>
                      <td data-label="Созревание до">{dayFmt(b.conditioning_until)}</td>
                      <td data-label="Остаток">
                        {b.remaining_l} / {b.volume_l} л
                      </td>
                      <td data-label="Окончание">{dayFmt(b.finished_on)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  )
}

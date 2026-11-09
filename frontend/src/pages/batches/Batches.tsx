import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Brush,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { createBatch, getBatches } from '@/api'
import type { Batch } from '@/types'
import { batchStatus, day, dayFmt, phases, STATUS, today, type BatchStatus } from '@/lib/batch'
import { useTitle } from '@/hooks/useTitle'
import BatchForm from './BatchForm'

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

const WINDOW_DAYS = 90
const ROW_PX = 44

/** Name of the batch, drawn above its bar inside the plot so no column eats a phone's width. */
function NameTick({
  x,
  y,
  payload,
  rows,
  onOpen,
}: {
  x?: number
  y?: number
  payload?: { value: number }
  rows: Batch[]
  onOpen: (b: Batch) => void
}) {
  const b = payload ? rows[payload.value] : undefined
  if (!b || x == null || y == null) return null
  return (
    <text
      x={x}
      y={y - 12}
      fontSize={13}
      fill={b.finished_on ? 'var(--muted)' : 'var(--text)'}
      style={{ cursor: 'pointer' }}
      onClick={() => onOpen(b)}
    >
      {b.name}
    </text>
  )
}

/** Every phase is a thick line at its batch's row over a day-by-day series, so the Brush
 *  zooms and pans time the same way it does on the hydrometer chart. */
function Gantt({ batches }: { batches: Batch[] }) {
  const navigate = useNavigate()
  const open = (b: Batch) => navigate(`/batches/${b.id}`)
  const now = today()
  const rows = [...batches].reverse() // oldest on top
  const series = rows.flatMap((b, i) =>
    phases(b, now).map((p) => ({ ...p, b, i, key: `r${i}_${p.status}` })),
  )
  const byKey = Object.fromEntries(series.map((s) => [s.key, s]))

  const data: Record<string, number>[] = []
  const last = Math.max(day(now), ...series.map((s) => day(s.to)))
  // setDate keeps local midnight across DST, adding 24h would not
  for (
    const d = new Date(Math.min(...rows.map((b) => day(b.bottled_on))));
    d.getTime() <= last;
    d.setDate(d.getDate() + 1)
  ) {
    const t = d.getTime()
    const point: Record<string, number> = { t }
    for (const s of series) if (t >= day(s.from) && t <= day(s.to)) point[s.key] = s.i
    data.push(point)
  }
  const todayIndex = data.findIndex((p) => p.t >= day(now))
  const startIndex = Math.max(0, todayIndex - WINDOW_DAYS)
  const endIndex = Math.min(data.length - 1, todayIndex + WINDOW_DAYS)

  const fmtDay = (t: number) =>
    new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  const fmtMonth = (t: number) =>
    new Date(t).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })
  const lines = (width: number) =>
    series.map((s) => (
      <Line
        key={s.key}
        dataKey={s.key}
        name={s.b.name}
        stroke={STATUS[s.status].color}
        strokeOpacity={s.b.finished_on ? 0.35 : 1}
        strokeWidth={width}
        strokeLinecap="butt"
        dot={false}
        activeDot={false}
        isAnimationActive={false}
        style={{ cursor: 'pointer' }}
        onClick={() => open(s.b)}
      />
    ))

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
      <ResponsiveContainer width="100%" height={rows.length * ROW_PX + 90}>
        <LineChart data={data} margin={{ top: 20, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.2)" horizontal={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={fmtDay}
            stroke="#888"
          />
          <YAxis
            type="number"
            domain={[-0.5, rows.length - 0.5]}
            ticks={rows.map((_, i) => i)}
            reversed
            mirror
            axisLine={false}
            tickLine={false}
            tick={<NameTick rows={rows} onOpen={open} />}
          />
          <Tooltip
            isAnimationActive={false}
            labelFormatter={(t) => new Date(Number(t)).toLocaleDateString()}
            formatter={(_value, name, item) =>
              [STATUS[byKey[String(item.dataKey)].status].label, name] as const
            }
          />
          <ReferenceLine x={day(now)} stroke="var(--accent)" strokeDasharray="4 3" />
          {lines(14)}
          <Brush
            dataKey="t"
            height={44}
            travellerWidth={10}
            startIndex={startIndex}
            endIndex={endIndex}
            stroke="var(--accent)"
            fill="var(--panel)"
            tickFormatter={fmtMonth}
          >
            {/* no axes in here: recharts 3 shares them with the main chart and a hidden
                preview YAxis replaces the one that draws the batch names */}
            <LineChart>{lines(3)}</LineChart>
          </Brush>
        </LineChart>
      </ResponsiveContainer>
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

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { addBatchVolume, deleteBatch, deleteBatchVolume, getBatch, updateBatch } from '@/api'
import MetricCard from '@/components/MetricCard'
import type { Batch, BatchInput } from '@/types'
import { batchStatus, day, dayFmt, STATUS, today } from '@/lib/batch'
import { useTitle } from '@/hooks/useTitle'
import BatchForm from './BatchForm'
import { StatusBadge } from './Batches'

function input(b: Batch): BatchInput {
  const { name, bottled_on, volume_l, carbonation_until, conditioning_until, finished_on, notes } =
    b
  return { name, bottled_on, volume_l, carbonation_until, conditioning_until, finished_on, notes }
}

function VolumeChart({ batch }: { batch: Batch }) {
  const now = today()
  // the line runs to the day the batch ended (or today), the marks may sit further ahead
  const lineEnd = batch.finished_on ?? now
  const points = [
    { t: day(batch.bottled_on), v: batch.volume_l },
    ...batch.volumes.map((v) => ({ t: day(v.recorded_on), v: v.volume_l })),
  ]
  const last = points[points.length - 1]
  if (day(lineEnd) > last.t) points.push({ t: day(lineEnd), v: last.v })

  const marks = [
    { at: batch.bottled_on, label: 'Розлив', color: 'var(--muted)' },
    { at: batch.carbonation_until, label: 'Конец газации', color: STATUS.carbonating.color },
    { at: batch.conditioning_until, label: 'Конец созревания', color: STATUS.conditioning.color },
    batch.finished_on
      ? { at: batch.finished_on, label: 'Окончание', color: STATUS.finished.color }
      : { at: now, label: 'Сегодня', color: 'var(--accent)' },
  ]
  const domainEnd = Math.max(last.t, ...marks.map((m) => day(m.at)))

  return (
    <ResponsiveContainer width="100%" height={360}>
      <LineChart data={points} margin={{ top: 28, right: 28, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.2)" />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={[day(batch.bottled_on), domainEnd]}
          tickFormatter={(t: number) => new Date(t).toLocaleDateString()}
          stroke="#888"
        />
        <YAxis domain={[0, 'auto']} unit=" л" stroke="#888" />
        <Tooltip
          isAnimationActive={false}
          labelFormatter={(t) => new Date(Number(t)).toLocaleDateString()}
          formatter={(value) => [`${value} л`, 'Объём'] as const}
        />
        {marks.map((m, i) => (
          <ReferenceLine
            key={m.label}
            x={day(m.at)}
            stroke={m.color}
            strokeDasharray="4 3"
            // alternate heights so marks a few days apart do not print over each other
            label={{
              value: m.label,
              position: i % 2 ? 'insideTopLeft' : 'top',
              fill: m.color,
              fontSize: 12,
            }}
          />
        ))}
        <Line
          type="stepAfter"
          dataKey="v"
          stroke={STATUS.ready.color}
          strokeWidth={2}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function BatchDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [volumeDay, setVolumeDay] = useState(today)
  const [volume, setVolume] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['batch', id],
    queryFn: () => getBatch(id as string),
    enabled: Boolean(id),
  })
  useTitle(data?.name ?? 'Партия')

  if (isLoading) return <p>Загрузка…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data) return null
  const batch = data

  async function run(action: () => Promise<Batch | void>) {
    setBusy(true)
    setActionError(null)
    try {
      const updated = await action()
      if (updated) queryClient.setQueryData(['batch', id], updated)
      await queryClient.invalidateQueries({ queryKey: ['batches'] })
      return true
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  const status = batchStatus(batch)
  const finish = (finished_on: string | null) =>
    run(() => updateBatch(batch.id, { ...input(batch), finished_on }))

  return (
    <div>
      <div className="page-head">
        <div>
          <h2>{batch.name}</h2>
          <div className="muted">Розлив {dayFmt(batch.bottled_on)}</div>
        </div>
        <div className="detail-badges">
          <StatusBadge status={status} />
        </div>
      </div>

      <div className="profile-actions">
        {batch.finished_on ? (
          <button type="button" disabled={busy} onClick={() => void finish(null)}>
            <i className="fa-solid fa-play" /> Возобновить
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={() => void finish(today())}>
            <i className="fa-solid fa-stop" /> Партия закончилась
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => setEditing((v) => !v)}>
          <i className="fa-solid fa-pen" /> Редактировать
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (!window.confirm(`Удалить партию «${batch.name}»?`)) return
            void run(() => deleteBatch(batch.id)).then((ok) => ok && navigate('/batches'))
          }}
        >
          <i className="fa-solid fa-trash" /> Удалить
        </button>
      </div>
      {actionError ? <p className="error">{actionError}</p> : null}

      {editing ? (
        <BatchForm
          initial={input(batch)}
          submitLabel="Сохранить"
          onCancel={() => setEditing(false)}
          onSubmit={async (next) => {
            queryClient.setQueryData(['batch', id], await updateBatch(batch.id, next))
            await queryClient.invalidateQueries({ queryKey: ['batches'] })
            setEditing(false)
          }}
        />
      ) : null}

      <section className="stats stats-compact">
        <MetricCard
          label="Остаток"
          value={`${batch.remaining_l} л`}
          sub={`из ${batch.volume_l} л`}
          icon="fa-solid fa-beer-mug-empty"
        />
        <MetricCard
          label="Газация до"
          value={dayFmt(batch.carbonation_until)}
          icon="fa-solid fa-bottle-droplet"
        />
        <MetricCard
          label="Созревание до"
          value={dayFmt(batch.conditioning_until)}
          icon="fa-solid fa-hourglass-half"
        />
        <MetricCard
          label="Окончание"
          value={dayFmt(batch.finished_on)}
          icon="fa-solid fa-flag-checkered"
          tone={batch.finished_on ? 'quiet' : undefined}
        />
      </section>

      <section className="panel">
        <VolumeChart batch={batch} />
      </section>

      <section className="panel">
        <h3 className="panel-title">
          <i className="fa-solid fa-scale-balanced" /> Остатки
        </h3>
        <form
          className="field-row"
          onSubmit={(e) => {
            e.preventDefault()
            void run(() => addBatchVolume(batch.id, volumeDay, Number(volume))).then(
              (ok) => ok && setVolume(''),
            )
          }}
        >
          <label className="field">
            <span>Дата</span>
            <input
              type="date"
              required
              min={batch.bottled_on}
              value={volumeDay}
              onChange={(e) => setVolumeDay(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Осталось, л</span>
            <input
              type="number"
              required
              min={0}
              step={0.1}
              value={volume}
              onChange={(e) => setVolume(e.target.value)}
            />
          </label>
          <div className="field profile-wizard-actions">
            <span>&nbsp;</span>
            <button type="submit" className="btn-solid" disabled={busy}>
              Обновить остаток
            </button>
          </div>
        </form>
        {batch.volumes.length ? (
          <div className="table-wrap">
            <table className="table-in-panel">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Остаток</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {[...batch.volumes].reverse().map((v) => (
                  <tr key={v.id}>
                    <td>{dayFmt(v.recorded_on)}</td>
                    <td>{v.volume_l} л</td>
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label="Удалить запись"
                        disabled={busy}
                        onClick={() => void run(() => deleteBatchVolume(batch.id, v.id))}
                      >
                        <i className="fa-solid fa-xmark" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {batch.notes?.trim() ? (
        <section className="panel">
          <p className="detail-notes">{batch.notes}</p>
        </section>
      ) : null}
    </div>
  )
}

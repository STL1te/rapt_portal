import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Brush,
  ResponsiveContainer,
} from 'recharts'
import { temp } from '@/lib/fmt'
import { getBrewTelemetry, type BrewSession } from '@/api'

type RangePreset = '24h' | '3d' | '7d' | 'all'

const RANGE_MS: Record<'24h' | '3d' | '7d', number> = {
  '24h': 24 * 60 * 60 * 1000,
  '3d': 3 * 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
}

const PRESETS: RangePreset[] = ['24h', '3d', '7d', 'all']

function parseUtc(value: string) {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`).getTime()
}

export default function BrewChart({
  sessionId,
  session,
}: {
  sessionId: string
  session?: BrewSession | null
}) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({})
  const [range, setRange] = useState<RangePreset>('7d')
  const toggle = (key?: string | number) => key && setHidden((h) => ({ ...h, [key]: !h[key] }))

  const { data, isLoading, error } = useQuery({
    queryKey: ['brew-telemetry', sessionId],
    queryFn: () => getBrewTelemetry(sessionId),
  })

  if (isLoading) return <p>Загрузка графика…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length) return <p>Нет точек телеметрии.</p>

  const steps = (session?.profile?.steps ?? []).slice().sort((a, b) => a.order - b.order)
  const stepById = new Map(steps.map((step) => [step.id ?? '', step]))

  const points = data.map((p) => ({
    t: parseUtc(p.timestamp),
    temperature: p.temperature,
    target: p.target_temperature,
    wort: p.control_device_temperature,
    step: stepById.get(p.profile_step_id ?? '')?.name ?? null,
  }))

  const end = points[points.length - 1]?.t ?? 0
  const filteredPoints =
    range === 'all'
      ? points
      : points.filter((point) => point.t >= end - RANGE_MS[range]).length
        ? points.filter((point) => point.t >= end - RANGE_MS[range])
        : points

  const fmtTime = (t: number) => new Date(t).toLocaleDateString()
  const fmtBrush = (t: number) => {
    const d = new Date(t)
    return `${d.getDate()}.${d.getMonth() + 1}`
  }
  const C = { temperature: '#4ea1ff', target: '#ff8a4e', wort: '#35c28a' }

  return (
    <>
      <div className="chart-toolbar">
        <span className="chart-toolbar-label">Диапазон</span>
        <div className="chart-presets">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`chart-preset${range === preset ? ' active' : ''}`}
              onClick={() => setRange(preset)}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={480}>
        <LineChart data={filteredPoints} margin={{ top: 8, right: 28, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.2)" />
          <XAxis
            dataKey="t"
            type="number"
            domain={['dataMin', 'dataMax']}
            scale="time"
            tickFormatter={fmtTime}
            stroke="#888"
          />
          <YAxis domain={['auto', 'auto']} stroke="#888" unit="°" />
          <Tooltip
            allowEscapeViewBox={{ x: false, y: false }}
            isAnimationActive={false}
            labelFormatter={(t, payload) => {
              const point = payload?.[0]?.payload as { step?: string | null } | undefined
              return point?.step
                ? `${new Date(Number(t)).toLocaleString()} · ${point.step}`
                : new Date(Number(t)).toLocaleString()
            }}
            formatter={(value, name, item) => {
              if (
                item.dataKey === 'temperature' ||
                item.dataKey === 'wort' ||
                item.dataKey === 'target'
              ) {
                const num = value == null ? null : Number(value as any)
                return [temp(num), name]
              }

              return [value, name]
            }}
          />
          <Legend
            wrapperStyle={{ paddingTop: 16 }}
            onClick={(e) => toggle(e.dataKey as string)}
            formatter={(value, entry) => (
              <span
                style={{
                  opacity: hidden[(entry as { dataKey?: string })?.dataKey ?? ''] ? 0.4 : 1,
                }}
              >
                {value}
              </span>
            )}
          />
          <Line
            type="monotone"
            dataKey="temperature"
            name="Котёл"
            stroke={C.temperature}
            dot={false}
            connectNulls
            hide={hidden.temperature}
          />
          <Line
            type="monotone"
            dataKey="wort"
            name="Сусло"
            stroke={C.wort}
            dot={false}
            connectNulls
            hide={hidden.wort}
          />
          <Line
            type="monotone"
            dataKey="target"
            name="Целевая"
            stroke={C.target}
            dot={false}
            connectNulls
            strokeDasharray="4 2"
            hide={hidden.target}
          />
          <Brush
            dataKey="t"
            height={44}
            travellerWidth={10}
            stroke={C.temperature}
            fill="var(--panel)"
            tickFormatter={fmtBrush}
          >
            <AreaChart>
              <Area
                type="monotone"
                dataKey="temperature"
                stroke={C.temperature}
                fill={C.temperature}
                fillOpacity={0.25}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </AreaChart>
          </Brush>
        </LineChart>
      </ResponsiveContainer>
    </>
  )
}

import { useState } from 'react'
import {
  Area,
  AreaChart,
  Brush,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { HydrometerTelemetryPoint } from '../api'
import { grav, temp } from '../fmt'

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

export default function HydrometerChart({ data }: { data: HydrometerTelemetryPoint[] }) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({})
  const [range, setRange] = useState<RangePreset>('7d')
  const toggle = (key?: string | number) => key && setHidden((h) => ({ ...h, [key]: !h[key] }))

  if (!data.length) return <p>Нет точек телеметрии.</p>

  const points = data.map((p) => ({
    t: parseUtc(p.timestamp),
    gravity: p.gravity,
    temperature: p.temperature,
    velocity: p.gravity_velocity != null ? Math.abs(p.gravity_velocity) : null,
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
  const fmtLegend = (value: string) =>
    ({
      gravity: 'Плотность',
      temperature: 'Температура',
      velocity: 'Скорость, points/day',
    })[value] ?? value
  const C = { gravity: '#e0a93a', temperature: '#4ea1ff', velocity: '#35c28a' }

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
          <YAxis yAxisId="g" orientation="left" domain={['auto', 'auto']} stroke={C.gravity} />
          <YAxis yAxisId="t" orientation="right" domain={['auto', 'auto']} stroke={C.temperature} />
          <YAxis yAxisId="v" hide domain={['auto', 'auto']} />
          <Tooltip
            allowEscapeViewBox={{ x: false, y: false }}
            isAnimationActive={false}
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
            formatter={(value, _name, item) => {
              const num = value == null ? null : Number(value)
              if (item.dataKey === 'gravity') return [grav(num), 'Плотность'] as const
              if (item.dataKey === 'temperature') return [temp(num), 'Температура'] as const
              if (item.dataKey === 'velocity')
                return [num == null ? '—' : `${num.toFixed(1)} points/day`, 'Скорость'] as const
              return [String(value ?? '—'), String(item.dataKey ?? '')] as const
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
                {fmtLegend(value)}
              </span>
            )}
          />
          <Line
            yAxisId="g"
            type="monotone"
            dataKey="gravity"
            name="gravity"
            stroke={C.gravity}
            dot={false}
            connectNulls
            hide={hidden.gravity}
          />
          <Line
            yAxisId="t"
            type="monotone"
            dataKey="temperature"
            name="temperature"
            stroke={C.temperature}
            dot={false}
            connectNulls
            hide={hidden.temperature}
          />
          <Line
            yAxisId="v"
            type="monotone"
            dataKey="velocity"
            name="velocity"
            stroke={C.velocity}
            dot={false}
            connectNulls
            strokeDasharray="4 2"
            hide={hidden.velocity}
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
                dataKey="gravity"
                stroke={C.gravity}
                fill={C.gravity}
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

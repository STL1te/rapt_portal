import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Brush,
  ResponsiveContainer,
} from 'recharts'
import { temp } from '../fmt'
import { getTelemetry } from '../api'

export default function HydrometerChart({ sessionId }: { sessionId: string }) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({})
  const toggle = (key?: string | number) => key && setHidden((h) => ({ ...h, [key]: !h[key] }))

  const { data, isLoading, error } = useQuery({
    queryKey: ['telemetry', sessionId],
    queryFn: () => getTelemetry(sessionId),
  })

  if (isLoading) return <p>Загрузка графика…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length) return <p>Нет точек телеметрии.</p>

  const parseUtc = (value: string) =>
    new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`).getTime()

  const points = data.map((p) => ({
    t: parseUtc(p.timestamp),
    gravity: p.gravity,
    temperature: p.temperature,
    velocity: p.gravity_velocity != null ? Math.abs(p.gravity_velocity) : null,
  }))

  const fmtTime = (t: number) => new Date(t).toLocaleDateString()
  const fmtBrush = (t: number) => {
    const d = new Date(t)
    return `${d.getDate()}.${d.getMonth() + 1}`
  }
  const C = { gravity: '#e0a93a', temperature: '#4ea1ff', velocity: '#35c28a' }

  return (
    <ResponsiveContainer width="100%" height={480}>
      <LineChart data={points} margin={{ top: 8, right: 28, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.2)" />
        <XAxis
          dataKey="t" type="number" domain={['dataMin', 'dataMax']}
          scale="time" tickFormatter={fmtTime} stroke="#888"
        />
        <YAxis yAxisId="g" orientation="left" domain={['auto', 'auto']} stroke={C.gravity} />
        <YAxis yAxisId="t" orientation="right" domain={['auto', 'auto']} stroke={C.temperature} />
        {/* velocity has its own scale (S.G. points/day); axis hidden to avoid clutter */}
        <YAxis yAxisId="v" hide domain={['auto', 'auto']} />
        <Tooltip
          allowEscapeViewBox={{ x: false, y: false }}
          isAnimationActive={false} 
          labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
          formatter={(value, name, item) => {
            if (item.dataKey === 'temperature') {
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
            <span style={{ opacity: hidden[(entry as { dataKey?: string })?.dataKey ?? ''] ? 0.4 : 1 }}>
              {value}
            </span>
          )}
        />
        <Line yAxisId="g" type="monotone" dataKey="gravity" name="Плотность, S.G."
          stroke={C.gravity} dot={false} connectNulls hide={hidden.gravity} />
        <Line yAxisId="t" type="monotone" dataKey="temperature" name="Температура"
          stroke={C.temperature} dot={false} connectNulls hide={hidden.temperature} />
        <Line yAxisId="v" type="monotone" dataKey="velocity" name="Скорость, S.G./день"
          stroke={C.velocity} dot={false} connectNulls strokeDasharray="4 2" hide={hidden.velocity} />
        <Brush dataKey="t" height={44} travellerWidth={10}
          stroke={C.temperature} fill="var(--panel)" tickFormatter={fmtBrush}>
          <AreaChart>
            <Area type="monotone" dataKey="gravity" stroke={C.gravity}
              fill={C.gravity} fillOpacity={0.25} dot={false} connectNulls isAnimationActive={false} />
          </AreaChart>
        </Brush>
      </LineChart>
    </ResponsiveContainer>
  )
}

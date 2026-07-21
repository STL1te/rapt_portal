import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Brush,
  ResponsiveContainer,
} from 'recharts'
import { getBrewTelemetry } from '../api'

export default function BrewChart({ sessionId }: { sessionId: string }) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({})
  const toggle = (key?: string | number) => key && setHidden((h) => ({ ...h, [key]: !h[key] }))

  const { data, isLoading, error } = useQuery({
    queryKey: ['brew-telemetry', sessionId],
    queryFn: () => getBrewTelemetry(sessionId),
  })

  if (isLoading) return <p>Загрузка графика…</p>
  if (error) return <p className="error">Ошибка: {String(error)}</p>
  if (!data?.length) return <p>Нет точек телеметрии.</p>

  const parseUtc = (value: string) =>
    new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`).getTime()

  const points = data.map((p) => ({
    t: parseUtc(p.timestamp),
    temperature: p.temperature,
    target: p.target_temperature,
    wort: p.control_device_temperature,
  }))

  const fmtTime = (t: number) => new Date(t).toLocaleDateString()
  const fmtBrush = (t: number) => {
    const d = new Date(t)
    return `${d.getDate()}.${d.getMonth() + 1}`
  }
  const C = { temperature: '#4ea1ff', target: '#ff8a4e', wort: '#35c28a' }

  return (
    <ResponsiveContainer width="100%" height={480}>
      <LineChart data={points} margin={{ top: 8, right: 28, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.2)" />
        <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']}
          scale="time" tickFormatter={fmtTime} stroke="#888" />
        <YAxis domain={['auto', 'auto']} stroke="#888" unit="°" />
        <Tooltip
          labelFormatter={(t) => new Date(Number(t)).toLocaleString()} 
          formatter={(value, name, item) => {
            if (item.dataKey === 'temperature' || item.dataKey === 'wort') {
              return [`${Number(value).toFixed(1)} °C`, name]
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
        <Line type="monotone" dataKey="temperature" name="Котёл, °C"
          stroke={C.temperature} dot={false} connectNulls hide={hidden.temperature} />
        <Line type="monotone" dataKey="wort" name="Сусло, °C"
          stroke={C.wort} dot={false} connectNulls hide={hidden.wort} />
        <Line type="monotone" dataKey="target" name="Целевая, °C"
          stroke={C.target} dot={false} connectNulls strokeDasharray="4 2" hide={hidden.target} />
        <Brush dataKey="t" height={44} travellerWidth={10}
          stroke={C.temperature} fill="var(--panel)" tickFormatter={fmtBrush}>
          <AreaChart>
            <Area type="monotone" dataKey="temperature" stroke={C.temperature}
              fill={C.temperature} fillOpacity={0.25} dot={false} connectNulls isAnimationActive={false} />
          </AreaChart>
        </Brush>
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function MetricCard({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string
  value: string
  sub?: string
  icon: string
  tone?: 'ok' | 'warn' | 'quiet' | 'info'
}) {
  return (
    <div className={tone ? `stat stat-${tone}` : 'stat'}>
      <span className="stat-label">
        <i className={icon} /> {label}
      </span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

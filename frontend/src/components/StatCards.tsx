export type Stat = { label: string; value: string; sub?: string; icon?: string }

export default function StatCards({ stats }: { stats: Stat[] }) {
  return (
    <div className="stats">
      {stats.map((s) => (
        <div key={s.label} className="stat">
          <span className="stat-label">
            {s.icon && <i className={s.icon} />} {s.label}
          </span>
          <span className="stat-value">{s.value}</span>
          {s.sub && <span className="stat-sub">{s.sub}</span>}
        </div>
      ))}
    </div>
  )
}

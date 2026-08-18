import { NavLink, Outlet } from 'react-router-dom'

const tabs = [{ to: 'syncs', label: 'Системные синки' }] as const

export default function Admin() {
  return (
    <>
      <div className="page-head">
        <h2>Администрирование</h2>
      </div>

      <nav className="pill-group admin-tabs">
        {tabs.map((tab) => (
          <NavLink key={tab.to} to={tab.to} className="pill">
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </>
  )
}

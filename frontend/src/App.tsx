import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import ThemeToggle from '@/components/ThemeToggle'
import BrewSessionPage from '@/pages/BrewSessionPage'
import BrewZillaDetail from '@/pages/BrewZillaDetail'
import Brewzillas from '@/pages/Brewzillas'
import Dashboard from '@/pages/Dashboard'
import HydrometerDetail from '@/pages/HydrometerDetail'
import Hydrometers from '@/pages/Hydrometers'
import HydrometerSessionPage from '@/pages/HydrometerSessionPage'
import SystemSyncs from '@/pages/SystemSyncs'
import YeastDetail from '@/pages/YeastDetail'
import Yeasts from '@/pages/Yeasts'

const primaryNavItems = [
  { to: '/', label: 'Дашборд', icon: 'fa-solid fa-gauge-high', end: true },
  { to: '/hydrometers', label: 'Гидрометры', icon: 'fa-solid fa-flask', end: false },
  { to: '/brewzillas', label: 'Пивоварни', icon: 'fa-solid fa-fire-burner', end: false },
  { to: '/yeasts', label: 'Дрожжи', icon: 'fa-solid fa-vial', end: false },
] as const

const secondaryNavItems = [
  { to: '/system-syncs', label: 'Системные синки', icon: 'fa-solid fa-gear' },
] as const

export default function App() {
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  useEffect(() => {
    document.body.classList.toggle('menu-open', sidebarOpen)
    return () => document.body.classList.remove('menu-open')
  }, [sidebarOpen])

  return (
    <div className="layout">
      <button
        type="button"
        className={`sidebar-backdrop${sidebarOpen ? ' open' : ''}`}
        aria-label="Закрыть меню"
        aria-hidden={!sidebarOpen}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="sidebar-head">
          <div className="brand">
            <img src="/favicon.png" className="brand-icon" alt="" /> RAPT Portal
          </div>
          <button
            type="button"
            className="sidebar-close"
            aria-label="Закрыть меню"
            onClick={() => setSidebarOpen(false)}
          >
            <i className="fa-solid fa-xmark" />
          </button>
        </div>

        <nav>
          {primaryNavItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <i className={item.icon} /> {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <nav className="sidebar-secondary-nav">
            {secondaryNavItems.map((item) => (
              <NavLink key={item.to} to={item.to}>
                <i className={item.icon} /> {item.label}
              </NavLink>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </aside>
      <main>
        <header className="mobile-topbar">
          <button
            type="button"
            className="menu-toggle"
            aria-label="Открыть меню"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen(true)}
          >
            <i className="fa-solid fa-bars" />
          </button>
          <div className="brand">
            <img src="/favicon.png" className="brand-icon" alt="" /> RAPT Portal
          </div>
          <ThemeToggle />
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/hydrometers" element={<Hydrometers />} />
          <Route path="/hydrometers/:id" element={<HydrometerDetail />} />
          <Route path="/hydrometer-sessions/:id" element={<HydrometerSessionPage />} />
          <Route path="/brewzillas" element={<Brewzillas />} />
          <Route path="/brewzillas/:id" element={<BrewZillaDetail />} />
          <Route path="/brew-sessions/:id" element={<BrewSessionPage />} />
          <Route path="/yeasts" element={<Yeasts />} />
          <Route path="/yeasts/:id" element={<YeastDetail />} />
          <Route path="/system-syncs" element={<SystemSyncs />} />
        </Routes>
      </main>
    </div>
  )
}

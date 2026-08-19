import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import ThemeToggle from '@/components/ThemeToggle'
import Admin from '@/pages/admin/Admin'
import SystemSyncs from '@/pages/admin/SystemSyncs'
import BrewSessionPage from '@/pages/brewzillas/BrewSessionPage'
import BrewZillaDetail from '@/pages/brewzillas/BrewZillaDetail'
import Brewzillas from '@/pages/brewzillas/Brewzillas'
import Dashboard from '@/pages/Dashboard'
import HydrometerDetail from '@/pages/hydrometers/HydrometerDetail'
import Hydrometers from '@/pages/hydrometers/Hydrometers'
import HydrometerSessionPage from '@/pages/hydrometers/HydrometerSessionPage'
import ProfileDetail from '@/pages/profiles/ProfileDetail'
import ProfileEditor from '@/pages/profiles/ProfileEditor'
import Profiles from '@/pages/profiles/Profiles'
import ProfileWizard from '@/pages/profiles/ProfileWizard'
import YeastDetail from '@/pages/yeasts/YeastDetail'
import Yeasts from '@/pages/yeasts/Yeasts'

const primaryNavItems = [
  { to: '/', label: 'Дашборд', icon: 'fa-solid fa-gauge-high', end: true },
  { to: '/hydrometers', label: 'Гидрометры', icon: 'fa-solid fa-flask', end: false },
  { to: '/brewzillas', label: 'Пивоварни', icon: 'fa-solid fa-fire-burner', end: false },
  { to: '/profiles', label: 'Профили', icon: 'fa-solid fa-scroll', end: false },
  { to: '/yeasts', label: 'Дрожжи', icon: 'fa-solid fa-vial', end: false },
] as const

export default function App() {
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('sidebar') === 'collapsed')

  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  useEffect(() => {
    document.body.classList.toggle('menu-open', sidebarOpen)
    return () => document.body.classList.remove('menu-open')
  }, [sidebarOpen])

  useEffect(() => {
    localStorage.setItem('sidebar', collapsed ? 'collapsed' : 'expanded')
  }, [collapsed])

  return (
    <div className="layout">
      <button
        type="button"
        className={`sidebar-backdrop${sidebarOpen ? ' open' : ''}`}
        aria-label="Закрыть меню"
        aria-hidden={!sidebarOpen}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`sidebar${sidebarOpen ? ' open' : ''}${collapsed ? ' collapsed' : ''}`}>
        <div className="sidebar-head">
          <div className="brand">
            <img src="/favicon.png" className="brand-icon" alt="" />
            <span className="nav-label">RAPT Portal</span>
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
            <NavLink key={item.to} to={item.to} end={item.end} title={item.label}>
              <i className={item.icon} /> <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <button
            type="button"
            className="icon-btn sidebar-collapse"
            aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((v) => !v)}
          >
            <i className={`fa-solid fa-angles-${collapsed ? 'right' : 'left'}`} />
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <button
            type="button"
            className="icon-btn topbar-menu"
            aria-label="Открыть меню"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <i className="fa-solid fa-bars" />
          </button>
          <div className="brand">
            <img src="/favicon.png" className="brand-icon" alt="" /> RAPT Portal
          </div>
          <div className="topbar-actions">
            <NavLink to="/admin" className="icon-btn" title="Администрирование">
              <i className="fa-solid fa-gear" />
            </NavLink>
            <ThemeToggle />
          </div>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/hydrometers" element={<Hydrometers />} />
          <Route path="/hydrometers/:id" element={<HydrometerDetail />} />
          <Route path="/hydrometer-sessions/:id" element={<HydrometerSessionPage />} />
          <Route path="/brewzillas" element={<Brewzillas />} />
          <Route path="/brewzillas/:id" element={<BrewZillaDetail />} />
          <Route path="/brew-sessions/:id" element={<BrewSessionPage />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/profiles/wizard" element={<ProfileWizard />} />
          <Route path="/profiles/new" element={<ProfileEditor />} />
          <Route path="/profiles/:id" element={<ProfileDetail />} />
          <Route path="/profiles/:id/edit" element={<ProfileEditor />} />
          <Route path="/yeasts" element={<Yeasts />} />
          <Route path="/yeasts/:id" element={<YeastDetail />} />
          <Route path="/admin" element={<Admin />}>
            <Route index element={<Navigate to="syncs" replace />} />
            <Route path="syncs" element={<SystemSyncs />} />
          </Route>
          <Route path="/system-syncs" element={<Navigate to="/admin/syncs" replace />} />
        </Routes>
      </main>
    </div>
  )
}

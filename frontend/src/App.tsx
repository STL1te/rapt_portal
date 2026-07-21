import { NavLink, Route, Routes } from 'react-router-dom'
import ThemeToggle from './components/ThemeToggle'
import BrewSessionPage from './pages/BrewSessionPage'
import BrewZillaDetail from './pages/BrewZillaDetail'
import Brewzillas from './pages/Brewzillas'
import Dashboard from './pages/Dashboard'
import HydrometerDetail from './pages/HydrometerDetail'
import Hydrometers from './pages/Hydrometers'
import HydrometerSessionPage from './pages/HydrometerSessionPage'
import SystemSyncs from './pages/SystemSyncs'
import YeastDetail from './pages/YeastDetail'
import Yeasts from './pages/Yeasts'

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <img src="/favicon.png" className="brand-icon" alt="" /> RAPT Portal
        </div>

        <nav>
          <NavLink to="/" end>
            <i className="fa-solid fa-gauge-high" /> Дашборд
          </NavLink>
          <NavLink to="/hydrometers">
            <i className="fa-solid fa-flask" /> Гидрометры
          </NavLink>
          <NavLink to="/brewzillas">
            <i className="fa-solid fa-fire-burner" /> Пивоварни
          </NavLink>
          <NavLink to="/yeasts">
            <i className="fa-solid fa-vial" /> Дрожжи
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <nav className="sidebar-secondary-nav">
            <NavLink to="/system-syncs">
              <i className="fa-solid fa-gear" /> Системные синки
            </NavLink>
          </nav>
          <ThemeToggle />
        </div>
      </aside>
      <main>
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

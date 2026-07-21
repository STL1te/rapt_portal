import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Hydrometers from './pages/Hydrometers'
import HydrometerDetail from './pages/HydrometerDetail'
import HydrometerSessionPage from './pages/HydrometerSessionPage'
import Brewzillas from './pages/Brewzillas'
import BrewZillaDetail from './pages/BrewZillaDetail'
import BrewSessionPage from './pages/BrewSessionPage'
import Yeasts from './pages/Yeasts'
import YeastDetail from './pages/YeastDetail'
import ThemeToggle from './components/ThemeToggle'

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
        <ThemeToggle />
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
        </Routes>
      </main>
    </div>
  )
}

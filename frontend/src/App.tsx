import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Hydrometers from './pages/Hydrometers'
import HydrometerDetail from './pages/HydrometerDetail'
import SessionPage from './pages/SessionPage'
import ThemeToggle from './components/ThemeToggle'

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand"><img src="/favicon.png" className="brand-icon" alt="" /> RAPT Portal</div>
        <nav>
          <NavLink to="/" end><i className="fa-solid fa-gauge-high" /> Дашборд</NavLink>
          <NavLink to="/hydrometers"><i className="fa-solid fa-flask" /> Гидрометры</NavLink>
        </nav>
        <ThemeToggle />
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/hydrometers" element={<Hydrometers />} />
          <Route path="/hydrometers/:id" element={<HydrometerDetail />} />
          <Route path="/sessions/:id" element={<SessionPage />} />
        </Routes>
      </main>
    </div>
  )
}

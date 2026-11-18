import HealthStatus from './components/HealthStatus'
import { SyntheticBanner } from './components/Common'
import About from './pages/About'
import HistoryPage from './pages/HistoryPage'
import IncidentPage from './pages/IncidentPage'
import IncidentsPage from './pages/IncidentsPage'
import RunPage from './pages/RunPage'
import { links, useRoute } from './router'

export default function App() {
  const route = useRoute()
  const current = route.page === 'incident' ? 'incidents' : route.page === 'run' ? 'history' : route.page
  const navItem = (page: string, href: string, label: string) => (
    <a href={href} aria-current={current === page ? 'page' : undefined}>
      {label}
    </a>
  )
  return (
    <>
      <SyntheticBanner />
      <header className="topbar">
        <h1>FabricOps</h1>
        <nav aria-label="Main">
          {navItem('incidents', links.incidents(), 'Incidents')}
          {navItem('history', links.history(), 'Run history')}
          {navItem('about', links.about(), 'About')}
        </nav>
        <div className="health">
          <HealthStatus />
        </div>
      </header>
      <main>
        {route.page === 'incidents' ? <IncidentsPage /> : null}
        {route.page === 'incident' ? <IncidentPage key={route.id} incidentId={route.id} /> : null}
        {route.page === 'run' ? <RunPage key={route.id} runId={route.id} /> : null}
        {route.page === 'history' ? <HistoryPage /> : null}
        {route.page === 'about' ? <About /> : null}
        {route.page === 'notfound' ? (
          <p className="state state-error" role="alert">
            There is no page at <code>{route.path}</code>. <a href={links.incidents()}>Go to incidents</a>
          </p>
        ) : null}
      </main>
    </>
  )
}

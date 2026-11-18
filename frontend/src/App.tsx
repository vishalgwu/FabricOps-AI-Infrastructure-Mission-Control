import { useState } from 'react'
import Home from './pages/Home'
import About from './pages/About'

type Page = 'home' | 'about'

export default function App() {
  const [page, setPage] = useState<Page>('home')
  return (
    <main style={{ maxWidth: 720, margin: '2rem auto', padding: '0 1rem', fontFamily: 'system-ui, sans-serif' }}>
      <h1>FabricOps</h1>
      <nav style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <button onClick={() => setPage('home')} aria-current={page === 'home'}>Home</button>
        <button onClick={() => setPage('about')} aria-current={page === 'about'}>About</button>
      </nav>
      {page === 'home' ? <Home /> : <About />}
    </main>
  )
}

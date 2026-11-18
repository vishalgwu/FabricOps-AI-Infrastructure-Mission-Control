import HealthStatus from '../components/HealthStatus'

export default function Home() {
  return (
    <section>
      <h2>Status</h2>
      <HealthStatus />
      <p>All data in FabricOps is synthetic. The investigation screens arrive in Phase 09; until then use the API (see the README).</p>
    </section>
  )
}

import HealthStatus from '../components/HealthStatus'

export default function Home() {
  return (
    <section>
      <h2>Status</h2>
      <HealthStatus />
      <p>All data in FabricOps is synthetic. Investigations are not implemented yet.</p>
    </section>
  )
}

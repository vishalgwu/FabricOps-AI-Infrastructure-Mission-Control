export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface HealthResponse {
  status: string
  service: string
  environment: string
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { signal })
  if (!res.ok) throw new Error(`Backend returned HTTP ${res.status}`)
  return (await res.json()) as HealthResponse
}

import { useCallback, useEffect, useState } from 'react'
import './Dashboard.css'

type SalesSummary = {
  revenue: number
  transaction_count: number
}

export type InventoryRow = {
  id: number
  name: string
  price: number
  stock_qty: number
  low_stock_threshold: number
  category: string
}

type DashboardPayload = {
  sales: SalesSummary
  inventory: InventoryRow[]
}

function apiUrl(path: string): string {
  const raw = import.meta.env.VITE_BACKEND_URL ?? ''
  const normalized = raw.startsWith('http') ? raw : `http://${raw}`
  try {
    const u = new URL(normalized)
    return `${u.origin}${path}`
  } catch {
    return `http://localhost:8000${path}`
  }
}

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

function stockStatus(row: InventoryRow): 'OK' | 'Low' | 'Out' {
  if (row.stock_qty === 0) return 'Out'
  if (row.stock_qty <= row.low_stock_threshold) return 'Low'
  return 'OK'
}

export function Dashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/dashboard'))
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as DashboardPayload
      setData(json)
      setError(null)
    } catch {
      setError('Could not load dashboard — check backend and CORS.')
    }
  }, [])

  useEffect(() => {
    void fetchDashboard()
    const id = window.setInterval(() => void fetchDashboard(), 5000)
    return () => window.clearInterval(id)
  }, [fetchDashboard])

  const revenue =
    data?.sales?.revenue !== undefined ? inr.format(data.sales.revenue) : '—'
  const txCount = data?.sales?.transaction_count ?? '—'

  return (
    <section className="dashboard" aria-labelledby="dashboard-heading">
      <h2 id="dashboard-heading">Today&apos;s store</h2>

      {error ? <p className="dashboard-error">{error}</p> : null}

      <dl className="dashboard-metrics">
        <div className="dashboard-metric">
          <dt>Today&apos;s total</dt>
          <dd>{revenue}</dd>
        </div>
        <div className="dashboard-metric">
          <dt>Transactions</dt>
          <dd>{txCount}</dd>
        </div>
      </dl>

      <div className="dashboard-table-wrap">
        <table className="dashboard-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">Stock</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {(data?.inventory ?? []).map((row) => {
              const st = stockStatus(row)
              const chipClass =
                st === 'OK'
                  ? 'stock-chip stock-chip--ok'
                  : st === 'Low'
                    ? 'stock-chip stock-chip--low'
                    : 'stock-chip stock-chip--out'
              return (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td>{row.stock_qty}</td>
                  <td>
                    <span className={chipClass}>{st}</span>
                  </td>
                </tr>
              )
            })}
            {data?.inventory?.length === 0 ? (
              <tr>
                <td colSpan={3}>No inventory rows.</td>
              </tr>
            ) : null}
            {!data && !error ? (
              <tr>
                <td colSpan={3}>Loading…</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  )
}

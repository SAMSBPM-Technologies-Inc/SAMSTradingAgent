import { useEffect, useState } from 'react'
import { Shield, RefreshCw } from 'lucide-react'
import { adminApi } from '../lib/api'
import type { AdminUser } from '../types'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'

const TIER_LABELS: Record<number, string> = { 1: 'Starter', 2: 'Pro', 3: 'Elite' }
const TIER_COLORS: Record<number, string> = {
  1: 'bg-gray-500/10 text-gray-500',
  2: 'bg-blue-500/10 text-blue-500',
  3: 'bg-brand-500/10 text-brand-500',
}

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [updating, setUpdating] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await adminApi.listUsers()
      setUsers(res.data)
    } catch {
      setError('Failed to load users.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const setTier = async (userId: string, tier: number) => {
    setUpdating(userId + ':tier')
    try {
      await adminApi.setTier(userId, tier)
      setUsers((prev) => prev.map((u) => u.id === userId
        ? { ...u, tier: tier as 1 | 2 | 3, tier_label: TIER_LABELS[tier] }
        : u
      ))
    } catch {
      setError('Failed to update tier.')
    } finally {
      setUpdating(null)
    }
  }

  const setRole = async (userId: string, role: string) => {
    setUpdating(userId + ':role')
    try {
      await adminApi.setRole(userId, role)
      setUsers((prev) => prev.map((u) => u.id === userId
        ? { ...u, role: role as 'user' | 'admin' }
        : u
      ))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to update role.')
    } finally {
      setUpdating(null)
    }
  }

  return (
    <Layout>
      <div className="mb-6 flex items-center justify-between">
        <h1
          className="text-2xl font-light text-[var(--color-fg)] flex items-center gap-2"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          <Shield className="w-6 h-6 text-brand-500" />
          Admin Portal
        </h1>
        <button onClick={load} disabled={isLoading} className="btn-secondary gap-2">
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-500/10 text-red-500 text-sm">{error}</div>
      )}

      {/* Tier legend */}
      <div className="flex gap-3 mb-5 flex-wrap">
        {[1, 2, 3].map((t) => (
          <div key={t} className={`px-3 py-1 rounded-full text-xs font-semibold ${TIER_COLORS[t]}`}>
            Tier {t} — {TIER_LABELS[t]}
          </div>
        ))}
        <div className="px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-500">
          Admin — full access
        </div>
      </div>

      <div className="text-xs text-[var(--color-fg-muted)] mb-2">{users.length} user{users.length !== 1 ? 's' : ''}</div>

      {isLoading ? (
        <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-[var(--color-fg-muted)] text-xs uppercase tracking-wide">
                  <th className="text-left px-4 py-3 font-medium">User</th>
                  <th className="text-left px-4 py-3 font-medium">Joined</th>
                  <th className="text-left px-4 py-3 font-medium">Tier</th>
                  <th className="text-left px-4 py-3 font-medium">Role</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-border)]/20 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium text-[var(--color-fg)]">{u.display_name}</div>
                      <div className="text-xs text-[var(--color-fg-muted)]">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-[var(--color-fg-muted)] text-xs">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${TIER_COLORS[u.tier]}`}>
                          {u.tier_label}
                        </span>
                        {updating === u.id + ':tier' ? (
                          <LoadingSpinner size="sm" />
                        ) : (
                          <select
                            value={u.tier}
                            onChange={(e) => setTier(u.id, parseInt(e.target.value))}
                            className="input py-0.5 px-2 text-xs w-24"
                          >
                            <option value={1}>Tier 1</option>
                            <option value={2}>Tier 2</option>
                            <option value={3}>Tier 3</option>
                          </select>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                          u.role === 'admin'
                            ? 'bg-amber-500/10 text-amber-500'
                            : 'bg-[var(--color-border)] text-[var(--color-fg-muted)]'
                        }`}>
                          {u.role}
                        </span>
                        {updating === u.id + ':role' ? (
                          <LoadingSpinner size="sm" />
                        ) : (
                          <select
                            value={u.role}
                            onChange={(e) => setRole(u.id, e.target.value)}
                            className="input py-0.5 px-2 text-xs w-24"
                          >
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                          </select>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Layout>
  )
}

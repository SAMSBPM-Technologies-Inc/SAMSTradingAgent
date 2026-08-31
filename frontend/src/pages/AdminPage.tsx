import { useCallback, useEffect, useState } from 'react'
import Layout from '../components/Layout'
import LoadingSpinner from '../components/LoadingSpinner'
import { adminApi } from '../lib/api'
import { TIER_LABELS, tierRefusal, type AccessTier } from '../lib/entitlements'
import { useToast } from '../lib/toast-context'
import type { AccessRequest, AdminUser } from '../types'

/**
 * Provisioning, without SSH.
 *
 * Accounts used to be created by running `scripts/create_user.py` on the VPS,
 * which meant every new user and every plan change needed a shell. This is the
 * same operations in a browser, for the one address named by `ADMIN_EMAIL` on
 * the server.
 *
 * Two things it deliberately does not offer. There is **no delete**: a user
 * document is referenced by watched tickers, trades and dossiers, none of which
 * cascade, and half a cascade is worse than none. And there is **no password
 * read-back** — a generated password appears once, in the response to the call
 * that generated it, and is never stored in a form a route could return.
 */

const TIERS: AccessTier[] = ['BASIC', 'PRO', 'TRADER']

function Card({
  title,
  blurb,
  children,
}: {
  title: string
  blurb?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <header className="border-b border-[var(--color-border)] px-4 py-3">
        <h2 className="text-[13.5px] font-semibold text-[var(--color-fg)]">{title}</h2>
        {blurb && (
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--color-fg-muted)]">
            {blurb}
          </p>
        )}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}

const inputClass =
  `h-8 rounded-[6px] border border-[var(--color-border)] bg-[var(--color-bg)] px-2
   text-[12.5px] text-[var(--color-fg)]`

/** One account's editable row. Local state so a mid-edit value is not lost. */
function UserRow({ user, onChanged }: { user: AdminUser; onChanged: () => void }) {
  const { toast } = useToast()
  const [saving, setSaving] = useState(false)

  const patch = useCallback(
    async (
      body: Parameters<typeof adminApi.updateUser>[1],
      force = false,
    ) => {
      setSaving(true)
      try {
        await adminApi.updateUser(user.id, body, force)
        onChanged()
      } catch (err) {
        const detail = (err as { response?: { status?: number; data?: { detail?: unknown } } })
          ?.response
        // A downgrade that removes trading from an account holding open
        // positions takes away the interface that closes them. The server
        // refuses it once and names the tickers; confirming here re-sends with
        // force, which is logged server-side.
        const d = detail?.data?.detail as { error?: string; message?: string } | undefined
        if (detail?.status === 409 && d?.error === 'open_positions') {
          if (window.confirm(`${d.message}\n\nProceed anyway?`)) {
            await patch(body, true)
            return
          }
        } else {
          toast(tierRefusal(err)?.message ?? 'Could not save that change.', 'error')
        }
      } finally {
        setSaving(false)
      }
    },
    [onChanged, toast, user.id],
  )

  return (
    <tr className="border-t border-[var(--color-border)]">
      <td className="px-2 py-2">
        <span className="text-[12.5px] text-[var(--color-fg)]">{user.display_name || '—'}</span>
        <br />
        <span className="text-[11px] text-[var(--color-fg-muted)]">{user.email}</span>
        {user.is_admin && (
          <span className="ml-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--color-fg-muted)]">
            operator
          </span>
        )}
      </td>

      <td className="px-2 py-2">
        <label className="sr-only" htmlFor={`tier-${user.id}`}>
          Plan for {user.email}
        </label>
        <select
          id={`tier-${user.id}`}
          className={inputClass}
          value={user.access_tier}
          disabled={saving || user.is_admin}
          onChange={(e) => patch({ access_tier: e.target.value as AccessTier })}
        >
          {TIERS.map((t) => (
            <option key={t} value={t}>{TIER_LABELS[t]}</option>
          ))}
        </select>
        {user.is_admin && (
          <p className="mt-1 text-[10.5px] text-[var(--color-fg-muted)]">
            Set by ADMIN_EMAIL, not here.
          </p>
        )}
      </td>

      <td className="px-2 py-2">
        <label className="sr-only" htmlFor={`cap-${user.id}`}>
          Ticker cap for {user.email}
        </label>
        <input
          id={`cap-${user.id}`}
          type="number"
          min={0}
          className={`${inputClass} w-20`}
          placeholder={user.watchlist_cap === null ? '∞' : String(user.watchlist_cap ?? '')}
          defaultValue={user.watchlist_cap_override ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim()
            if (raw === '' && user.watchlist_cap_override == null) return
            if (raw === '') {
              patch({ clear_watchlist_cap: true })
              return
            }
            const n = Number(raw)
            if (Number.isFinite(n) && n !== user.watchlist_cap_override) {
              patch({ watchlist_cap: Math.max(0, Math.round(n)) })
            }
          }}
        />
        <p className="mt-1 text-[10.5px] text-[var(--color-fg-muted)]">
          {user.watching} watched · blank uses the plan default
        </p>
      </td>

      <td className="px-2 py-2 text-center">
        <label className="sr-only" htmlFor={`nightly-${user.id}`}>
          Allow nightly research for {user.email}
        </label>
        <input
          id={`nightly-${user.id}`}
          type="checkbox"
          checked={user.research_daily_allowed}
          disabled={saving}
          onChange={(e) => patch({ research_daily_allowed: e.target.checked })}
        />
        {user.research_enabled && (
          <p className="mt-1 text-[10.5px] text-[var(--color-fg-muted)]">enrolled</p>
        )}
      </td>

      <td className="px-2 py-2 text-right text-[11.5px] text-[var(--color-fg-muted)]">
        {user.llm_key_count || '—'}
      </td>
    </tr>
  )
}

function CreateUser({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [tier, setTier] = useState<AccessTier>('BASIC')
  const [busy, setBusy] = useState(false)
  // Shown once and never again — the server does not keep it in a readable form.
  const [issued, setIssued] = useState<{ email: string; password: string } | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const { data } = await adminApi.createUser({
        email: email.trim(),
        display_name: name.trim(),
        access_tier: tier,
      })
      if (data.password) setIssued({ email: data.user.email, password: data.password })
      setEmail('')
      setName('')
      onCreated()
    } catch (err) {
      toast(tierRefusal(err)?.message ?? 'Could not create that account.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-email" className="text-[11px] text-[var(--color-fg-muted)]">
            Email
          </label>
          <input
            id="new-email"
            type="email"
            required
            className={`${inputClass} w-56`}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-name" className="text-[11px] text-[var(--color-fg-muted)]">
            Name
          </label>
          <input
            id="new-name"
            className={`${inputClass} w-40`}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-tier" className="text-[11px] text-[var(--color-fg-muted)]">
            Plan
          </label>
          <select
            id="new-tier"
            className={inputClass}
            value={tier}
            onChange={(e) => setTier(e.target.value as AccessTier)}
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>{TIER_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={busy || !email.trim()}
          className="h-8 rounded-[6px] bg-[var(--color-fg)] px-3 text-[12.5px] font-semibold
                     text-[var(--color-bg)] disabled:opacity-50"
        >
          {busy ? 'Creating…' : 'Create account'}
        </button>
      </form>

      {issued && (
        <div
          role="status"
          className="mt-3 rounded-[6px] border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2"
        >
          <p className="text-[12px] text-[var(--color-fg)]">
            Password for <strong>{issued.email}</strong>:{' '}
            <code className="num select-all">{issued.password}</code>
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-fg-muted)]">
            Shown once. Nothing can read it back — email it now, or set a new one
            by recreating the account.
          </p>
        </div>
      )}
    </>
  )
}

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [requests, setRequests] = useState<AccessRequest[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [u, r] = await Promise.all([adminApi.users(), adminApi.accessRequests()])
      setUsers(u.data)
      setRequests(r.data)
      setError(null)
    } catch (err) {
      setError(tierRefusal(err)?.message ?? 'Could not load accounts.')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <Layout>
      <div className="mx-auto flex max-w-4xl flex-col gap-4 px-4 py-6">
        <header>
          <h1
            className="text-[19px] font-semibold text-[var(--color-fg)]"
            style={{ fontFamily: 'Archivo, system-ui, sans-serif' }}
          >
            Accounts
          </h1>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--color-fg-muted)]">
            There is no self-serve signup. People ask through the contact form and
            you provision them here. A plan change takes effect on that account's
            next request — no sign-out needed.
          </p>
        </header>

        {error && (
          <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]
                        px-4 py-6 text-center text-sm text-[var(--color-fg-muted)]">
            {error}
          </p>
        )}

        <Card
          title="Create an account"
          blurb="The password is generated and shown once. Email it to them yourself."
        >
          <CreateUser onCreated={load} />
        </Card>

        <Card
          title="Everyone"
          blurb="Basic reads stored analysis. Pro also runs research and full analyses, on its own provider key. Trader adds the broker."
        >
          {users === null && !error ? (
            <LoadingSpinner />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-[10.5px] uppercase tracking-[0.08em] text-[var(--color-fg-muted)]">
                    <th scope="col" className="px-2 pb-2 font-medium">Account</th>
                    <th scope="col" className="px-2 pb-2 font-medium">Plan</th>
                    <th scope="col" className="px-2 pb-2 font-medium">Tickers</th>
                    <th scope="col" className="px-2 pb-2 text-center font-medium">Nightly research</th>
                    <th scope="col" className="px-2 pb-2 text-right font-medium">Keys</th>
                  </tr>
                </thead>
                <tbody>
                  {(users ?? []).map((u) => (
                    <UserRow key={u.id} user={u} onChanged={load} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          title="Who has asked"
          blurb="Contact-form submissions, newest first. Read-only — provisioning an account is the action, and it shows up in the table above. Entries age out after 180 days."
        >
          {requests.length === 0 ? (
            <p className="text-[12px] text-[var(--color-fg-muted)]">Nothing waiting.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {requests.map((r) => (
                <li key={r.id} className="border-t border-[var(--color-border)] pt-3 first:border-0 first:pt-0">
                  <p className="text-[12.5px] text-[var(--color-fg)]">
                    {r.name} · <span className="text-[var(--color-fg-muted)]">{r.email}</span>
                  </p>
                  {r.interest && (
                    <p className="text-[11.5px] text-[var(--color-fg-muted)]">{r.interest}</p>
                  )}
                  <p className="mt-1 whitespace-pre-wrap text-[12px] text-[var(--color-fg-muted)]">
                    {r.message}
                  </p>
                  {r.created_at && (
                    <p className="mt-1 text-[10.5px] text-[var(--color-fg-muted)]">
                      {new Date(r.created_at).toLocaleString()}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </Layout>
  )
}

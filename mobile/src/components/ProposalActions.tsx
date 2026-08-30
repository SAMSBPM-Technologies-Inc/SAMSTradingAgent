import React, { useState } from 'react'
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native'
import { Check, X } from 'lucide-react-native'
import { tradingApi } from '../lib/api'
import { useToast } from '../lib/toast-context'
import { usePalette } from '../lib/palette'

/**
 * Accepting or refusing an entry the agent wanted but was not permitted to take
 * alone — in one place, because there are now three of them.
 *
 * The activity list, the transaction screen and the ticker screen all resolve
 * the same proposal, and the live-money gate is the thing that must not be
 * reimplemented twice: approving a proposal *is* placing an order, and the fact
 * that the agent chose the name rather than the human does not make it a
 * smaller commitment. So it asks for the ticker to be typed back, exactly as
 * the order ticket does, wherever it is shown.
 *
 * Mirrors `frontend/src/components/trade/ProposalActions.tsx`. The two clients
 * must not disagree about what confirmation a live order needs.
 */

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export default function ProposalActions({
  id, ticker, isPaper, onResolved,
}: {
  id: string
  ticker: string
  isPaper: boolean
  onResolved: () => void
}) {
  const C = usePalette()
  const { toast } = useToast()
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null)
  const [confirmLive, setConfirmLive] = useState('')

  const needsConfirm = !isPaper
  const liveConfirmed =
    !needsConfirm || confirmLive.trim().toUpperCase() === ticker.toUpperCase()

  const approve = async () => {
    if (busy || !liveConfirmed) return
    setBusy('approve')
    try {
      const { data } = await tradingApi.approveProposal(id, needsConfirm)
      toast(
        data.placed
          ? `Order placed: ${data.qty} ${data.ticker} at ${usd.format(data.limit_price)}`
            + (data.trade_id ? ` — Ref ${data.trade_id.slice(-8).toUpperCase()}` : '')
          : data.reason ?? 'The order could not be placed.',
        data.placed ? 'success' : 'error',
      )
      onResolved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      toast(detail ?? 'Could not approve this proposal.', 'error')
      onResolved()
    } finally {
      setBusy(null)
    }
  }

  const decline = async () => {
    if (busy) return
    setBusy('decline')
    try {
      await tradingApi.declineProposal(id)
      toast(`Rejected ${ticker}.`, 'info')
      onResolved()
    } catch {
      toast('Could not reject this proposal.', 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <View style={{ gap: 10 }}>
      {needsConfirm && (
        <View style={{ gap: 4 }}>
          <Text style={{ fontSize: 11, color: C.red }}>
            Live money — type {ticker} to approve
          </Text>
          <TextInput
            value={confirmLive}
            onChangeText={setConfirmLive}
            autoCapitalize="characters"
            autoCorrect={false}
            accessibilityLabel="Type the ticker to confirm a live approval"
            style={{
              borderWidth: 1, borderColor: C.red, borderRadius: 8,
              paddingHorizontal: 12, paddingVertical: 9, fontSize: 14,
              color: C.fg, backgroundColor: C.bg,
            }}
          />
        </View>
      )}

      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Pressable
          onPress={approve}
          disabled={busy !== null || !liveConfirmed}
          accessibilityRole="button"
          style={{
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 6, backgroundColor: C.brand, borderRadius: 9, paddingVertical: 11,
            opacity: busy !== null || !liveConfirmed ? 0.4 : 1,
          }}
        >
          {busy === 'approve'
            ? <ActivityIndicator size="small" color="#fff" />
            : <Check size={15} color="#fff" />}
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>Approve</Text>
        </Pressable>
        <Pressable
          onPress={decline}
          disabled={busy !== null}
          accessibilityRole="button"
          style={{
            flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 6, backgroundColor: C.surface, borderRadius: 9, paddingVertical: 11,
            borderWidth: 1, borderColor: C.border, opacity: busy !== null ? 0.4 : 1,
          }}
        >
          {busy === 'decline'
            ? <ActivityIndicator size="small" color={C.fgMuted} />
            : <X size={15} color={C.fgMuted} />}
          <Text style={{ color: C.fgMuted, fontWeight: '600', fontSize: 13 }}>Reject</Text>
        </Pressable>
      </View>
    </View>
  )
}

import React, { useState } from 'react'
import { View, Text, Pressable, ScrollView } from 'react-native'
import { ChevronDown, ChevronUp } from 'lucide-react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import Disclaimer from '../../src/components/Disclaimer'
import { usePalette, type Palette } from '../../src/lib/palette'


const cardStyle = (C: Palette) => ({
  backgroundColor: C.surface, borderRadius: 12,
  borderWidth: 1, borderColor: C.border, padding: 16, marginBottom: 12,
})

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const C = usePalette()
  const card = cardStyle(C)
  const [open, setOpen] = useState(true)
  return (
    <View style={{ marginBottom: 12 }}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={{
          flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
          backgroundColor: C.surface, borderRadius: 12,
          borderWidth: 1, borderColor: C.border, padding: 14,
        }}
      >
        <Text style={{ fontSize: 14, fontWeight: '600', color: C.fg, flex: 1 }}>{title}</Text>
        {open ? <ChevronUp size={16} color={C.fgMuted} /> : <ChevronDown size={16} color={C.fgMuted} />}
      </Pressable>
      {open && (
        <View style={{
          backgroundColor: C.surface, borderRadius: 12,
          borderWidth: 1, borderColor: C.border, borderTopWidth: 0,
          borderTopLeftRadius: 0, borderTopRightRadius: 0,
          padding: 14, gap: 8,
        }}>
          {children}
        </View>
      )}
    </View>
  )
}

function P({ children }: { children: React.ReactNode }) {
  const C = usePalette()
  const card = cardStyle(C)
  return <Text style={{ fontSize: 13, color: C.fg, lineHeight: 20 }}>{children}</Text>
}

function Bullet({ children }: { children: React.ReactNode }) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
      <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: C.brand, marginTop: 7, flexShrink: 0 }} />
      <Text style={{ fontSize: 13, color: C.fg, flex: 1, lineHeight: 19 }}>{children}</Text>
    </View>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  const C = usePalette()
  const card = cardStyle(C)
  return (
    <Text style={{
      fontSize: 9, fontWeight: '700', color: C.fgMuted,
      textTransform: 'uppercase', letterSpacing: 0.8, marginTop: 4, marginBottom: 4,
    }}>
      {children}
    </Text>
  )
}

export default function GuideScreen() {
  const C = usePalette()
  const card = cardStyle(C)
  const [tab, setTab] = useState<'buyer' | 'seller' | 'ibgw'>('buyer')

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 20, paddingBottom: 100 }}
        showsVerticalScrollIndicator={false}
      >
        <Text style={{ fontSize: 22, fontWeight: '700', color: C.fg, marginBottom: 4 }}>Trading Guide</Text>
        <Text style={{ fontSize: 13, color: C.fgMuted, marginBottom: 20 }}>
          How to read and act on SAMSBPM signals
        </Text>

        {/* Tab switcher */}
        <View style={{
          flexDirection: 'row', backgroundColor: C.surface,
          borderRadius: 12, borderWidth: 1, borderColor: C.border,
          padding: 4, marginBottom: 20, gap: 4,
        }}>
          {([
            { key: 'buyer', label: "Buyer's Guide" },
            { key: 'seller', label: "Seller's Guide" },
            { key: 'ibgw', label: 'IB Gateway' },
          ] as const).map(({ key, label }) => (
            <Pressable
              key={key}
              onPress={() => setTab(key)}
              style={{
                flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center',
                backgroundColor: tab === key ? C.bg : 'transparent',
              }}
            >
              <Text style={{ fontSize: 11, fontWeight: '600', color: tab === key ? C.fg : C.fgMuted }}>
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* ── Buyer's Guide ── */}
        {tab === 'buyer' && (
          <>
            <Section title="Understanding Signals">
              <Label>BUY</Label>
              <P>Score ≥ 70, risk acceptable. AI has high conviction on upside catalysts and strong technical setup.</P>
              <Label>HOLD</Label>
              <P>Score 40–69. Mixed signals — not a clear entry, but no reason to exit existing positions.</P>
              <Label>SELL</Label>
              <P>Score {'<'} 40. Bearish bias, deteriorating fundamentals or sentiment. Avoid new positions.</P>
            </Section>

            <Section title="Score Breakdown">
              <Bullet>70–100 Strong — enter on confirmation</Bullet>
              <Bullet>40–69 Mixed — wait for clearer signal</Bullet>
              <Bullet>0–39 Weak — avoid, consider exit</Bullet>
              <P style={{ marginTop: 4 }}>
                Score = 40% technical + 30% sentiment + 30% volatility/macro composite.
              </P>
            </Section>

            <Section title="When to Enter">
              <Bullet>Signal is BUY with score ≥ 70</Bullet>
              <Bullet>Conviction is HIGH or MEDIUM</Bullet>
              <Bullet>Price is near or below Price Target entry zone</Bullet>
              <Bullet>At least 2 catalysts confirmed</Bullet>
              <Bullet>Bull case outweighs bear case for your risk tolerance</Bullet>
              <Bullet>Stop loss is defined and acceptable</Bullet>
            </Section>

            <Section title="Pre-Buy Checklist">
              <Bullet>Score ≥ 70 on latest analysis?</Bullet>
              <Bullet>Conviction HIGH or MEDIUM?</Bullet>
              <Bullet>Know your stop loss?</Bullet>
              <Bullet>Position size ≤ your risk rule?</Bullet>
              <Bullet>No near-term earnings that could gap down?</Bullet>
              <Bullet>Macro environment not in crisis mode?</Bullet>
            </Section>
          </>
        )}

        {/* ── Seller's Guide ── */}
        {tab === 'seller' && (
          <>
            <Section title="When to Trim / Exit">
              <Bullet>Signal flips from BUY → HOLD or HOLD → SELL</Bullet>
              <Bullet>Score drops below 40</Bullet>
              <Bullet>Price hits your price target (take 50–100% profit)</Bullet>
              <Bullet>Price hits stop loss (cut immediately)</Bullet>
              <Bullet>Bear case materialises (earnings miss, news catalyst reversal)</Bullet>
            </Section>

            <Section title="Taking Profit">
              <P>When signal remains BUY but price has run 20–30% above entry:</P>
              <Bullet>Trim 25–50% of position to lock gains</Bullet>
              <Bullet>Move stop loss to break-even on remainder</Bullet>
              <Bullet>Let the rest run if conviction stays HIGH</Bullet>
            </Section>

            <Section title="Cutting Losses">
              <P>Respect the stop loss. Do not average down on a SELL signal.</P>
              <Bullet>Exit fully when score drops below 35</Bullet>
              <Bullet>Exit fully when stop loss price is breached</Bullet>
              <Bullet>A SELL signal with LOW conviction = watch closely</Bullet>
              <Bullet>A SELL signal with HIGH conviction = exit immediately</Bullet>
            </Section>

            <Section title="Should I Sell Checklist">
              <Bullet>Signal just flipped to SELL?</Bullet>
              <Bullet>Score below 40 for 2+ consecutive days?</Bullet>
              <Bullet>Bear case narrative strengthening?</Bullet>
              <Bullet>Catalyst failed to materialise?</Bullet>
              <Bullet>Stop loss breached intraday?</Bullet>
            </Section>
          </>
        )}

        {/* ── IB Gateway ── */}
        {tab === 'ibgw' && (
          <>
            <View style={{
              padding: 12, borderRadius: 10, marginBottom: 16,
              backgroundColor: `${C.amber}1a`, borderWidth: 1, borderColor: `${C.amber}33`,
            }}>
              <Text style={{ fontSize: 12, color: C.amber, lineHeight: 18 }}>
                IB Gateway must run on a machine that your backend server can reach over TCP. It cannot run on a mobile device.
              </Text>
            </View>

            <Section title="What is IB Gateway?">
              <P>IB Gateway is a headless API bridge between your backend and your Interactive Brokers account. It listens on port 4001 (live) or 4002 (paper) and accepts TWS API connections from the SAMSTradingAgent backend.</P>
            </Section>

            <Section title="Installation">
              <Label>Step 1 — Download</Label>
              <P>Go to interactivebrokers.com → Technology → Traders' Workstation → IB Gateway. Download the offline installer for your OS.</P>
              <Label>Step 2 — Install and launch</Label>
              <P>Run the installer. Launch IB Gateway and log in with your IBKR credentials.</P>
              <Label>Step 3 — Enable API</Label>
              <P>In IB Gateway: Configure → Settings → API → Enable ActiveX and Socket Clients. Set Socket port to 4001 (live) or 4002 (paper). Enable "Allow connections from localhost only" if on the same machine, or add your server's IP.</P>
              <Label>Step 4 — Backend env vars</Label>
              <P>Set these in your backend .env:</P>
              <View style={{
                backgroundColor: C.bg, borderRadius: 8, padding: 10,
                borderWidth: 1, borderColor: C.border, marginTop: 4,
              }}>
                <Text style={{ fontSize: 11, fontFamily: 'monospace', color: C.fg, lineHeight: 17 }}>
                  {'IB_HOST=<your-gateway-ip>\nIB_PORT=4002\nIB_CLIENT_ID=1\nAUTO_TRADE_LIVE_ALLOWED=false'}
                </Text>
              </View>
            </Section>

            <Section title="Port Reference">
              <Bullet>4001 — Live trading account</Bullet>
              <Bullet>4002 — Paper trading account (default, safer)</Bullet>
              <Bullet>7496 / 7497 — TWS (desktop app, avoid for server use)</Bullet>
            </Section>

            <Section title="Session Timeout">
              <P>IB Gateway logs out automatically after 24h by default. To disable: Configure → Settings → Lock and Exit → Auto-logoff timer → set to 00:00 (midnight).</P>
              <P>For production use, run IB Gateway as a background service with auto-restart and schedule a daily re-login at a low-activity time.</P>
            </Section>
          </>
        )}
        <Disclaimer />
      </ScrollView>
    </SafeAreaView>
  )
}

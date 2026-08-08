import { useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import Layout from '../components/Layout'

// ── Collapsible section ───────────────────────────────────────────────────────

function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
}: {
  title: string
  icon: React.FC<{ className?: string }>
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center justify-between w-full px-5 py-4 text-left"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center flex-shrink-0">
            <Icon className="w-4 h-4 text-brand-500" />
          </div>
          <span
            className="font-medium text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            {title}
          </span>
        </div>
        {open
          ? <ChevronUp className="w-4 h-4 text-[var(--color-fg-muted)]" />
          : <ChevronDown className="w-4 h-4 text-[var(--color-fg-muted)]" />}
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-[var(--color-border)]">
          <div className="pt-4 flex flex-col gap-3 text-sm text-[var(--color-fg)] leading-relaxed">
            {children}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Pill label ────────────────────────────────────────────────────────────────

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${color}`}>
      {label}
    </span>
  )
}

// ── Guide row ─────────────────────────────────────────────────────────────────

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-4 py-2
                    border-b border-[var(--color-border)] last:border-0">
      <div className="sm:w-36 flex-shrink-0">{label}</div>
      <div className="text-[var(--color-fg-muted)] flex-1">{children}</div>
    </div>
  )
}

// ── Guide Page ────────────────────────────────────────────────────────────────

export default function GuidePage() {
  return (
    <Layout>
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <BookOpen className="w-6 h-6 text-brand-500" />
          <h1
            className="text-2xl font-light text-[var(--color-fg)]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            Trading Guide
          </h1>
        </div>
        <p className="text-sm text-[var(--color-fg-muted)]">
          What to look at before making a trade decision
        </p>
      </div>

      <div className="flex flex-col gap-3">

        {/* Signals */}
        <Section title="Reading Signals (BUY / HOLD / SELL)" icon={TrendingUp} defaultOpen>
          <Row label={<Pill label="BUY" color="bg-green-500/15 text-green-500" />}>
            The model sees a favourable setup — price momentum, sentiment, and macro are aligned.
            Does not mean buy immediately. Confirm with your own research and risk tolerance.
          </Row>
          <Row label={<Pill label="HOLD" color="bg-yellow-500/15 text-yellow-600" />}>
            Mixed or neutral signals. Not enough conviction to enter or exit. Good time to monitor
            and wait for a clearer setup. If you already hold the stock, hold your position.
          </Row>
          <Row label={<Pill label="SELL" color="bg-red-500/15 text-red-500" />}>
            Deteriorating signals — bearish momentum, negative sentiment, or macro headwinds.
            If you hold the stock, consider reducing or exiting. Does not mean short selling.
          </Row>
          <p className="text-xs text-[var(--color-fg-muted)] bg-[var(--color-bg)] rounded-xl px-4 py-3">
            <strong>Important:</strong> Signals are a starting point, not financial advice.
            Always combine with your own analysis before executing a trade.
          </p>
        </Section>

        {/* Score */}
        <Section title="Understanding the Score (0–100)" icon={Zap}>
          <Row label={<span className="font-semibold text-green-500">70–100</span>}>
            Strong bullish setup. Multiple indicators aligned. Higher probability of upside,
            but not guaranteed.
          </Row>
          <Row label={<span className="font-semibold text-yellow-500">40–69</span>}>
            Neutral / mixed. Some positive signals offset by negatives. Use caution.
            Wait for score to move decisively in one direction.
          </Row>
          <Row label={<span className="font-semibold text-red-500">0–39</span>}>
            Weak or bearish setup. Multiple signals pointing down. Avoid new long positions.
            Review your stop loss if you hold.
          </Row>
          <p className="text-[var(--color-fg-muted)]">
            The score is a weighted composite of 6 factors: Technical (25%), Sentiment (20%),
            Fundamental (15%), Macro (15%), Catalyst (15%), Volatility (10%).
          </p>
        </Section>

        {/* Conviction */}
        <Section title="Signal Strength (Strong / Moderate / Weak)" icon={Zap}>
          <Row label={<Pill label="Strong Signal" color="bg-brand-500/15 text-brand-500" />}>
            High confidence — all evidence strongly supports the signal direction.
            More weight can be given to this signal.
          </Row>
          <Row label={<Pill label="Moderate" color="bg-brand-500/10 text-brand-600" />}>
            Decent confidence but some conflicting indicators. Proceed with normal caution.
          </Row>
          <Row label={<Pill label="Weak Signal" color="bg-brand-500/5 text-brand-700 dark:text-brand-400" />}>
            Low confidence — indicators are mixed or data quality is limited.
            Do more research before acting. Treat as informational only.
          </Row>
        </Section>

        {/* Entry & Exit */}
        <Section title="Entry & Exit Points" icon={TrendingUp}>
          <p>
            <strong>Price Target</strong> — the AI's estimated fair value or upside target based on
            fundamentals and momentum. Not a guarantee; use as a reference for setting take-profit levels.
          </p>
          <p>
            <strong>Stop Loss</strong> — suggested level to exit if the trade goes against you.
            Always set a stop loss before entering a position. Risking more than 1–2% of
            your portfolio on a single trade is generally considered high risk.
          </p>
          <p>
            <strong>Entry suggestion</strong> — conditions under which entering the trade makes sense
            (e.g. "on a pullback to support", "after earnings confirmation").
            Don't chase — wait for the suggested setup.
          </p>
          <p>
            <strong>Time horizon</strong> — whether this is a short-term (days), medium-term (weeks),
            or long-term (months) signal. Match it to your own trading style.
          </p>
        </Section>

        {/* Catalysts & Risks */}
        <Section title="Catalysts & Key Risks" icon={AlertTriangle}>
          <p>
            <strong>Catalysts</strong> are upcoming events that could push the stock up —
            earnings beats, product launches, analyst upgrades, sector tailwinds.
            A strong catalyst + BUY signal is a higher conviction setup.
          </p>
          <p>
            <strong>Key risks</strong> are factors that could invalidate the signal —
            regulatory issues, earnings misses, macro shocks, sector rotation.
            Always read the risks section before entering a trade.
          </p>
          <p className="text-[var(--color-fg-muted)]">
            If the risks outweigh the catalysts even on a BUY signal, consider passing on the trade.
          </p>
        </Section>

        {/* Bull & Bear */}
        <Section title="Bull & Bear Case" icon={TrendingDown}>
          <p>
            Every ticker shows both sides of the argument. Read both before deciding.
          </p>
          <p>
            <strong>Bull case</strong> — why the stock could go up. Use this to confirm your thesis.
          </p>
          <p>
            <strong>Bear case</strong> — why the stock could go down. Use this to stress-test
            your thesis and size your position appropriately.
          </p>
          <p className="text-[var(--color-fg-muted)]">
            If you can't argue against the bear case, your position size should be smaller.
          </p>
        </Section>

        {/* Risk management */}
        <Section title="Risk Management Checklist" icon={ShieldAlert}>
          <div className="flex flex-col gap-2">
            {[
              'Never risk more than 1–2% of your total portfolio on a single trade.',
              'Always set a stop loss before entering — not after.',
              'Weak Signal trades should use smaller position sizes.',
              "Don't trade a SELL signal by shorting unless you understand the risks of short selling.",
              'Check the macro score — a strong BUY in a bad macro environment is riskier.',
              'High confidence score + Strong Signal + clear catalyst = best setup.',
              'Updated data is more reliable. Prefer signals updated within the last trading session.',
              'When in doubt, HOLD. Missing a trade is better than a bad trade.',
            ].map((item, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-brand-500 flex-shrink-0" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </Section>

        {/* Disclaimer */}
        <div className="px-5 py-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)]
                        text-xs text-[var(--color-fg-muted)] leading-relaxed">
          <strong className="text-[var(--color-fg)]">Disclaimer:</strong> SAMSBPM Trading is an
          AI-powered analysis tool for informational purposes only. It is not registered financial
          advice, investment advice, or a brokerage service. Past signal accuracy does not guarantee
          future results. Always consult a licensed financial advisor before making investment decisions.
        </div>

      </div>
    </Layout>
  )
}

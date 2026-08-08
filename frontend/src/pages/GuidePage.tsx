import { useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  DollarSign,
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

// ── Checklist ─────────────────────────────────────────────────────────────────

function Checklist({ items }: { items: string[] }) {
  return (
    <div className="flex flex-col gap-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-3">
          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-brand-500 flex-shrink-0" />
          <span>{item}</span>
        </div>
      ))}
    </div>
  )
}

// ── View toggle ───────────────────────────────────────────────────────────────

type View = 'buyer' | 'seller'

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="flex rounded-xl border border-[var(--color-border)] overflow-hidden bg-[var(--color-surface)] p-1 gap-1">
      <button
        onClick={() => onChange('buyer')}
        className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-200
          ${view === 'buyer'
            ? 'bg-brand-500 text-white shadow-sm'
            : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
          }`}
      >
        <DollarSign className="w-4 h-4" />
        I want to buy
      </button>
      <button
        onClick={() => onChange('seller')}
        className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-200
          ${view === 'seller'
            ? 'bg-brand-500 text-white shadow-sm'
            : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
          }`}
      >
        <TrendingDown className="w-4 h-4" />
        I hold stocks
      </button>
    </div>
  )
}

// ── Buyer Guide ───────────────────────────────────────────────────────────────

function BuyerGuide() {
  return (
    <>
      {/* What to look for */}
      <Section title="What signal to look for" icon={TrendingUp} defaultOpen>
        <Row label={<Pill label="BUY" color="bg-green-500/15 text-green-500" />}>
          The model sees a favourable setup — momentum, sentiment, and macro aligned.
          Not a guarantee. Use as a starting point, not a final answer.
        </Row>
        <Row label={<Pill label="HOLD" color="bg-yellow-500/15 text-yellow-600" />}>
          Mixed signals. No clear edge to enter now. Wait for a BUY before committing capital.
          Buying on a HOLD signal increases your risk.
        </Row>
        <Row label={<Pill label="SELL" color="bg-red-500/15 text-red-500" />}>
          Conditions are deteriorating. Do not enter a new long position on a SELL signal.
          Wait for the signal to flip to BUY or HOLD before looking again.
        </Row>
        <p className="text-xs text-[var(--color-fg-muted)] bg-[var(--color-bg)] rounded-xl px-4 py-3">
          <strong>Best setup to buy:</strong> BUY signal + Score above 70 + Strong Signal conviction + clear upcoming catalyst.
        </p>
      </Section>

      {/* Score */}
      <Section title="Score — how strong is the setup?" icon={Zap}>
        <Row label={<span className="font-semibold text-green-500">70–100</span>}>
          Strong bullish setup. Multiple indicators aligned. This is the range where buying makes most sense.
        </Row>
        <Row label={<span className="font-semibold text-yellow-500">40–69</span>}>
          Mixed. Some positive signals offset by negatives. If you buy here, use a smaller position size.
        </Row>
        <Row label={<span className="font-semibold text-red-500">0–39</span>}>
          Weak or bearish setup. Avoid new long positions. Wait for conditions to improve.
        </Row>
        <p className="text-[var(--color-fg-muted)]">
          Score is a weighted composite of 6 factors: Technical (25%), Sentiment (20%),
          Fundamental (15%), Macro (15%), Catalyst (15%), Volatility (10%).
        </p>
      </Section>

      {/* Entry */}
      <Section title="When and where to enter" icon={TrendingUp}>
        <p>
          <strong>Entry suggestion</strong> — the app tells you the conditions under which entering makes sense
          (e.g. "on a pullback to support", "after earnings confirmation"). Don't chase — wait for
          the described setup to appear.
        </p>
        <p>
          <strong>Price target</strong> — the AI's estimated upside. Use this to calculate your reward-to-risk ratio
          before entering. If the target is only 2% above current price but your stop is 5% below, the trade is not worth taking.
        </p>
        <p>
          <strong>Time horizon</strong> — match this to your own trading style. If the signal is short-term (days)
          but you plan to hold for months, the analysis may not apply to you.
        </p>
        <p>
          <strong>Stop loss</strong> — set this before you enter, not after. This is the price at which you
          accept the trade is wrong and exit. Never skip this step.
        </p>
      </Section>

      {/* Catalysts */}
      <Section title="Catalysts — what could push it up?" icon={AlertTriangle}>
        <p>
          <strong>Catalysts</strong> are upcoming events that could drive the stock higher —
          earnings beats, product launches, analyst upgrades, sector tailwinds.
        </p>
        <p>
          A BUY signal with a strong upcoming catalyst is a higher-conviction setup.
          A BUY signal with no clear catalyst relies entirely on technical/sentiment — higher risk.
        </p>
        <p className="text-[var(--color-fg-muted)]">
          Also read the <strong>Key Risks</strong> section. If risks outweigh catalysts even on a BUY signal,
          consider passing or reducing position size.
        </p>
      </Section>

      {/* Bull & Bear */}
      <Section title="Bull & Bear case — read both before buying" icon={TrendingUp}>
        <p>
          <strong>Bull case</strong> — confirms why the stock could go up. Use this to validate your thesis.
        </p>
        <p>
          <strong>Bear case</strong> — why the stock could go down. Before you buy, ask yourself:
          "Can I argue against this?" If you can't, your position size should be smaller.
        </p>
        <p className="text-[var(--color-fg-muted)]">
          If you find the bear case more convincing than the bull case, don't buy — regardless of the signal.
        </p>
      </Section>

      {/* Risk checklist */}
      <Section title="Pre-buy checklist" icon={ShieldAlert}>
        <Checklist items={[
          'Signal is BUY — not HOLD or SELL.',
          'Score is above 70. If 40–70, use a smaller position size.',
          'Conviction is Strong or Moderate — avoid Weak Signal entries.',
          'Entry suggestion matches current price conditions — don\'t chase.',
          'Stop loss is set before you place the order.',
          'Risk per trade is 1–2% of your total portfolio maximum.',
          'Read the bear case and key risks — you can argue against them.',
          'Macro score is not negative — a BUY in a bad macro environment is riskier.',
          'Data is recent — prefer signals updated within the last trading session.',
        ]} />
      </Section>
    </>
  )
}

// ── Seller Guide ──────────────────────────────────────────────────────────────

function SellerGuide() {
  return (
    <>
      {/* Signals for holders */}
      <Section title="What the signal means when you hold" icon={TrendingDown} defaultOpen>
        <Row label={<Pill label="BUY" color="bg-green-500/15 text-green-500" />}>
          Conditions are still favourable. Your thesis is intact. Hold your position
          and let it run toward the price target. Reassess if score drops below 50.
        </Row>
        <Row label={<Pill label="HOLD" color="bg-yellow-500/15 text-yellow-600" />}>
          Mixed signals. If you're at a profit, consider trimming part of your position.
          If you're at a loss, don't average down — wait for a clear BUY signal to recover.
        </Row>
        <Row label={<Pill label="SELL" color="bg-red-500/15 text-red-500" />}>
          Conditions are deteriorating. Reassess your position seriously.
          If the stock is near or above your price target, consider taking profit.
          If it's below your entry, review whether your original thesis still holds.
        </Row>
        <p className="text-xs text-[var(--color-fg-muted)] bg-[var(--color-bg)] rounded-xl px-4 py-3">
          <strong>Note:</strong> SELL does not mean short the stock. It means consider reducing
          or fully exiting your long position.
        </p>
      </Section>

      {/* Score for holders */}
      <Section title="Score — is my position deteriorating?" icon={Zap}>
        <Row label={<span className="font-semibold text-green-500">70–100</span>}>
          Momentum still strong. No reason to exit if your price target hasn't been hit.
          Trail your stop loss up as the stock moves in your favour.
        </Row>
        <Row label={<span className="font-semibold text-yellow-500">40–69</span>}>
          Conditions mixed. Monitor closely. Consider trimming to reduce exposure
          if you've already made a meaningful profit.
        </Row>
        <Row label={<span className="font-semibold text-red-500">0–39</span>}>
          Bearish setup. Revisit your original thesis. If it no longer holds,
          cut your position — even at a small loss. Losses get worse when ignored.
        </Row>
        <p className="text-[var(--color-fg-muted)]">
          A score that was 75 last week and is now 38 is a warning sign — the trend is turning against you.
        </p>
      </Section>

      {/* When to sell */}
      <Section title="When to take profit or cut losses" icon={TrendingDown}>
        <p>
          <strong>Price target reached</strong> — the stock has hit or exceeded the AI's price target.
          This is a natural point to take full or partial profit. Don't get greedy — targets exist for a reason.
        </p>
        <p>
          <strong>Exit suggestion</strong> — the app provides suggested exit conditions
          (e.g. "exit if price breaks below 200-day MA", "take profit near resistance").
          Use this as your trigger to act.
        </p>
        <p>
          <strong>Stop loss triggered</strong> — if the stock hits the suggested stop loss level,
          exit without hesitation. The stop loss was set when your analysis was objective —
          honour it when emotions are running high.
        </p>
        <p>
          <strong>Time horizon expired</strong> — if the trade was short-term and weeks have passed
          without movement, capital is better deployed elsewhere.
        </p>
      </Section>

      {/* Bear case for holders */}
      <Section title="Bear case — is your thesis broken?" icon={AlertTriangle}>
        <p>
          When you hold a stock, the bear case is the most important section to read.
          Ask yourself: <strong>has any of this materialised?</strong>
        </p>
        <p>
          <strong>If yes</strong> — the bear case is playing out. Your original thesis may be broken.
          This is a signal to reduce or exit, even if you're currently at a loss.
        </p>
        <p>
          <strong>If no</strong> — the bear case is still hypothetical. Your thesis holds.
          Continue to hold and monitor.
        </p>
        <p className="text-[var(--color-fg-muted)]">
          Also check <strong>Key Risks</strong> — a new risk that wasn't there when you entered
          is a reason to reassess, regardless of the current signal.
        </p>
      </Section>

      {/* Catalysts for holders */}
      <Section title="Catalysts — already priced in?" icon={TrendingUp}>
        <p>
          If you bought ahead of a catalyst (e.g. earnings, product launch) and the event has now passed,
          the catalyst may already be priced in — even if the stock went up on the day.
        </p>
        <p>
          "Buy the rumour, sell the news" — once the catalyst plays out, check whether
          new catalysts exist. If none, the stock may drift back down.
        </p>
        <p className="text-[var(--color-fg-muted)]">
          A HOLD or SELL signal after a catalyst has passed is a sign to consider taking profit,
          especially if the score has dropped from its peak.
        </p>
      </Section>

      {/* Sell checklist */}
      <Section title="Should-I-sell checklist" icon={ShieldAlert}>
        <Checklist items={[
          'Price target hit or exceeded → take full or partial profit.',
          'Stop loss triggered → exit, no exceptions.',
          'Signal flipped to SELL and score is below 40 → seriously consider exiting.',
          'Bear case has started to materialise → original thesis is broken.',
          'Catalyst already happened and no new catalysts exist → consider taking profit.',
          'Time horizon has passed with no meaningful move → redeploy capital.',
          'HOLD signal + score dropping week over week → trim position to reduce risk.',
          'You\'re holding at a loss and the signal is SELL → cut it, don\'t average down.',
          'When in doubt on a profitable position, take partial profit — never regret locking in gains.',
        ]} />
      </Section>
    </>
  )
}

// ── Guide Page ────────────────────────────────────────────────────────────────

export default function GuidePage() {
  const [view, setView] = useState<View>('buyer')

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
          How to read and act on the signals — choose your situation
        </p>
      </div>

      {/* View toggle */}
      <div className="mb-4">
        <ViewToggle view={view} onChange={setView} />
      </div>

      {/* Context pill */}
      <div className={`mb-4 px-4 py-3 rounded-xl text-xs leading-relaxed
        ${view === 'buyer'
          ? 'bg-green-500/8 border border-green-500/20 text-green-700 dark:text-green-400'
          : 'bg-orange-500/8 border border-orange-500/20 text-orange-700 dark:text-orange-400'
        }`}>
        {view === 'buyer'
          ? 'You have capital to deploy and are looking for the right moment to enter a position.'
          : 'You already hold a stock and are deciding whether to hold on, take profit, or cut your losses.'
        }
      </div>

      <div className="flex flex-col gap-3">
        {view === 'buyer' ? <BuyerGuide /> : <SellerGuide />}

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

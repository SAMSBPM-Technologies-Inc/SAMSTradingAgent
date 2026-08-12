import { useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  DollarSign,
  Server,
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

// ── Numbered step ─────────────────────────────────────────────────────────────

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-500 text-white text-xs font-bold flex items-center justify-center mt-0.5">
        {n}
      </div>
      <div className="flex-1">
        <p className="font-semibold text-[var(--color-fg)] mb-1">{title}</p>
        <div className="text-[var(--color-fg-muted)] flex flex-col gap-1.5">{children}</div>
      </div>
    </div>
  )
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-xs font-mono text-brand-500">
      {children}
    </code>
  )
}

// ── IB Gateway Setup Guide ────────────────────────────────────────────────────

function IbGatewayGuide() {
  return (
    <>
      <Section title="What is IB Gateway?" icon={Server} defaultOpen>
        <p>
          IB Gateway is a lightweight application provided by Interactive Brokers that exposes
          a local API on your machine. SAMS Trading Agent connects to this API to place and
          monitor orders in your IBKR account.
        </p>
        <p>
          You install IB Gateway on a machine you control (your PC, Mac, or a VPS). SAMS connects
          to it using the IP address and port you configure in your Profile page. No IBKR credentials
          are stored on SAMS servers.
        </p>
        <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>
            <strong>CIRO note:</strong> Automated API-based order submission is only permitted for
            US-listed securities. Canadian-exchange tickers (.TO, .V, .CN) cannot be traded via this integration.
          </span>
        </div>
      </Section>

      <Section title="Step 1 — Download and install IB Gateway" icon={Server}>
        <div className="flex flex-col gap-4">
          <Step n={1} title="Download IB Gateway">
            <p>
              Go to the Interactive Brokers website → <strong>Trading → IBKR APIs → IB Gateway</strong>.
              Download the installer for your platform (Windows, macOS, or Linux).
            </p>
            <p className="text-xs">
              Direct path: <strong>ibkr.com → Technology → Trading Tools → IB Gateway</strong>.
              Do not download TWS — IB Gateway is the headless version designed for API use.
            </p>
          </Step>
          <Step n={2} title="Run the installer">
            <p>Run the downloaded installer and follow the on-screen steps. No special configuration is needed during installation.</p>
          </Step>
          <Step n={3} title="Launch IB Gateway">
            <p>Open IB Gateway. You will see a login screen — enter your IBKR username and password.</p>
            <p>At the top-left, select <strong>IB API</strong> (not Proprietary Trading Firm). Choose either <strong>Paper Trading</strong> or <strong>Live Trading</strong> depending on your intent.</p>
          </Step>
        </div>
      </Section>

      <Section title="Step 2 — Enable the API" icon={Server}>
        <div className="flex flex-col gap-4">
          <Step n={1} title="Open the API settings">
            <p>Inside IB Gateway, go to <strong>Configure → Settings</strong> (or the gear icon).</p>
            <p>Navigate to <strong>API → Settings</strong>.</p>
          </Step>
          <Step n={2} title="Enable socket connections">
            <p>Check <strong>Enable ActiveX and Socket Clients</strong>.</p>
            <p>Uncheck <strong>Read-Only API</strong> — this is required for order submission. Without this, SAMS can read your account but cannot place orders.</p>
          </Step>
          <Step n={3} title="Confirm the port">
            <p>The default ports are:</p>
            <div className="flex flex-col gap-1 mt-1">
              <p><Code>4001</Code> — Live Trading</p>
              <p><Code>4003</Code> — Paper Trading</p>
            </div>
            <p className="mt-1">Note the port you see here — you will enter it in your SAMS Profile.</p>
          </Step>
          <Step n={4} title="(Optional) Trusted IPs">
            <p>
              If SAMS is hosted on a server with a known IP, you can add that IP to the
              <strong> Trusted IPs</strong> list for additional security. If left blank, any local
              or network connection can reach the API.
            </p>
          </Step>
        </div>
      </Section>

      <Section title="Step 3 — Configure your SAMS Profile" icon={Server}>
        <div className="flex flex-col gap-4">
          <Step n={1} title="Find your machine's IP address">
            <p>
              If IB Gateway is running on the <strong>same machine as SAMS</strong> (e.g. a VPS),
              use <Code>127.0.0.1</Code> as the host.
            </p>
            <p>
              If IB Gateway is on a <strong>different machine</strong> (e.g. your home PC, SAMS on cloud),
              use the external IP of that machine. Ensure port <Code>4003</Code> or <Code>4001</Code> is
              open in your firewall/router.
            </p>
          </Step>
          <Step n={2} title="Enter connection details in SAMS">
            <p>Go to <strong>Profile → IB Gateway Connection</strong>.</p>
            <p>Enter the <strong>Host</strong> (IP address) and <strong>Port</strong> you noted above.</p>
            <p>If you have multiple IBKR sub-accounts, enter your <strong>Account ID</strong> (e.g. <Code>U1234567</Code>) — found in IBKR Client Portal under Account Settings. Leave blank to use the default account.</p>
          </Step>
          <Step n={3} title="Save and verify">
            <p>Click <strong>Save</strong>. Then navigate to <strong>Profile → Auto Trading</strong> to check the connection status indicator.</p>
            <p>If the status shows <strong>IB Gateway offline</strong>, double-check that IB Gateway is running and the host/port is correct.</p>
          </Step>
        </div>
      </Section>

      <Section title="Keeping IB Gateway running" icon={AlertTriangle}>
        <p>
          IB Gateway must be running at all times for automated trading to work. If it stops
          (e.g. session timeout, reboot), SAMS will skip trades and log a "not connected" reason.
        </p>
        <p>
          <strong>Session timeout:</strong> IB Gateway sessions expire after 24 hours by default.
          To extend this, in IB Gateway go to <strong>Configure → Settings → Lock and Exit</strong>
          and set Auto Logoff Time to a late hour (e.g. 11:59 PM) or disable it.
        </p>
        <p>
          <strong>Auto-start on reboot:</strong> On Windows, add IB Gateway to your Startup folder.
          On Linux/macOS, set it up as a systemd service or launchd agent. Interactive Brokers also
          offers <strong>IBC</strong> (a free open-source tool) to manage automated startup and login.
        </p>
        <div className="flex items-start gap-2 p-3 rounded-xl bg-blue-500/10 text-blue-400 text-xs">
          <Server className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>
            <strong>Tip:</strong> For reliable unattended operation, run IB Gateway on a VPS (cloud server)
            rather than your home PC. A VPS is always on, has a stable IP, and won't go to sleep.
          </span>
        </div>
      </Section>

      <Section title="Ports and firewall reference" icon={ShieldAlert}>
        <div className="flex flex-col gap-2">
          <Row label={<Code>4001</Code>}>IB Gateway — Live Trading API (default)</Row>
          <Row label={<Code>4003</Code>}>IB Gateway — Paper Trading API (default)</Row>
          <Row label={<Code>7496</Code>}>TWS — Live Trading (if using Trader Workstation instead)</Row>
          <Row label={<Code>7497</Code>}>TWS — Paper Trading (if using Trader Workstation instead)</Row>
        </div>
        <p className="text-xs text-[var(--color-fg-muted)] mt-2">
          Only open these ports to trusted IPs. If SAMS and IB Gateway are on the same machine,
          no firewall changes are needed — use <Code>127.0.0.1</Code> as the host.
        </p>
      </Section>
    </>
  )
}

type View = 'buyer' | 'seller' | 'setup'

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const tabs: { key: View; label: string; icon: React.FC<{ className?: string }> }[] = [
    { key: 'buyer', label: 'I want to buy', icon: DollarSign },
    { key: 'seller', label: 'I hold stocks', icon: TrendingDown },
    { key: 'setup', label: 'IB Gateway setup', icon: Server },
  ]
  return (
    <div className="flex rounded-xl border border-[var(--color-border)] overflow-hidden bg-[var(--color-surface)] p-1 gap-1 flex-wrap sm:flex-nowrap">
      {tabs.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 whitespace-nowrap
            ${view === key
              ? 'bg-brand-500 text-white shadow-sm'
              : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]'
            }`}
        >
          <Icon className="w-4 h-4" />
          {label}
        </button>
      ))}
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
      {view !== 'setup' && (
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
      )}

      <div className="flex flex-col gap-3">
        {view === 'buyer' ? <BuyerGuide /> : view === 'seller' ? <SellerGuide /> : <IbGatewayGuide />}

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

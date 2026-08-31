import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Check } from 'lucide-react'
import { contactApi } from '../lib/api'
import { IconMark, LogoLockup } from '../components/Logo'
import PipelineDiagram from '../components/PipelineDiagram'
import ThemeToggle from '../components/ThemeToggle'
import LoadingSpinner from '../components/LoadingSpinner'

/* The public face of sta.samsbpm.com.
 *
 * Set like a document rather than assembled from cards. Sections are numbered,
 * separated by hairlines and hung off a six-column grid; the only filled block
 * on the page is the Discipline band, and it is filled because that section is
 * the argument. There are no feature icons — an icon that illustrates nothing
 * is decoration standing where a fact should be.
 *
 * The page reads no auth state and makes no request on load. The one network
 * call it can make is the contact form, and only when a visitor submits it.
 * That is what keeps the eventual move to a public host cheap: delete the
 * branch in App.tsx, point the form at the same API.
 *
 * Every claim here is one the engine actually makes. The sample readout is
 * labelled a sample.
 */

// ── Chrome ────────────────────────────────────────────────────────────────────

const SECTIONS = [
  { href: '#loop', label: 'The loop' },
  { href: '#capabilities', label: 'Capabilities' },
  { href: '#discipline', label: 'Discipline' },
  { href: '#proof', label: 'Proof' },
  { href: '#faq', label: 'Questions' },
  { href: '#contact', label: 'Contact' },
]

function HomeNav() {
  return (
    <header className="sticky top-0 z-50 border-b home-hr bg-[var(--color-bg)]">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6"
      >
        <Link to="/" className="rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/50">
          <LogoLockup />
        </Link>

        <ul className="hidden items-center gap-6 lg:flex">
          {SECTIONS.map((s) => (
            <li key={s.href}>
              <a
                href={s.href}
                className="text-[13px] text-[var(--color-fg-muted)] transition-colors hover:text-[var(--color-fg)]"
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>

        {/* Same ordering as the hero, and for the same reason: the button a
            stranger can actually use is the one that asks for an account. */}
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <Link
            to="/auth"
            className="hidden whitespace-nowrap px-2 text-[13px] text-[var(--color-fg-muted)]
                       transition-colors hover:text-[var(--color-fg)] sm:inline"
          >
            Sign in
          </Link>
          <a href="#contact" className="btn-primary whitespace-nowrap">
            Request access
          </a>
        </div>
      </nav>
    </header>
  )
}

/** Section number and title in the left gutter, content in the right columns. */
function Section({
  id,
  index,
  kicker,
  title,
  lede,
  children,
  band = false,
}: {
  id: string
  index: string
  kicker: string
  title: string
  lede?: string
  children: React.ReactNode
  band?: boolean
}) {
  const rule = band ? 'border-[var(--home-band-rule)]' : 'home-hr'
  const muted = band ? 'text-[var(--home-band-muted)]' : 'text-[var(--color-fg-muted)]'

  return (
    <section id={id} className={band ? 'home-band' : ''}>
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <div className="grid gap-x-10 gap-y-6 lg:grid-cols-12">
          <div className="lg:col-span-3">
            <p className={`flex items-baseline gap-3 border-t pt-3 ${rule}`}>
              <span className={`num text-[13px] font-semibold ${band ? '' : 'text-brand-500'}`}>
                {index}
              </span>
              <span className="label-micro" style={band ? { color: 'var(--home-band-muted)' } : undefined}>
                {kicker}
              </span>
            </p>
          </div>

          <div className="lg:col-span-9">
            <h2 className="font-fraunces text-[1.75rem] leading-[1.15] tracking-tight sm:text-[2.5rem]">
              {title}
            </h2>
            {lede && (
              <p className={`mt-5 max-w-2xl text-[15px] leading-relaxed ${muted}`}>{lede}</p>
            )}
          </div>
        </div>

        <div className="mt-12 sm:mt-16">{children}</div>
      </div>
    </section>
  )
}

// ── Hero ──────────────────────────────────────────────────────────────────────

/* The six factors the engine combines, with the shipped default weights.
   Shown because attribution is the product: a score with no decomposition is
   a number you have to take on faith. */
const FACTORS = [
  { name: 'Technical', score: 0.82, weight: 0.30 },
  { name: 'Catalyst', score: 0.88, weight: 0.15 },
  { name: 'Fundamental', score: 0.71, weight: 0.20 },
  { name: 'Sentiment', score: 0.64, weight: 0.15 },
  { name: 'Macro', score: 0.55, weight: 0.10 },
  { name: 'Volatility', score: 0.49, weight: 0.10 },
]

/** A readout, not a card: the shape of what the engine actually returns. */
function Readout() {
  return (
    <figure className="m-0 border home-hr bg-[var(--color-surface)]">
      <figcaption className="flex items-center justify-between border-b home-hr px-4 py-2.5">
        <span className="label-micro">Sample output</span>
        <span className="label-micro">14:35:02 ET</span>
      </figcaption>

      <div className="flex items-end justify-between gap-4 border-b home-hr px-4 py-4">
        <div>
          <p className="num text-[13px] tracking-[0.06em] text-[var(--color-fg-muted)]">NVDA</p>
          <p className="num text-[3.25rem] font-semibold leading-none tracking-tight">78</p>
        </div>
        <div className="pb-1 text-right">
          <p className="num text-[13px] font-semibold text-[var(--accent-buy)]">BUY</p>
          <p className="num mt-1 text-[11px] text-[var(--color-fg-muted)]">conviction HIGH</p>
        </div>
      </div>

      <table className="w-full border-collapse">
        <caption className="sr-only">Factor contributions to the sample score</caption>
        <tbody>
          {FACTORS.map((f, i) => (
            <tr key={f.name} className="border-b home-hr last:border-b-0">
              <th scope="row" className="w-[92px] px-4 py-[7px] text-left text-[11px] font-normal text-[var(--color-fg-muted)]">
                {f.name}
              </th>
              <td className="py-[7px] pr-3">
                <span className="block h-[3px] bg-[var(--color-hover)]">
                  <span
                    className="home-bar block h-full bg-brand-500"
                    style={{ width: `${f.score * 100}%`, animationDelay: `${320 + i * 70}ms` }}
                  />
                </span>
              </td>
              <td className="num w-[52px] px-4 py-[7px] text-right text-[11px] text-[var(--color-fg-muted)]">
                {f.weight.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <dl className="grid grid-cols-2 border-t home-hr">
        {[
          ['Risk gate', '4.1 < 6.0'],
          ['Threshold', '0.78 > 0.70'],
          ['Confirmed', '3 of 3 fresh'],
          ['Dwell', '45 min'],
        ].map(([k, v], i) => (
          <div
            key={k}
            className={`px-4 py-3 ${i % 2 === 0 ? 'border-r home-hr' : ''} ${i < 2 ? 'border-b home-hr' : ''}`}
          >
            <dt className="label-micro mb-1">{k}</dt>
            <dd className="num text-[12px]">{v}</dd>
          </div>
        ))}
      </dl>
    </figure>
  )
}

const CADENCE = [
  ['06', 'weighted factors per score'],
  ['05', 'minute evaluation cycle'],
  ['04', 'research agents in parallel'],
  ['00', 'uncited claims retained'],
]

function Hero() {
  return (
    <section className="relative overflow-hidden border-b home-hr">
      <div className="home-wash" aria-hidden="true" />
      <div className="home-columns relative mx-auto max-w-6xl px-4 sm:px-6">
        {/* z-1: sits above the decorative column rules, which are drawn on
            .home-columns::before and would otherwise cross the readout. */}
        <div className="relative z-[1] grid gap-12 py-16 sm:py-24 lg:grid-cols-12 lg:gap-10">
          <div className="home-rise lg:col-span-7">
            <p className="label-micro mb-8">Autonomous equity research &amp; execution</p>

            <h1 className="font-fraunces text-[2.75rem] leading-[1.02] tracking-tight sm:text-[4.25rem] lg:text-[4.75rem]">
              Every verdict
              <br />
              arrives with its
              <br />
              evidence attached.
            </h1>

            <p className="mt-8 max-w-lg border-t home-hr pt-6 text-[15px] leading-relaxed text-[var(--color-fg-muted)] sm:text-base">
              Six factors, one score, and the arithmetic that produced it — plus the
              threshold it had to clear, the risks its own red team raised, and the guard
              that would have stopped the trade. Research, scoring and execution in one
              loop, on your rules.
            </p>

            {/* Request access is primary and Sign in is not, because almost
                everybody reading this page does not have an account — there is
                no self-serve signup, so "Sign in" is a door they cannot open.
                Leading with it left a first-time visitor no route at all: the
                only explanation of how to get in was section 06, below four
                screens of argument. */}
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <a href="#contact" className="btn-primary h-11 px-6">
                Request access
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </a>
              <a href="#loop" className="btn-secondary h-11 px-5">
                How it works
              </a>
              <Link
                to="/auth"
                className="h-11 px-2 text-[13.5px] leading-[2.75rem] text-[var(--color-fg-muted)]
                           underline-offset-4 transition-colors hover:text-[var(--color-fg)] hover:underline"
              >
                Already have an account?
              </Link>
            </div>

            <p className="mt-5 text-[13px] leading-relaxed text-[var(--color-fg-muted)]">
              Accounts are provisioned by hand — there is no signup form. Tell us
              what you trade and you will get credentials by email.
            </p>
          </div>

          <div className="home-rise lg:col-span-5" style={{ animationDelay: '120ms' }}>
            <Readout />
          </div>
        </div>
      </div>

      <div className="relative border-t home-hr">
        <dl className="mx-auto grid max-w-6xl grid-cols-2 px-4 sm:px-6 lg:grid-cols-4">
          {CADENCE.map(([figure, label], i) => (
            <div
              key={label}
              className={`py-6 pr-6 ${i < 3 ? 'lg:border-r' : ''} ${i % 2 === 0 ? 'border-r lg:border-r' : ''} ${
                i < 2 ? 'border-b lg:border-b-0' : ''
              } home-hr lg:pl-6 lg:first:pl-0`}
            >
              <dt className="num text-2xl font-semibold sm:text-3xl">{figure}</dt>
              <dd className="mt-1.5 text-[12px] leading-relaxed text-[var(--color-fg-muted)]">
                {label}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}

// ── The loop ──────────────────────────────────────────────────────────────────

const STEPS = [
  [
    'Ingest',
    'Prices, filings, earnings history, news sentiment, macro rates and options flow, on a five-minute clock. Filings accumulate rather than overwrite — that is what makes a trend computable at all.',
  ],
  [
    'Score',
    'Six weighted factors resolve to one number, and the decomposition ships with it. Where a score comes from a model that cannot be decomposed, the page says so rather than inventing a breakdown.',
  ],
  [
    'Confirm',
    'A changed verdict is a candidate, not news. It publishes only once consecutive fresh evaluations agree and the standing call has served its minimum dwell. Exits are exempt from every delay.',
  ],
  [
    'Act',
    'Propose to you, execute only above a conviction line, or run unattended — the same guard chain either way. Nothing opens without a stop and a target already protecting it.',
  ],
]

function Loop() {
  return (
    <Section
      id="loop"
      index="01"
      kicker="The loop"
      title="From raw ticks to a position, twelve times an hour."
      lede="The same cycle runs on every watched name, all session. Each stage records what it did, so no step has to be taken on faith."
    >
      <PipelineDiagram />

      <ol className="mt-14 grid border-t home-hr sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map(([title, body], i) => (
          <li
            key={title}
            className="border-b home-hr py-7 pr-8 sm:odd:border-r lg:border-r lg:pl-8 lg:first:pl-0 lg:last:border-r-0"
          >
            <p className="num mb-4 text-[11px] font-semibold text-brand-500">0{i + 1}</p>
            <h3 className="font-archivo mb-3 text-[15px] font-semibold">{title}</h3>
            <p className="text-[13px] leading-relaxed text-[var(--color-fg-muted)]">{body}</p>
          </li>
        ))}
      </ol>
    </Section>
  )
}

// ── Capabilities ──────────────────────────────────────────────────────────────

const CAPABILITIES = [
  [
    'Attribution, not assertion',
    'Every verdict returns each factor’s sub-score, its weight and the points it contributed, alongside the exact buy and sell thresholds it was measured against — read from the engine, never restated in the interface.',
  ],
  [
    'Signals that stop flickering',
    'One name alerted eight times in 65 minutes at an unchanged score. Confirmation counts, a minimum dwell and a one-sided hysteresis band now sit between computing a verdict and publishing one.',
  ],
  [
    'Research that cites, or is deleted',
    'Four scoped agents work from a shared ledger where every fact carries an id, a source and a date. An uncited claim is stripped before storage — not flagged — and the audit of what was removed travels with the report.',
  ],
  [
    'A red team that never saw the bull case',
    'Hand one model a thesis and ask for the risks and it argues inside that framing. The risk agent runs in the fan-out instead, blind to the bull case, and the synthesis must address or carry every risk it raises.',
  ],
  [
    'Autonomy on a dial',
    'Manual queues a proposal for your approval; semi-auto acts alone only above a conviction line you set; auto runs unattended. A proposal commits nothing — it never consumes a position slot or reaches your realised record.',
  ],
  [
    'Net, not gross',
    'Commissions accrue from the venue’s own execution reports across the entry, every add and the exit. A cost the broker has not reported yet stays unknown rather than being folded in at zero.',
  ],
]

function Capabilities() {
  return (
    <Section
      id="capabilities"
      index="02"
      kicker="Capabilities"
      title="Six things a spreadsheet and a news feed will not do for you."
      lede="Each of these exists because the naive version failed in production first. The failures are in the changelog; the fixes are in the product."
    >
      <dl className="border-t home-hr">
        {CAPABILITIES.map(([term, description]) => (
          <div key={term} className="grid gap-2 border-b home-hr py-7 lg:grid-cols-12 lg:gap-10">
            <dt className="font-archivo text-[15px] font-semibold lg:col-span-4">{term}</dt>
            <dd className="max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-fg-muted)] lg:col-span-8">
              {description}
            </dd>
          </div>
        ))}
      </dl>
    </Section>
  )
}

// ── Discipline ────────────────────────────────────────────────────────────────

const RULES = [
  [
    'Selling is never delayed.',
    'Every brake in the system sits on the entry path. Delaying an exit costs money; delaying an entry costs an opportunity. The two are not symmetrical and are not treated as such.',
  ],
  [
    'Research can veto a buy. It can never create one.',
    'A dossier can stop a trade the score wanted. It cannot open one, enlarge one, or reach an exit — and every uncertain path, from a missing report to a database error, allows the trade rather than halting your account over a cron job.',
  ],
  [
    'Nothing opens without a bracket.',
    'A stop and a target go out with the position, sized to what the broker says is actually held. An add may never loosen the stop already protecting the holding.',
  ],
  [
    'The quantity on your screen is a request.',
    'The server takes the smaller of what you asked for and what the risk model sizes to, so a position limit cannot be escaped from a form field. Orders are idempotent. Live money asks you to type the ticker back first.',
  ],
]

function Discipline() {
  return (
    <Section
      id="discipline"
      index="03"
      kicker="Discipline"
      title="The interesting part is what it refuses to do."
      lede="Anything can be built to place orders. These four rules decide when it will not. Each was written down after a real incident, and none of them is optional."
      band
    >
      <ol className="border-t border-[var(--home-band-rule)]">
        {RULES.map(([rule, why], i) => (
          <li
            key={rule}
            className="grid gap-3 border-b border-[var(--home-band-rule)] py-7 lg:grid-cols-12 lg:gap-10"
          >
            <p className="num text-[11px] font-semibold lg:col-span-1">0{i + 1}</p>
            <h3 className="font-archivo text-[15px] font-semibold leading-snug lg:col-span-4">
              {rule}
            </h3>
            <p className="max-w-2xl text-[13.5px] leading-relaxed text-[var(--home-band-muted)] lg:col-span-7">
              {why}
            </p>
          </li>
        ))}
      </ol>
    </Section>
  )
}

// ── Proof ─────────────────────────────────────────────────────────────────────

const PROOF = [
  [
    'Calibration reports. It does not tune.',
    'A dedicated screen asks whether the score actually ranks outcomes, what every candidate buy cutoff would have returned, and whether stated confidence tracks being right. There is no button that quietly refits the thresholds to flatter the record.',
  ],
  [
    'A thin sample says it is thin.',
    'Every row carries its sample count. Below the significance floor it is marked thin rather than dressed up as a confident-looking percentage — the number that would have persuaded you is the one held back.',
  ],
  [
    'Three records, never pooled.',
    'Trades the agent placed unattended, trades it proposed and you approved, and trades you chose yourself are reported apart. Only the first is a clean read of the engine; pooling them makes the engine look like whatever you did.',
  ],
]

function Proof() {
  return (
    <Section
      id="proof"
      index="04"
      kicker="Proof"
      title="Built to be checked, including against itself."
      lede="The failure mode of every system like this is a record that flatters itself. These are the defences against that, and they are what to judge it on."
    >
      <div className="grid border-t home-hr lg:grid-cols-3">
        {PROOF.map(([title, body], i) => (
          <div
            key={title}
            className={`py-7 pr-8 ${i < 2 ? 'border-b lg:border-b-0 lg:border-r' : ''} home-hr lg:pl-8 lg:first:pl-0`}
          >
            <h3 className="font-archivo mb-3 text-[15px] font-semibold">{title}</h3>
            <p className="text-[13px] leading-relaxed text-[var(--color-fg-muted)]">{body}</p>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ── Questions ─────────────────────────────────────────────────────────────────

/* The questions people actually ask before trusting software with a brokerage
 * account, answered here rather than in a reply to the contact form.
 *
 * Two rules govern what may go in this list. Every answer has to be true of
 * the shipped system today — where the honest answer is "nothing yet", it says
 * so, because a FAQ is the first place a reader checks whether the rest of the
 * page was written carefully. And every answer names the limit alongside the
 * capability: the position caps are listed with the two ways a loss can still
 * exceed them, since a reader who finds that out later stops believing the
 * first half too.
 */
const FAQS: [string, string][] = [
  [
    'Will it trade my money without asking me?',
    'Only if you set it to. Autonomy is a three-position dial and a new account starts on manual, where the agent runs every guard, sizes the order and picks the bracket levels, then queues it as a proposal for you to accept or decline. Semi-auto acts alone only at or above a conviction line you choose. Fully unattended is opt-in, and a live-money order asks you to type the ticker back before it will send.',
  ],
  [
    'What has it actually returned?',
    'Nothing, in the sense that matters: no real money has ever been traded through it. Production has run against a paper brokerage session since August 2026, and that record tests plumbing — that orders route, brackets attach, fills reconcile, exits settle, commissions accrue — not whether the signals are any good. Paper fills are optimistic and the sample is weeks long. Any performance figure quoted from it would be misleading, so none is quoted.',
  ],
  [
    'Do you hold my money?',
    'No. The platform never takes custody of cash or securities. Orders route to your own Interactive Brokers account, under your own credentials, and your positions stay yours whatever happens to us.',
  ],
  [
    'What happens to my positions if your servers go down?',
    'They keep their protection. Stops and targets are placed at the broker, not held in our application, so they survive this service crashing, the gateway dropping or the host going offline. What stops is new orders and signal-driven exits — the agent does not sell on its own outside a sell signal, and a sell signal needs the service running. That asymmetry is why nothing is allowed to open without a bracket already on it.',
  ],
  [
    'Do you have my brokerage password?',
    'Encrypted, yes — it has to be, for the agent to hold a session with your broker. It is stored encrypted at rest with a key that lives only in the server environment, decrypted in memory to authenticate, and never sent to any model or third party. It is a real credential in our custody and worth weighing as one.',
  ],
  [
    'Can it lose more than I told it to risk?',
    'The limits are hard: a cap per position measured on cost basis against equity frozen at entry, a cap on open positions, a daily realised-loss kill switch, a cash reserve held back from sizing, and margin off, so it cannot buy what the account cannot pay for. Three honest caveats. The kill switch counts realised losses, so an unrealised drawdown does not trip it. A stop fills at the next available price, not at the stop price, so an overnight gap can exceed the intended loss. And there are no sector or correlation limits yet, so several positions can turn out to be one bet.',
  ],
  [
    'Why did it not buy something I expected it to?',
    'Every refusal records its reason, and you can read the arithmetic: each factor’s sub-score, the weight it carried, the points it contributed, and which threshold the name failed. Verdicts are also deliberately slow to change — a new one publishes only after consecutive fresh evaluations agree and the standing call has served its minimum dwell — so a borderline name will not flip at you all afternoon.',
  ],
  [
    'Why will it sell straight away but wait to buy?',
    'Because delaying an exit costs money and delaying an entry costs an opportunity, and those are not the same price. Confirmation, dwell and the risk gate all sit on the entry path. Sells are exempt from every one of them, and no brake will be added to the exit path to make the two look symmetrical.',
  ],
  [
    'What do I need to run it?',
    'An Interactive Brokers account and IB Gateway; Alpaca is supported as an alternative venue. Automated order placement is limited to US-listed securities — Canadian-listed tickers are refused at the first guard, because API-based automated trading of them is not permitted under CIRO rules. You can watch and analyse any name the data providers cover without connecting a broker at all.',
  ],
  [
    'Can I score names my own way?',
    'Yes. The six factor weights are yours to set per account, and your weighting is applied with the same thresholds and the same hysteresis the engine uses, so your view and the stored verdict cannot quietly diverge. What you cannot do is turn off a risk guard from the interface.',
  ],
  [
    'Is my data used to train models?',
    'No. What reaches a model is market data — prices, indicators, filings figures, public headlines. Your identity, your positions, your account numbers and your credentials are not in any prompt. We reply to the address you give us and use it for nothing else.',
  ],
  [
    'How do I get an account, and what does it cost?',
    'By asking. There is no self-serve signup: accounts are provisioned by hand, because the product is early and we would rather know who is running it. Pricing is not set — if that matters to your decision, say so in your message and you will get a straight answer rather than a placeholder.',
  ],
]

function Faq() {
  return (
    <Section
      id="faq"
      index="05"
      kicker="Questions"
      title="What people ask before connecting a broker."
      lede="Answered as they would be in a reply, including where the answer is that something does not exist yet."
    >
      <div className="home-faq border-t home-hr">
        {FAQS.map(([question, answer], i) => (
          <details key={question} className="group border-b home-hr" open={i === 0}>
            <summary
              /* Flex on a phone so the question and the sign share a line; the
                 twelve-column grid only applies where the gutter number exists. */
              className="flex list-none items-baseline justify-between gap-4 py-6
                         lg:grid lg:grid-cols-12 lg:gap-10
                         rounded-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50"
            >
              <span className="num hidden text-[11px] font-semibold text-brand-500 lg:col-span-1 lg:block">
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="font-archivo text-[15px] font-semibold leading-snug lg:col-span-9">
                {question}
              </h3>
              <span
                aria-hidden="true"
                className="faq-sign num justify-self-start text-[18px] font-normal leading-none
                           text-[var(--color-fg-muted)] lg:col-span-2 lg:justify-self-end"
              >
                +
              </span>
            </summary>
            <div className="grid gap-3 pb-7 lg:grid-cols-12 lg:gap-10">
              <p className="max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-fg-muted)] lg:col-span-9 lg:col-start-2">
                {answer}
              </p>
            </div>
          </details>
        ))}
      </div>

      <p className="mt-10 border-t home-hr pt-6 text-[13.5px] leading-relaxed text-[var(--color-fg-muted)]">
        Something not here?{' '}
        <a href="#contact" className="text-brand-500 underline-offset-4 hover:underline">
          Ask it directly
        </a>
        {' '}— the list grows from what gets asked.
      </p>
    </Section>
  )
}

// ── Contact ───────────────────────────────────────────────────────────────────

function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  // Honeypot. A real visitor never sees this field, so anything in it came
  // from a bot filling every input on the page.
  const [company, setCompany] = useState('')
  // What they are after, in a visitor's terms. Deliberately not "Basic / Pro /
  // Trader": a stranger has no idea what those mean, and naming plans on a page
  // that quotes no prices invites a question the page cannot answer. A static
  // list, because this page reads no context and makes no request on load —
  // that property is what keeps moving it to a public host a one-line change.
  const [interest, setInterest] = useState<'' | 'read' | 'research' | 'trade'>('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSending(true)
    try {
      await contactApi.send({ name, email, message, company, interest })
      setSent(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Could not send that just now. Please try again in a moment.')
    } finally {
      setSending(false)
    }
  }

  if (sent) {
    return (
      <div role="status" className="border home-hr p-6">
        <Check className="mb-3 h-5 w-5 text-[var(--accent-buy)]" aria-hidden="true" />
        <p className="font-archivo text-[15px] font-semibold">Message sent.</p>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--color-fg-muted)]">
          It went to the SAMSBPM team. You will get a reply at {email}.
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="contact-name" className="label-micro">
          Name
        </label>
        <input
          id="contact-name"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={120}
          autoComplete="name"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="contact-email" className="label-micro">
          Email
        </label>
        <input
          id="contact-email"
          type="email"
          className="input"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          maxLength={254}
          autoComplete="email"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="contact-interest" className="label-micro">
          What are you after
        </label>
        <select
          id="contact-interest"
          className="input"
          value={interest}
          onChange={(e) => setInterest(e.target.value as typeof interest)}
        >
          <option value="">Not sure yet</option>
          <option value="read">Just want to see the analysis</option>
          <option value="research">In-depth research on my own names</option>
          <option value="trade">Trading through my own IB account</option>
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="contact-message" className="label-micro">
          Message
        </label>
        <textarea
          id="contact-message"
          className="input min-h-[7rem] resize-y py-2.5"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
          minLength={10}
          maxLength={4000}
        />
      </div>

      {/* Off-screen rather than display:none — some bots skip hidden inputs. */}
      <div className="sr-only" aria-hidden="true">
        <label htmlFor="contact-company">Company (leave blank)</label>
        <input
          id="contact-company"
          tabIndex={-1}
          autoComplete="off"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
      </div>

      {error && (
        <p role="alert" className="text-[13px] text-[var(--accent-sell)]">
          {error}
        </p>
      )}

      <button type="submit" className="btn-primary mt-1 h-11 self-start px-6" disabled={sending}>
        {sending ? <LoadingSpinner size="sm" /> : null}
        {sending ? 'Sending…' : 'Send message'}
      </button>
    </form>
  )
}

function Contact() {
  return (
    <Section
      id="contact"
      index="06"
      kicker="Contact"
      title="Ask a question, or request an account."
      lede="There is no self-serve signup — accounts are provisioned by hand. Tell us what you trade and what you want the agent to do, and we will come back to you."
    >
      <div className="grid gap-10 border-t home-hr pt-10 lg:grid-cols-12 lg:gap-16">
        <div className="lg:col-span-5">
          <p className="text-[13.5px] leading-relaxed text-[var(--color-fg-muted)]">
            Messages reach the team directly. We reply to the address you give us and use it
            for nothing else — no list, no sequence.
          </p>
          <p className="mt-6 border-t home-hr pt-6 text-[13.5px] leading-relaxed text-[var(--color-fg-muted)]">
            Already have an account?{' '}
            <Link to="/auth" className="text-brand-500 underline-offset-4 hover:underline">
              Sign in
            </Link>
            .
          </p>
        </div>
        <div className="lg:col-span-7">
          <ContactForm />
        </div>
      </div>
    </Section>
  )
}

// ── Footer ────────────────────────────────────────────────────────────────────

function Footer() {
  return (
    <footer className="border-t home-hr bg-[var(--color-surface)]">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="flex flex-col gap-8 border-b home-hr pb-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-center gap-3">
            <IconMark size={26} />
            <p className="font-fraunces text-[15px] font-semibold">SAMSBPM Trading Agent</p>
          </div>

          <a
            href="https://samsbpm.com"
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1.5 text-[13px] text-[var(--color-fg-muted)]
                       transition-colors hover:text-brand-500"
          >
            Developed by SAMSBPM Technologies Inc
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        </div>

        {/* Same disclaimer the application carries, for the same reason. */}
        <p className="mt-8 max-w-3xl text-[11.5px] leading-relaxed text-[var(--color-fg-muted)]">
          <strong className="text-[var(--color-fg)]">Not financial advice.</strong> SAMSBPM
          Trading Agent is an automated analysis tool provided for informational purposes
          only. It is not a registered investment adviser, broker-dealer, or portfolio
          manager, and nothing here is a recommendation to buy or sell any security. Signals
          are model output, not research; past signal accuracy does not predict future
          results. Trading involves risk of loss, including total loss of capital. You are
          solely responsible for your investment decisions.
        </p>

        <p className="mt-6 text-[11.5px] text-[var(--color-fg-muted)]">
          © {new Date().getFullYear()} SAMSBPM Technologies Inc. All rights reserved.
        </p>
      </div>
    </footer>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HomePage() {
  // Arriving at `/home#contact` — which is where the sign-in screen sends
  // somebody who has no account — must actually land on the contact form.
  // React Router does not act on a hash fragment by itself, so a link that
  // looks like it works would quietly drop the visitor at the top of the page,
  // four screens above the only thing they came for.
  //
  // Reading `window.location.hash` is not a violation of this page making no
  // request and reading no context on load: it touches neither the API nor any
  // provider, so moving this page to its own public host stays a one-line
  // change.
  useEffect(() => {
    const id = window.location.hash.slice(1)
    if (!id) return
    // After paint, or the target does not exist to scroll to yet.
    const frame = requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <div className="home-scroll min-h-dvh bg-[var(--color-bg)] text-[var(--color-fg)]">
      <HomeNav />
      <main>
        <Hero />
        <Loop />
        <div className="border-t home-hr" />
        <Capabilities />
        <Discipline />
        <Proof />
        <div className="border-t home-hr" />
        <Faq />
        <div className="border-t home-hr" />
        <Contact />
      </main>
      <Footer />
    </div>
  )
}

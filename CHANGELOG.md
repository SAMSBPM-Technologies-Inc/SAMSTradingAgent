# Changelog

All notable changes to SAMSTradingAgent are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project aims at [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Backend, frontend, and mobile deploy together from this repository and share a
single version.

**Two conventions worth keeping.** Record *behaviour* changes, not commit
subjects — the question a reader has is "what is different for me", and a list
of subjects answers a different one. And keep the **Known gaps** section honest:
a release note that only lists wins is the kind of document nobody trusts twice.

---

## [1.10.0] — 2026-08-27

The front door.

**sta.samsbpm.com no longer opens on a password prompt.** Anyone arriving at
the root now gets a public landing page: what the agent does, the loop it runs
every five minutes, the six factors behind a score, and — the part worth
reading — the four rules that decide when it will *not* place an order. Sign in
sits top right; signing in lands you on the same dashboard as before, and a
signed-in visit to `/` still goes straight there, so nothing changed for an
existing user. The page is also served at `/home`.

It is set as a document rather than assembled from cards: numbered sections on
a column grid, hairline rules, one inverted band for the section that carries
the argument, and no decorative icons. The sample readout on the hero shows the
real shape of an engine response — score, six weighted factors, risk gate,
confirmation count — and is labelled a sample. Every claim on the page is one
the system actually makes elsewhere in this changelog.

**A contact form, going to the team.** No self-serve signup exists, so the page
asks for a message instead of pretending to offer an account. `POST /contact`
is the only unauthenticated write on the API and the only way a stranger can
make the server send mail, so it is rate limited per address counting *every*
submission, carries a honeypot that returns a normal success, caps every field
in the schema, and puts the sender in `Reply-To` rather than forging a `From`.
It is also the one mail path that reports failure to the caller: everywhere
else an outage is logged and ignored so trading continues, but a visitor told
"sent" when nothing was sent has been lied to and has no other route to anyone.

**The logo is now drawn in one place.** `IconMark` and `LogoLockup` moved out
of `Layout.tsx` into `components/Logo.tsx`. They were private to the app chrome
while the chrome was the only consumer; the landing page was the second, and
the first version of it drew its own mark that matched nothing shipped. The
sign-in page was a third, and had been drawing a gradient "S" over an orange
wordmark since long before any of this — so the one screen every user passes
through looked like a different product from the app behind it. All three now
import the same lockup, and the mark on the sign-in page links home.

**Two smaller fixes.** The auth provider began every page load in a loading
state and only then checked whether a token existed, so a visitor who had never
signed in painted a spinner for a frame; it now starts from what is in storage.
And `client_ip` — the Cloudflare-aware address lookup the login limiter
depends on — moved to `app/utils/net.py` rather than being reimplemented for
the second endpoint that needed it.

### Known gaps

- The landing page still ships inside the application bundle. An anonymous
  visitor downloads the dashboard's JavaScript to read a marketing page — a
  real cost that goes away when the page moves to its own host, and not worth
  code-splitting the app to fix before then.
- **The contact form has not been exercised over the wire.** It reuses the
  same Zoho SMTP path that already delivers order-placed and order-filled
  emails, so the mailer itself is known good in production — but no contact
  message has actually been sent through it, and the tests run against a fake
  sender. Worth one real submission after deploy.
- **Locally the form always fails.** `SMTP_*` lives in GitHub secrets and vars,
  not in `.env.example`, so a developer running the stack gets a 502 and the
  form's error state on every submit. That is the honest behaviour — the
  endpoint refuses to claim it sent something — but it is not a bug to chase.
- `CONTACT_EMAIL` is deliberately **not** injected by the deploy workflow. Its
  `_set_key` helper writes `KEY=` for an unset variable, which would override
  the code default with an empty string and turn every submission into a 502.
  The recipient lives in `config.py`; changing it is a code change.
- The rate limiter is in-process, so its counters reset on restart and a second
  API replica would keep its own. Same caveat the login limiter already
  carries, now also load-bearing for spam.
- The public page is web only. The mobile app opens on its login screen, which
  is right for an installed app but means the two clients no longer show the
  same first screen.
- No pricing, docs, terms or privacy policy, and no analytics on the page — so
  which sections work is currently unknown. Those belong to the separate public
  host.
- The copy has been reviewed by nobody but its author.

---

## [1.9.0] — 2026-08-27

A UX review of the whole client, and the data bug it turned up.

**Closed positions were disappearing from your record.** `execute_exit` stamps
`closed_at` the moment it sends the sell; reconciliation's open-trade query
requires `closed_at: None`, so every trade the agent sold on a SELL signal —
and every position closed with the Close button — fell outside all of it and
was never settled. They sat at `PENDING` with a P&L estimated from the limit
price, invisible to `/performance/trades`, which counts `status == CLOSED`,
while Order History showed a "pending" pill for a position sold days earlier.
Realised P&L, win rate and fee totals were computed over whatever was left.
Reconciliation now settles these against the fill log like any other closure.
The position cap and the daily-loss kill switch were never affected — both key
off `closed_at`, not status — so this was a reporting hole, not a risk one.

**A closed trade now says why it closed.** `execute_exit` knew — a fallen
score, an exit alert, your own Close button — and put it in a log line and a
push notification, then discarded it. Reconciliation later stamped
`bracket_or_manual` over everything it found flat, so a stop firing and the
agent acting on its own signal were indistinguishable. The trade record now
carries the reason and the trigger behind it, and both reach the UI: the agent
activity feed reads *"AVGO sold 12 — −$1,234.00"* with *"Score fell below the
sell threshold — scored 24/100 against the 30 that triggers a sell"* beneath
it. The Performance page stopped inferring "stop hit" by comparing the exit
price to the stop, which could contradict the recorded reason.

**The Trade screen mounted itself twice.** Its two layout containers each
rendered the full screen — 14 canvases for two charts, two live order tickets,
duplicate fetches of the chart series and the account — with one copy hidden
by CSS and still running its effects. One tree now, reordered by CSS: 7
canvases, one ticket, 36% fewer DOM nodes, and `/trading/account` down from
six requests per load to one now that all four callers share a copy.

**Mobile.** On a phone every action used to sit below three and a half screens
of reading — the order ticket 2898px down, the approvals queue 3255px, under a
banner announcing it that was not a button. The order now runs verdict → ticket
→ evidence, with the ticket on the first screen. The record tables were 46–52rem
wide in a 356px column, hiding 52–57% of every row behind a scroller with no
visible edge: the Close button, unrealised P&L, stop, target, net P&L and the
exit reason were simply not reachable. Those are cards below `md` now, and the
comparison tables on Calibration and Performance were made to fit rather than
restructured, because reading one row against the next is their whole point.
Nothing is hidden on any table at any width any more. Touch targets went from
24–28px to 36–45px. Five of twelve watchlist tickers were truncating —
`NVDA` rendered `N…` — because the signal badge won the space; none truncate now.

**Freshness.** The watchlist and the approvals queue were fetched once on mount
and never again, so a tab left open showed prices as old as the tab. They now
refresh each minute, paused while the tab is hidden and caught up the moment it
is revealed. `/analyze` is deliberately excluded — on a cache miss it runs the
whole pipeline including a paid model call — so instead the analysis states its
age and flags itself past the server's own 30-minute cache window.

**Smaller things.** The order ticket no longer overwrites a quantity you typed
while the account balance was still loading. The theme follows your OS instead
of defaulting to light, until you pick one explicitly.

**Mobile follows.** It had never refreshed anything — every screen fetched once
on mount, and a phone app is resumed rather than reloaded, so the prices you
came back to were the ones you left. Watchlist and Positions now refetch on
screen focus, on return to the foreground, and each minute while both hold.
Exit reasons render in order history, the ticker screen flags an analysis past
the server's cache window, and the quantity field no longer refills itself when
you clear it to retype.

328 tests, up from 314.

### Known gaps

- Trades closed before this release keep `exit_reason: closed_reason_unrecorded`
  — nothing recorded the cause at the time, and `bracket_or_manual` would be a
  guess dressed as a fact. Ones that settle without a priceable fill lose their
  estimated P&L rather than banking it: that estimate came from the limit we
  asked for, and on a manual close that limit is the position's own average
  cost, which would report a break-even trade every time.
- The commission extraction behind the net figures is still unverified against
  live IB data — see the 1.6.0 note. This release did not touch it.
- Four sort controls in the watchlist header are 36px rather than 44px. A 44px
  strip above a twelve-row list costs a row of real content, and sorting is a
  secondary action; the rows themselves are a full 45px.
- `PerformancePage` and `CalibrationPage` still use raw Tailwind palette
  classes (`text-red-500`, `text-amber-600`) instead of the accent tokens.
  They are legible in both themes, so this is consistency debt rather than the
  dark-mode bug the token rule exists to prevent.
- Mobile is synced on the parts that transfer — exit reasons, refresh on focus
  and foreground, the staleness badge, and the order-ticket quantity fix — and
  already followed the OS theme and shared its account fetch before this
  release. The layout work does not transfer: it was a fix for two mounted
  copies and for tables too wide for a phone, and the native client has
  neither. Its touch targets were not audited; React Native's defaults are
  generally adequate but that is an assumption, not a measurement.
- Two pre-existing type errors in the mobile project — `app/(app)/guide.tsx`
  passes `style` to a component that does not accept it, and `app/(auth)/index.tsx`
  hits a react-hook-form generic variance issue. Neither is touched here and
  neither blocks the bundle, but `tsc --noEmit` is not clean on mobile the way
  it is on web.

## [1.8.2] — 2026-08-27

Closes a gap found while reviewing the first real production dossier: the
citation filter was computing proof of its own enforcement — a count of every
uncited claim it dropped, a list of every fabricated id it caught — and then
throwing that proof away. It lived inside `report` under `_dropped_uncited`
and `_invented_citations`, keys `ResearchReport` has no field for, so Pydantic
silently stripped them at the API boundary. Nothing short of a log line or the
raw Mongo document could tell whether a clean-looking report had actually been
checked, or the check had simply found nothing to catch on this run.

`citation_audit` is now a first-class field on the dossier — present whenever
a report was produced, `None` only when there was none to filter — carrying
`dropped` (a per-field count) and `invented` (the fabricated ids themselves).
`report` no longer carries any underscore-prefixed keys.

Data-contract change only: no UI renders this yet, and none of the enforcement
behaviour changed — every uncited or fabricated claim was already being
removed before this release. This just makes that removal visible instead of
asserted. 314 tests, up from 309.

## [1.8.1] — 2026-08-27

Fixes a bug that made every deep-research dossier fail in production on the
first real run: `output_config.format.schema` rejects `minimum`/`maximum` on
an integer field outright — a 400, not a silent no-op. Three of the five
research agents (fundamentals, risk, the synthesiser) declared exactly that
shape for their 0–100 score and failed identically the moment real API keys
were in place; the other two, with no bounded-integer field, ran fine, which
is what made the failure look selective rather than systemic. The bound now
lives in Python — both consumers already clamped and coerced defensively — and
26 new tests statically lint every agent schema against the documented
unsupported-constructs list, so this class of bug fails in CI, not against a
live call that costs money to find out.

Also: a synthesiser failure no longer collapses into an unexplained `report:
null`. It is recorded with the reason and reaches the API response as
`synthesis_error`, distinguished from "no specialist produced anything to
merge" — the same split `agents_skipped` already draws from a specialist
failure. Both dossier panels render the distinction.

## [1.8.0] — 2026-08-27

Research becomes a thing the system actually does, rather than a paragraph it
writes. Four scoped analysts work a ticker in parallel over one sourced
evidence ledger, a fifth merges them, and **every claim that survives cites a
dated fact** — because anything that did not is deleted before the report is
stored.

### Added

- **Deep research dossiers, on demand and once a day.** `POST /research/{ticker}`
  builds one; `GET` reads the last one. It is a second, slower path that never
  touches the 5-minute pipeline, and it is off until you set
  `RESEARCH_AGENTS_ENABLED=true`.
- **Four agents, run at once, one of them adversarial.** Fundamentals,
  Technical and News each see only the evidence they are qualified to read. The
  Risk agent sees everything **except the bull case**, and that omission is the
  design: given a thesis, a critic argues against that thesis and inherits its
  framing. The old single analyst wrote both sides in one pass from the same
  inputs and produced a bear case shaped to fit its own bull case. The
  synthesiser must now **address or carry every risk the risk agent raised** —
  dismissed risks appear under *Risks raised and answered*, so dropping one is
  visible as a decision rather than a silence.
- **Six 0–100 dimension scores** — business quality, financial strength,
  growth, valuation, technical, risk. Five are computed in Python, not asked of
  a model, because a headline number that cannot be reproduced or regression
  tested is decoration. Only business quality is model-judged, and it is
  labelled *judged* in the UI. Higher is better on all six, risk included,
  where it means safer.
- **Conviction is 0–100 and anchored.** It was `HIGH|MEDIUM|LOW` mapped to a
  hardcoded `{0.85, 0.55, 0.25}`. It is now blended from the scored dimensions,
  and the model may move it 15 points either way — a departure it has to
  explain. Both numbers are stored, so a persistent gap between the arithmetic
  and the narrative is visible instead of hidden inside one score.
- **An evidence ledger, and a per-claim source list.** Every fact enters with an
  id, a value, a source and a date; the report cites ids; the UI shows the
  ledger with links. **Uncited sentences are deleted, and a fabricated citation
  is deleted and recorded** — an invented `[F99]` is more dangerous than no
  citation, because it survives exactly the check a reader would make.
- **The model now knows what the company does.** Alpha Vantage's business
  description was arriving on the same call as the P/E and being discarded
  during parsing on every refresh. Sector, industry, country, share count,
  beta, book value, forward P/E, EV/EBITDA, EV/revenue, operating margin, gross
  margin, ROA and dividend yield were in that same response and equally unused.
  No new API call — the payload was always paid for.
- **Ten years of financial statements, kept.** The old code fetched two annual
  periods, used the second for a single revenue delta, and `replace_one`'d the
  document on every refresh — so a decade of filings could pass through the
  process and leave nothing behind. Filings now accumulate in
  `financial_statements`, which makes revenue and EPS CAGRs, margin trends and
  share-count dilution computable for the first time. Quarterly statements are
  pulled too, so "latest results" is not a year-old annual.
- **Estimate versus actual, and a real earnings calendar.** A new Alpha Vantage
  `EARNINGS` call supplies reported EPS against consensus by quarter, a
  beat-rate over the last eight settled quarters, and the next scheduled report
  date. This is the only expectation in the system — everything else describes
  what happened, never what was forecast.
- **Earnings proximity finally feeds the catalyst score.** `next_earnings_date`
  had been read by the analyst prompt and rendered as `N/A` on every run since
  yfinance was dropped, because nothing wrote it. It is now an **additive bonus,
  capped at +0.10, not a fourth weighted component** — as a component its
  absence would cost coverage, and coverage is a penalty, so every ticker past
  the Alpha Vantage daily cap would have scored on a narrower range than one
  inside it for a reason unrelated to the company.
- **An agent whose evidence holds no facts about the company is not called.**
  Found by running a real AVGO dossier on a cold cache: with no fundamentals
  provider key, the fundamentals agent was sent exactly two items — "no
  historical range collected" and "no earnings history collected" — and paid
  Opus rates for a paragraph restating them. Evidence is now marked as either a
  fact about the company or a fact about *our data* (a declared absence, a
  methodological caveat); an agent is skipped when its slice holds none of the
  former. On that same AVGO ledger this drops the run from four calls to three.

  A skip and a failure are reported separately, and read differently: a failure
  means the call broke and the dossier is incomplete; a skip means there was
  nothing to assess, so the questions that agent would have answered are open
  rather than neutral. The synthesiser is told which it is, and the meta items
  still reach every agent that does run — knowing the boundary of the evidence
  is what stops one reasoning past it.

- **A research veto on entries, off by default.** Research can block a BUY. It
  can never create one, enlarge one, or reach an exit — the same asymmetry that
  exempts SELL from every other delay here, because refusing to buy costs an
  opportunity and refusing to sell costs money. A missing, stale, undated or
  unreadable dossier **never vetoes**: a guard that halts all buying when a cron
  job misfires is a worse failure than one that occasionally lets a trade
  through unchecked.

### Changed

- **Headlines reach the model with their publisher, date and link.** All three
  were already stored on every article and all three were stripped before the
  prompt was built, so the analyst could reference "recent news" but was
  structurally incapable of attributing a claim to anything.
- **Free cash flow and debt/equity stop lying about their basis.** Where a
  filing reports capital expenditure, free cash flow is now free cash flow;
  where it does not, the operating-cash-flow proxy is labelled as such in the
  evidence text rather than in a code comment nobody downstream can read. Same
  for leverage: a filed long-term-debt line gives a true ratio, and the
  halved-total-liabilities approximation is named where it is still used — the
  two differ by roughly a factor of two, and the dimension scorer anchors them
  differently so a company is not penalised for what its filing omitted.
- **Return on invested capital exists.** The fundamental picture had return on
  equity but nothing accounting for how much borrowed money produced the
  return.
- **"Where the inputs come from" is accurate again**, on web and mobile. It
  claimed fundamentals came from Yahoo Finance months after that path was
  removed, and described insider activity as a 90-day window when the code
  applies no date filter at all. Rows that are genuinely unavailable —
  institutional ownership, transcripts, a real peer screen — now say so.
- The Alpha Vantage daily budget is spent by **counting calls rather than list
  position**, now that a ticker can cost one call or two.

### Known gaps

- **No earnings-call transcripts and no management guidance.** No configured
  provider carries them, so the earnings analysis stops at estimates versus
  actuals. The spec this was built against asks for *what management expected*
  and *what changed*; those two questions are not answered, and the earnings
  evidence says so out loud rather than letting an agent fill the silence.
- **No institutional ownership or 13F data.** Absent entirely, from every
  provider configured here.
- **Peers are not a screen.** They are other names on your own watchlist sharing
  a sector or industry, plus a hand-written map of about six industries. Useful,
  and labelled as a convenience wherever it is shown.
- **Citations are provider-level, not document-level.** "Alpha Vantage OVERVIEW,
  as of 2026-08-26", never a filing page. Adding SEC EDGAR — free, no key, ten
  years of XBRL financials plus 10-K risk factors — would close most of this and
  most of the two gaps above; it was deliberately out of scope for this round.
- **Insider data is unchanged and still weak**: yfinance, the most recent ~20
  filed transactions, no date window, no dollar weighting, no filer role. Short
  interest is still usually unavailable from the production host. Both now carry
  their caveats into the evidence so an agent cannot read absence as a signal,
  but the underlying data is no better than it was.
- **The historical valuation band is a weaker statement than it sounds.** Price
  history is still capped at 90 days, so the range applies *today's* price to
  each past year's EPS. It shows how the current price would have been valued
  against past earnings, not what the multiple actually was at the time — and
  the caveat is in the ledger beside the number.
- **Parallel agents forfeit the cross-agent prompt cache.** A cache entry is
  only readable once the first response has started, so four concurrent calls
  all miss it; only the synthesiser gets the read. The wall-clock saving was
  judged worth more. Expect `cache_read_input_tokens` to be zero on the four
  specialists and non-zero on the fifth — that is correct, not a misplaced
  breakpoint.
- **None of this has been run against a live model or a real database.** The
  orchestration is covered by 76 new tests against a fake client — fan-out
  concurrency, per-agent failure, citation filtering, conviction clamping, the
  veto's fail-open paths — but no dossier has been built with real API keys, and
  the statement-accumulation path has not been exercised against a real MongoDB.
  Prompt quality in particular is unmeasured: the agents are known to produce
  the right *shape*, and nothing yet says whether they produce good analysis.
- **The research UI was reviewed by eye and type-checked, not run.** `tsc -b`,
  `vite build` and `lint:a11y` are clean, and none of them can see a layout. The
  mobile panel has not been rendered on a simulator or a device.
- **`tsc --noEmit` in `mobile/` reports two errors** — in `guide.tsx` and the
  auth screen — and both predate this change. They are unrelated to research and
  were not fixed here, but a clean mobile typecheck is not something this
  release can claim.
- **Cost has not been measured.** Five model calls per dossier against a
  ~29-ticker watchlist is roughly 150 calls a day with the daily job on. Both
  the job and the whole feature are off by default for that reason.

---

## [1.7.0] — 2026-08-26

A full UI redesign, from a Claude Design handoff. Ten routes become three
destinations — **Trade**, **Positions**, **Settings** — without retiring a
single feature.

### Changed

- **Trade replaces the Dashboard, the Ticker page, Search, and the buy flow.**
  Three columns: the watchlist on the left, the selected ticker in the middle,
  the order ticket on the right. These were four screens answering one
  question — what should I do about this name, and why — and answering it used
  to cost two navigations and lose the list you were working through. Picking
  a row navigates, so every selection is still deep-linkable and Back walks the
  names you looked at.
- **Every verdict now leads with a plain-English "Why" line**, above the
  numbers rather than buried under them. It prefers the model's own thesis and
  otherwise derives a sentence from the gate the engine actually applied. It
  never invents a rationale.
- **Positions merges Holdings and Orders.** They were split along a line that
  meant nothing to a reader: one asked the broker what it holds, the other
  asked our records what we sent, and "am I up or down" needed both. Open
  positions now carry a **Source** column — Agent, Approved, or You.
- **Closed trades show gross, fees, and net side by side.** Where the venue
  never reported a complete fee total the Net cell is a dash and a banner says
  how many trades are affected — they are excluded from the net figures rather
  than folded in at zero, which would understate cost in one direction every
  time.
- **Settings replaces Profile, and autonomy leads it.** The old page stacked
  seven cards with the autonomy ladder below alert webhooks and the risk limits
  behind a master toggle. Risk limits now carry live notes computed from your
  real equity and watchlist: "about $4,227 per position", "6 positions commit
  at most 48% of equity", "3 of your 6 watched tickers score at or above this".
- **Switching order routing to live money asks for confirmation**, and says
  plainly that live must also be enabled server-side or the orders are refused.
- **⌘K searches screens and actions as well as tickers.** With three tabs in
  the header this is the flat index of everything the app can do.
- **The chart gains a 1M range and dashed stop/target guides.** They are drawn
  as price lines rather than data series, so a distant stop cannot rescale the
  pane and flatten the price action into a band.
- **Mobile moves to the same three tabs** and merges Holdings into Positions.
  Holdings there now load on arrival rather than on demand — a screen called
  Positions that shows nothing until you press a button reads as broken.

### Added

- **Mobile has a dark theme.** Every screen read from its own hardcoded
  light-only `C` block, so a theme switch had nothing to act on. Colours now
  come from one palette module mirroring the web `:root` / `.dark` tokens, and
  the choice is a Light/Dark control in Settings. It persists across restarts
  and the first frame waits for the stored value, so choosing dark no longer
  means a white flash on every cold start.
- **Mobile shows the logo and product name on every screen.** Past the login
  page the app previously identified itself only by its tab bar. The mark is
  the same rising-arrow geometry as the web `IconMark`, drawn in
  `react-native-svg` from the same viewBox and stroke weights.
- **Broker balances are on the mobile Trade screen.** Net liquidation sits in a
  badge in the header, and available / in-trade / unrealised in a strip above
  the watchlist — the figures web keeps in its account bar. Deciding whether to
  buy no longer means leaving the screen that is asking you to.
- Two alert toggles the settings type already carried but no screen exposed:
  **order submitted** and **fills and closes**.
- The watchlist rail marks a **timing trigger with a round dot** and a **held
  position with a square**. Different shapes rather than two colours of one
  shape: one is an opinion and the other is a fact, and colour alone would not
  separate them for a red-green colourblind reader.

### Fixed

- **The same order could be labelled "Agent" on one screen and counted as
  manual on another.** Order history classified any `signal_type` that was not
  `MANUAL` or `PROPOSAL_APPROVED` as agent-placed, while the backend counts
  only `BUY`/`SELL`/`EXIT_ALERT` as agent. Mobile had a third copy with the
  same defect. Both clients now share a helper that mirrors
  `backend/app/routes/performance.py`.
- **Approving a live-money proposal on the Trade screen requires typing the
  ticker back**, matching the order ticket. Approving a proposal *is* placing
  an order; the agent having chosen the name does not make it a smaller
  commitment.
- **The header pill, the order ticket and Settings can no longer disagree about
  paper versus live.** All three read one shared copy of the auto-trade
  document; previously each fetched its own, so flipping to live in Settings
  left a header still reading PAPER and a ticket still willing to submit
  without confirmation.
- **Every mobile row, button and pill built with a `Pressable` style function
  was rendering unstyled.** `babel-preset-expo` was configured with
  `jsxImportSource: 'nativewind'`, which routed all JSX through NativeWind's
  runtime and dropped the function form of `style`. The watchlist collapsed
  into a vertical stack with no padding, `HOLD`/`SELL` wrapped mid-word, and
  the ticker screen's Refresh and Share buttons lost their borders. NativeWind
  was reaching one component, which was itself imported nowhere; the transform
  and that dead component are both gone. This predates the redesign — it was
  live on `main` and had never been seen, because the mobile app had never been
  run.
- **The mobile watchlist's Signal column was too narrow for its own badges.**
  42pt against a `SELL`/`HOLD` pill needing ~47pt, so both wrapped to two
  lines. The header and the row now share one constant sized to the longest
  badge, and an over-long symbol truncates instead of growing the row.
- **The post-login redirect no longer typechecks against a route that does not
  exist.** `router.replace('/(app)/')` — with the trailing slash — fell out of
  expo-router's generated route union when the screens were renamed.
- One jsx-a11y suppression removed — the Settings restructure made the label
  association real rather than promised in a comment. One suppression remains
  in the tree, with its reason written beside it.

### Deliberate departures from the handoff

- **The autonomy pill opens a menu instead of cycling on click.** One of those
  three transitions hands an unattended process permission to spend money, and
  a blind cycle put it one mis-click away from the theme toggle. Climbing to
  AUTO confirms; stepping down never does.
- **The wordmark uses `--color-fg`, not the specified `#281F13`.** That literal
  is the light-mode ink colour and would be near-invisible on the dark surface.
- **The chart stays `lightweight-charts`** rather than becoming a flat SVG
  line. Candles, volume and SMA-50 are existing functionality.
- **Signal-weight sliders do not live-rescore the watchlist.** Scoring is
  server-side; the copy says weights apply at the next scoring rather than
  promising what the prototype mocked.
- **There is no Day P&L tile.** The broker summary carries no day-open figure,
  and a "day" number derived from something else would be a different quantity
  wearing the same label.

### Known gaps

- **The web screens were reviewed by eye against a mock API and looked right;
  nothing more systematic than that was done.** No responsive sweep across
  breakpoints, no browser other than Chrome, and there are still no automated
  UI tests in this project — `tsc -b`, `vite build` and `lint:a11y` are the
  whole safety net, and none of them can see a layout. A regression here would
  reach production unnoticed.
- **The redesign has not been run against the real backend.** The review used a
  local mock, which returns well-formed data for every endpoint. Empty
  watchlists, a disconnected broker, partially-scored tickers and analyst
  responses missing optional fields have been coded for but not observed.
- **Mobile was run, but only in the simulator, only on iOS, and only against
  the mock.** Trade, Positions and Settings were rendered on an iPhone 17 Pro
  simulator in both themes and the screens above were seen working. No physical
  device, no Android, and no pass over Performance, Calibration or the Guide,
  which keep their 1.6 visual design inside a themed shell. Running it at all
  is what surfaced the NativeWind defect above, which had been shipping
  unnoticed — treat the untested surfaces accordingly.
- **Mobile is an IA and palette change, not a full visual redesign.** The three
  tabs, the Positions merge, the theme and the brand header landed, but the
  screens keep their previous type scale and spacing, so web and mobile now
  agree on structure and colour but not on typography.
- **Mobile toasts stay dark in both themes.** They were already a dark overlay
  and were left that way; against the dark surface they separate by tint alone.
- **"Agent activity" on the Trade screen is derived from order records**, not a
  real event feed — there is no agent-log endpoint. It shows orders, so a guard
  that declined to act leaves no trace there.
- **Performance and Calibration keep their old visual design.** They were kept
  reachable rather than restyled; they will look like 1.6 inside a 1.7 shell.
- The company name is not shown in the ticker header. `AnalyzeResponse` has no
  name field and inventing one was not worth a lookup round-trip.
- Fee-drag verification from 1.6.0 is still outstanding — the closed-trades
  table now makes `net_unknown` visible, which should make checking it easier,
  but it has not been checked.

---

## [1.6.3] — 2026-08-25

### Fixed

- **`npm run build` now actually type-checks**, closing the gap noted in
  1.6.2. The root `tsconfig.json` is reference-only (`"files": []` plus
  `references`), which needs `tsc -b` to descend into the referenced
  projects; the build script ran plain `tsc`, which exits clean regardless of
  what the code says, so CI had never once caught a type error. Getting there
  meant actually fixing what `tsc -b` found: `frontend/src/vite-env.d.ts` was
  missing outright (that's the file that types `import.meta.env`), and
  `TradeRecord` was missing `filled_qty`, `stop_loss`, and `take_profit` —
  present on the backend's response, just never declared on the frontend
  type, despite the Positions table reading all three off it.

### Changed

- **Order history's column filters are funnel icons in the header now, not a
  permanent row underneath it.** The row doubled every header's height and
  read as clutter on the five columns nobody was filtering at any given
  moment. Click the funnel next to a column to open just that column's
  inputs; the icon fills solid once a filter is set, so an active filter is
  visible with the popover closed. Panels render through a portal to
  `document.body` with `position: fixed`, computed from the funnel button's
  own screen position — the table's horizontal scrollbar also makes the
  browser compute `overflow-y: auto` on that container per the CSS overflow
  spec, so an in-flow popover would get clipped by the very box it needs to
  escape.

### Known gaps

- **Web only.** This was a request against `OrdersPage.tsx` specifically;
  mobile's order history is unchanged and has neither the status tabs nor the
  column filters.
- Filter popovers don't move focus in on open or trap it there; Escape
  returns focus to the funnel that opened them, but Tab doesn't land inside
  the panel automatically.
- Still no live click-through, for the same reason as 1.6.2 — Chrome's
  extension blocks `localhost` by site permission. Verified via `tsc -b`,
  `lint:a11y`, and a manual trace of the filter predicate.
- Unchanged from 1.6.1/1.6.2: the API still emits naive datetimes and both
  clients compensate in `parseTimestamp`; the analyst "Generated …" stamp is
  still device-local; none of this has a test.

---

## [1.6.2] — 2026-08-25

### Added

- **Order history is a tab per status, with Filled the default.** The ten
  possible statuses (see `TradeStatus` in the backend) span three different
  questions — what the agent actually filled, what's still awaiting you as a
  proposal, what a risk guard refused — and one long sorted list buried that
  distinction under whatever sorted first. A tab only appears once an order
  reaches that status, so a fresh account isn't shown nine empty tabs; Filled
  is the exception and always shows, since it's the one that answers "what did
  the agent do".
- **Every column in order history filters.** Date range, ticker substring,
  side, quantity range, price range, gain/loss, and source (Agent / Approved /
  You) — Status doesn't get its own filter because the tab you're on already
  is one. Filters persist across tab switches; a "Clear filters" control
  appears once any are set.

### Known gaps

- **`npm run build`'s `tsc` step has been silently checking nothing.** The
  root `tsconfig.json` is reference-only (`"files": []` plus `references`),
  which needs `tsc -b` to actually descend into the referenced projects; plain
  `tsc` (what the build script and this session's earlier verification both
  ran) exits clean regardless of what the code says. Running it correctly
  (`tsc -b --force`) turned up two **pre-existing** issues this change did not
  introduce: `filled_qty`, `stop_loss`, and `take_profit` aren't declared on
  `TradeRecord` but are read off it in the Positions table, and
  `import.meta.env` isn't typed in `lib/api.ts`. Neither is fixed here, and CI
  has not actually been catching type errors — the build script should move to
  `tsc -b`.
- **No live click-through.** Chrome's extension blocked `localhost` by site
  permission, so the tabs and filters were verified by type-checking against
  the real `TradeRecord` shape, `lint:a11y`, and tracing the filter predicate
  by hand against fixtures covering all ten statuses, the UTC-day-boundary
  case, gains/losses, and all three sources — not by clicking the page.
- Unchanged from 1.6.1: the API still emits naive datetimes and both clients
  compensate in `parseTimestamp`; the analyst "Generated …" stamp on both
  ticker pages is still device-local; none of the timestamp handling has a
  test.

---

## [1.6.1] — 2026-08-25

### Fixed

- **Order history shows the time of an order, not just the day.** The agent can
  place several orders for one ticker in a session — an entry and its scale-in
  adds — and a column that only said "8/25" could not tell them apart. Web
  shows the date with the clock time beneath it; mobile appends it to the order
  line.

- **Timestamps are no longer shifted by the viewer's UTC offset.** The backend
  writes UTC but MongoDB returns datetimes tz-naive, so the JSON carries no
  offset and the browser was reading `18:04` as *local* time. Date-only
  displays mostly hid this; a clock time would not have. Parsing now assumes
  UTC when no zone is given (`parseTimestamp` in each client's `lib/format`),
  which also fixes relative ages west of UTC — a proposal placed an hour ago
  read as "just now" because its timestamp parsed into the future.

- **Dates and times display in Toronto time on both clients**, not in whatever
  zone the device happens to be in. The zone belongs to the record, not to the
  reader: an order filled at 01:30 UTC belongs to the 25th's session and must
  not be dated the 26th because the laptop travelled. Toronto is US market
  time, so 9:31 AM is one minute into the open wherever it is read. Columns
  showing a clock time are labelled ET; `DISPLAY_TZ` in `lib/format` is the one
  place it is set.

- **Signal history dates on the Performance page** used a private, unfixed copy
  of the date formatter on each client and had the same UTC-shift — an evening
  signal could be filed under the previous day. Both now use the shared one.

### Known gaps

- **The root cause is still there.** The Mongo client is not `tz_aware`, so the
  API keeps emitting datetimes with no offset and both clients compensate by
  assuming UTC. Anything that reads these timestamps without going through
  `parseTimestamp` — a new page, a script, a third client — inherits the old
  bug. Setting `tz_aware=True` on the client in `db.py` is the real fix.
- **Two places still render in device-local time.** The analyst's "Generated
  …" stamp on the web and mobile ticker pages uses a raw `toLocaleString()`,
  so it can disagree with every other timestamp in the app by the viewer's UTC
  offset. The Holdings "As of …" line is also device-local, but that one is a
  browser-side fetch time rather than a server record, so it is arguably right.
- **None of this is covered by a test.** The formatters were verified by hand
  against a non-ET machine zone across naive/zoned/DST inputs; there is no
  check that stops the next edit from regressing it.
- Unchanged from 1.6.0: IB commission extraction is still unverified against a
  real fill, so `net_unknown` is the number to watch on the Performance page.

---

## [1.6.0] — 2026-08-25

### Added

- **Realised performance is now reported net of commission.** Gross P&L is what
  the position did; net is what reached the account, and on a small account the
  two are far apart — a fixed broker ticket costs roughly 0.5% of a $200 round
  trip and 0.005% of a $20,000 one. A strategy can look profitable gross and
  lose money net, and until now nothing in the app would have shown that.
  - `/performance/trades` gains `realised_pnl_net`, `commission_paid`,
    `commission_drag` (fees as a share of the gross P&L they were charged
    against) and `win_rate_net`, per bucket, alongside the gross figures the
    endpoint already returned. Buckets are still never pooled.
  - **`wins_lost_to_fees`** counts trades that were profitable before
    commission and not after. That is the number to set the sizing thresholds
    from — the first honest read on whether `MIN_ADD_FRACTION`, the 2% dip and
    the two-add cap are anywhere near right.
  - The Performance page leads with net where it is known and labels it, shows
    gross beneath, and gives each closed trade its own fee and add count.
  - Commission is the venue's real figure, taken from IB's execution reports —
    not a modelled estimate. IB paper simulates commissions, so the paper
    record produces usable numbers.

- **Trades record what they actually cost.** `commission_paid` accrues across
  every ticket the position paid: the entry, each scale-in add, and the exit.
  - Accrual is idempotent by execution id. Reconcile re-reads a 24-hour fill
    window every two minutes, so without that the fee total would climb on its
    own for as long as the app stayed up, fastest on the busiest trades.
  - IB delivers commission in a report separate from the execution and can lag
    it by a beat. A trade that closes in that gap is picked up by a backfill
    pass over the last 24 hours rather than being left permanently unpriced.

### Known gaps

- **Trades closed before this release can never be netted.** IB only serves the
  current session's executions, so there is no way to recover their commissions.
  They are counted as `net_unknown` and excluded from every net figure rather
  than folded in at zero — zero would understate cost in one direction every
  time, which is worse than an honest gap. Expect the net view to be thin for a
  few days.
- **A missing commission suppresses the net figure for that trade entirely.**
  `commission_complete` goes false if any single execution never reported, and
  the trade then shows gross only. This is deliberate — a partial fee total
  flatters — but it means one bad execution report hides an otherwise good
  trade from the net numbers.
- **Mobile does not show any of this.** The mobile Performance screen renders
  signal accuracy only and has never had a realised-trades section, so there is
  nothing there to extend. This is not a new parity gap, but it is now a
  larger one.
- **Multi-currency is not handled.** `commission_currency` is recorded but
  never converted; a non-USD commission would be summed as though it were USD.
  Everything traded so far is USD-denominated.
- **The thresholds are still not fitted.** This release makes the evidence
  visible; it does not use it. `MIN_ADD_FRACTION`, `SCALE_IN_DIP_PCT` and
  `MAX_SCALE_INS` remain the judgement calls made in 1.5.1.

---

## [1.5.1] — 2026-08-25

### Fixed

- **Scaling in no longer churns out one- and two-share orders.** On the morning
  of 25 Aug 2026 a single NVDA position produced eight orders, seven of them
  for one or two shares. Commission is charged per order, so those seven cost
  nearly as much in fees as a full-size trade and bought almost nothing. No
  risk guard was breached — the guards bounded position *size* and never
  bounded order size or order count. Four changes, each closing one part of it:
  - **An add now has to be a real dip.** The only price condition on adding
    was "above the stop", which is a reason not to panic, not a reason to buy.
    Meanwhile a standing `BUY` verdict re-runs the entry path every 5-minute
    pipeline cycle, so a ticker that simply stayed BUY bought more of itself
    all morning, into strength. An add now requires the price to be at least
    `SCALE_IN_DIP_PCT` (default 2%) below the position's blended cost. Because
    blended cost falls after each add, successive adds space themselves out.
  - **Adds are capped per position.** `MAX_SCALE_INS` (default 2). The
    `scale_ins` counter had been written since scale-in shipped and never read.
  - **An add must move the position by at least `MIN_ADD_FRACTION` (default
    25%) of what is already held.** Two shares onto 450 is not worth a ticket
    at any account size. This is a fraction rather than a dollar figure on
    purpose: it scales with the account instead of needing to be re-tuned, and
    it does not silence a small account the way a flat floor would. An opening
    entry has no such limit — refuse one and there is no position at all, so
    the commission is simply the cost of participating; an add always has the
    alternative of doing nothing, so it has to earn its ticket.
  - `MIN_ORDER_NOTIONAL` is an absolute floor across every entry path,
    **disabled by default**. Worth switching on once `position_size_pct` of
    the account clears it comfortably. Neither limit rounds an order *up* to
    clear itself — that would let a fee rule override the position cap — and
    **exits are subject to neither**: you must always be able to close a
    position, at any size.
  - **The position cap stopped drifting.** It is `equity × position_size_pct`,
    and equity was read live. A position sitting at its cap gained a sliver of
    fresh room every time the account ticked up, and the 5-minute retry loop
    spent it immediately — the actual engine of the seven small orders. Equity
    is now frozen at the opening entry and stored on the position, so a cap
    cannot move under a position that is already full. Positions opened before
    this release fall back to live equity and are unaffected.
  - Sizing rounds down to zero instead of flooring at one share, so the
    existing "quantity < 1" refusal can actually fire.
  - Repeated refusals collapse to one history row again: skip reasons quote
    live prices, and comparing the rendered sentences made one standing
    condition look new every cycle.

- **Orders now notify on WhatsApp and Slack, not just email.** Trades were the
  only event that emailed and nothing else — signal flips, gateway outages and
  the daily digest all reached chat, so the notification that matters most
  (money moved) arrived on the slowest channel. `notify_on_trade` now gates all
  three channels together; it was never meant to be an email-only switch, and
  the WhatsApp and Slack credentials are the same ones the signal alerts
  already use. Nothing to configure if WhatsApp is already set up.
  - The chat message carries the same numbers as the email — side, quantity,
    limit, notional, stop and target with their distances and reward:risk —
    led by PAPER/LIVE, because that is the one thing that has to be legible at
    a glance on a phone.
  - Channels dispatch independently: a dead SMTP host no longer swallows the
    WhatsApp message.

- **A dead WhatsApp API key looked exactly like a delivered message.**
  CallMeBot answers an invalid key with `203 Non-Authoritative Information` and
  puts the real outcome in the HTML body. The check was `if status != 200:
  warn`, so it missed every genuine failure *and* would have cried wolf on
  successes — 203 is also what a delivered message returns. The body is now
  what gets inspected.
  - **Send test reports the truth.** It previously appended "whatsapp" to the
    success list unconditionally, so the button confirmed a channel that was
    not working. It now sends through the low-level sender and surfaces
    CallMeBot's actual refusal, alongside the SMTP reason it already showed.
  - A half-configured channel (number but no key, or the reverse) is reported
    as incomplete rather than skipped in silence.
  - Failure reasons no longer echo the alert text back into logs or the UI —
    CallMeBot repeats the whole outgoing message before saying what went wrong.
    Logged phone numbers are masked to their last four digits.

### Added

- **A second notification when the order actually fills.** Submission and
  execution are different events and only one of them involves a price you
  really paid, so both are now sent:
  - *Order placed* — what was asked for, at what limit. Reworded: it used to
    say "Bought 57 HXL", which was not true until something filled.
  - *Filled* — the executed price, the cash it cost, and how it compared with
    your limit. The comparison is unsigned with the direction in words
    ("$0.02 better"), because a minus sign next to "better" makes a reader stop
    and decode it.
  - *Closed* — realised P&L as the headline, since that is the only question an
    exit answers. A close that cannot be priced says so instead of reporting
    zero.
  - Partial fills are announced once, with how much is still working. A
    scale-in add is announced as the shares *added*, not the new total.
  - `notify_on_fill` gates these, separately from `notify_on_trade`. Both
    default on. Separate because "tell me when it happened, not when you tried"
    is a reasonable preference that one switch could not express.
  - Each message is claimed atomically before sending, so overlapping
    reconciler passes cannot announce the same fill twice.

### Known gaps

- **Fill notifications are as timely as the reconciler**, which runs every two
  minutes — so a fill is reported up to two minutes late. Nothing pushes fills
  to us; this is polling, not a stream.
- **A position closed on an earlier day cannot be priced.** IB only serves
  same-session executions, so those arrive as "Closed HXL" with no P&L rather
  than a fabricated number.
- **`notify_on_trade`, `notify_on_fill` and `trade_email` are not on the
  profile screen.** All three exist in the API, default sensibly, and survive a
  save untouched, but neither client renders a control — changing them needs an
  API call.
- **UNRECONCILED trades notify nothing.** A record the broker has no memory of
  is closed silently; there is genuinely nothing truthful to say about it, but
  it does mean a vanished position is only visible in the logs.
- **Small opening entries are deliberately unlimited, and on a small account
  they will be mostly fee.** A $200 entry pays the same commission as a
  $20,000 one — roughly 0.5% round-trip at IBKR's minimum versus 0.005%. That
  is accepted for now because the alternative is an agent that refuses every
  order and looks broken, but it is a real cost and it does not show up
  anywhere in the performance figures yet. Revisit `MIN_ORDER_NOTIONAL` as the
  account grows.
- **Nothing verifies any of these numbers against realised fee drag.** The 2%
  dip, the two-add cap and the 25% add fraction were chosen as reasonable, not
  fitted — there is no report that shows commission paid against return per
  position, so we cannot say whether they are right. `/calibration` scores
  signals, not costs, and `/performance/trades` reports gross.
- **The frozen size basis never refreshes.** A position held through a large
  genuine change in account size keeps sizing against the equity it was opened
  with. That is the intended trade — a fixed denominator is the whole point —
  but it means a deliberate deposit does not open room in an existing position
  until it is closed and re-entered.

---

## [1.5.0] — 2026-08-24

You can now add to a position you already hold. Holding a stock was never a
reason to refuse buying more of it — the refusal was standing in for a feature
that did not exist.

### Added

- **Scale-in.** A `BUY` on a ticker you already hold adds to that position
  instead of being skipped. One position record, one set of protective orders,
  sized to the whole holding. Under MANUAL/SEMI_AUTO an add is proposed like any
  other entry. `ENABLE_SCALE_IN=false` restores the old refusal.
  - **Sizing caps the position, not the order.** `position_size_pct` used to
    limit each order, which limited nothing: three 5% adds made a 15% position.
    Room is measured on **cost basis**, deliberately — on market value a falling
    position frees room as it falls, so the agent would buy more of a loser
    precisely as it got worse.
  - **An add below the stop is refused.** The stop is the level at which the
    thesis is declared wrong; buying more underneath it is overriding the exit
    you already chose.
  - **Protection is never weakened.** The combined stop is the higher of what
    the new blended cost implies and what is already working, so averaging down
    cannot loosen the stop on the shares bought first. If no valid pair exists,
    the add is refused and the existing bracket is left alone.
- **`place_protective_orders`** on both broker adapters — a stop and target on
  shares already held, with no entry attached (IB: OCA pair, `ocaType 1`;
  Alpaca: native OCO). A bracket can only hang off an entry, so without this
  "the position is unprotected" was a state the system could detect and not fix.
- **The reconciler re-protects an uncovered position.** Any filled holding the
  venue reports with no working order gets its stop and target back within two
  minutes. Scale-in is one way to arrive there; a rolled gateway session or a
  leg cancelled by hand are others. It never invents a level — a record with no
  stored stop is logged for a human instead.
- **`runbooks/scale-in-paper-verification.md`** — the paper-account check,
  including the partial-fill case and the leg quantities to read in TWS.

### Fixed

- **Closing a scaled position sold only the original shares.** `execute_exit`
  sizes from the trade record, which understates the holding while an add is
  still settling — the close sold the original 450, marked the record closed,
  and orphaned the 100 just added.

### Known gaps

- **Not yet exercised against the paper account.** The logic is covered by 31
  tests and the ib_async call surface was verified against the installed
  library, but no order from this code has reached IB. The gateway lives inside
  the VPS network and is not reachable from a development machine. Run the
  runbook before this touches funded money — step 4 (partial fill) and step 6
  (the healer) are the two that cannot be reasoned about from here.
- **A gap between fill and consolidation.** The add goes out unbracketed and the
  original bracket is left working, so the *added* shares carry no stop until
  the next reconciliation pass — up to two minutes. This is deliberate: the
  alternative (cancel first, or size the legs to the intended total) leaves the
  whole holding naked while the add rests, or over-covers a partial fill and
  sells into a short. Under-protection for two minutes is the cheaper failure,
  but it is a failure.
- **A resting add can buy back into a position that just stopped out.** The
  reconciler cancels the add and logs `scale_in_abandoned_position_closed`, but
  only on its next pass — a fill inside that window opens a small unprotected
  position, which the healer then brackets.
- Adds are refused while the previous one is still working, so a fast-moving
  thesis can only be acted on once per reconciliation cycle.
- Neither client has a scale-in affordance: pressing Buy on a held ticker now
  adds, but nothing in the UI says so before you press it. The order ticket
  still reads as though it were opening a position.

---

## [1.4.0] — 2026-08-24

A signal only means something if it stops changing. HXL sent eight alerts in
sixty-five minutes — BUY, HOLD, BUY, HOLD — with the score reported as 61 and
confidence as 55% in every one of them. Nothing about the stock had changed.
This release makes a verdict earn its way to your phone.

### Fixed

- **The AI analyst cache never worked.** `analyst_used` was set on the
  in-memory signal but never written to the document, and the cache check read
  it back from the database. Every ticker therefore looked like it had no
  analyst signal, on every cycle: Claude was re-run every five minutes per
  ticker instead of hourly, roughly a **12× overspend**, and the
  `/analyze` response reported "the analyst did not run" on reports the analyst
  had just written. This one line is what made HXL flip — a language model
  re-sampled twelve times an hour on unchanged inputs will disagree with itself
  when a call is genuinely marginal, which is also why the price target drifted
  $101 → $102 → $103 → $104 with the score frozen.
- **Repeat alerts for a conviction that had not changed.** A HIGH-conviction
  ticker re-alerted on every evaluation for as long as the analyst held its
  view. Now only the *transition* into HIGH conviction alerts.
- **Duplicate proposals.** `PROPOSED` is deliberately not an open position, so
  nothing stopped the agent queueing the same entry again next cycle. Four
  identical HXL cards could sit in the Orders queue with no way to tell which
  was current. One outstanding proposal per ticker; approving or declining it
  clears the way for the next.
- **Repeated skip records.** A standing condition — position already open, IB
  Gateway down — wrote an identical `SKIPPED` row on every evaluation and
  buried real order history. An unbroken run of the same reason is now recorded
  once. A *different* reason, or the same one after something else happened, is
  recorded again.

### Added

- **Signal debouncing** (`services/signal_stability.py`). A changed verdict
  becomes a *candidate* and publishes only after `SIGNAL_CONFIRMATIONS` (2)
  consecutive fresh evaluations agree **and** the current verdict has stood for
  `SIGNAL_MIN_DWELL_MINUTES` (60). An oscillating ticker therefore publishes
  nothing and says nothing, which is the honest report of a stock sitting on a
  threshold. **SELL is exempt from both** — delaying an exit costs money,
  delaying an entry costs an opportunity, and those are not the same price.
  While a candidate is withheld, the signal's explanation says so.
- **Hysteresis on the thresholds.** Entering BUY still requires clearing 0.70;
  leaving it now requires falling under 0.67 (`SIGNAL_HYSTERESIS`). One-sided
  on purpose: an existing verdict becomes sticky, never easier to acquire. The
  risk gate still vetoes a BUY the band would otherwise hold, and calibration
  replays continue to use the raw rule.
- **Alerts you can act on without opening the app.** A bare
  `Target: $102.00 | Stop: $87.50` never said what those levels were measured
  from. Each level is now quoted with its distance from the price the call was
  made at, alongside the reward-to-risk ratio, the risk score, the analyst's
  expected horizon, and your configured position size:

  ```
  📈 HXL signal flipped: HOLD -> BUY
  Score: 61/100 | Moderate | Confidence: 55% | Risk: 4.2/10
  Price now: $95.20
  Target: $102.00 (+7.1%)
  Stop: $87.50 (-8.1%)
  Reward:risk 0.9 : 1
  Expected horizon: 2-4 weeks
  Your sizing: 5% of account equity, adjusted for volatility
  ```

  That 0.9 : 1 is the point — the old format hid the fact that this particular
  setup risked more than it stood to make.
- **`pending_signal` on `GET /analyze`**, so a withheld candidate is visible
  rather than merely silent.

### Known gaps

- **The confirmation delay is real.** With the analyst cache working, a genuine
  BUY can take up to two analyst evaluations — as much as an hour or two — to
  publish. That is the deliberate trade: fewer, later, more trustworthy entries.
  It has not yet been measured against `stocks_signal_history` to say what it
  costs in missed entry price. Set `SIGNAL_CONFIRMATIONS=1` to opt out.
- **Neither client renders `pending_signal` yet.** The withheld candidate shows
  up only in the explanation text, which both clients already display. A proper
  "candidate, unconfirmed" chip on web and mobile is still to do.
- **There is still no time-based exit.** A position is closed by its stop, its
  target, or a SELL signal, and by nothing else. The analyst's `time_horizon`
  is displayed and now included in alerts, but nothing enforces it: a position
  whose thesis said "2-4 weeks" will sit there indefinitely if neither bracket
  leg fills. This is the most-asked question about the agent and it deserves a
  real answer, not a displayed string.
- The debounce is tuned from a single day's observation of one ticker. The
  defaults are a judgement call, not a measurement.

---

## [1.3.0] — 2026-08-24

Closes the security and operability items carried since 1.1.0.

### Added

- **Login rate limiting.** `/auth/login` had no limit of any kind — a known
  email could be guessed against as fast as the network allowed. Sliding window
  per email *and* per client address, both of which must pass: the first stops a
  slow grind against one account from many addresses, the second stops one
  address spraying many accounts. 8 attempts per 5 minutes, then a 15-minute
  lockout. A success clears the email's history so a user who mistypes twice
  carries no penalty; the client key is *not* cleared, because one valid
  credential should not buy an address unlimited guesses at every other account.
  Client identity comes from `CF-Connecting-IP` — everything arrives through
  Cloudflare, so `request.client.host` is always the tunnel and would collapse
  every user into one bucket.
- **The placeholder JWT secret is now impossible to miss.** `JWT_SECRET_KEY` is
  never injected by the deploy and `.env.production` persists on the server, so
  "never set" persisted silently while the app fell back to a value committed to
  this repo — anyone reading the source could forge a token for any user and
  reach order placement. Now logged at critical on startup, reported as
  `auth_secret_is_default` on `/health` (unauthenticated, deliberately — a
  forgeable signer makes auth meaningless anyway), and the deploy generates a
  real key when it finds the placeholder or nothing.
- **Unconfigured alerting is surfaced.** The broker watch job sends nothing when
  no Slack/WhatsApp channel is set, which is exactly how an outage goes
  unnoticed. The Broker panel now says so and links to Profile → Alerts.

### Changed

- **The gateway restart no longer needs the host Docker socket.** It goes
  through a `docker-socket-proxy` sidecar that holds the socket read-only and
  answers only the container endpoints — images, volumes, networks, exec, swarm
  and system are refused, and the proxy is never published to the host. This is
  a much smaller grant than the raw socket, *not* a precise "restart only"
  capability, and the compose comments say so rather than overselling it. Still
  gated behind `ALLOW_GATEWAY_RESTART` so a deployment can decline entirely.
  The restart call distinguishes a refused endpoint (403) from a missing
  container (404), which are different problems.

### Known gaps

- The restart path has **still never been exercised against a live Docker
  daemon** — only its refusal behaviour is tested.
- Rate-limit counters are in-process: they reset on restart, and a second API
  replica would keep its own. Fine for a single container, and the module says
  so rather than leaving it to be discovered.
- `JWT_SECRET_KEY` on the existing server has not been inspected. If it was
  already set by hand, nothing changes; if it was the placeholder, the next
  deploy replaces it and **all existing sessions are invalidated** — sign in
  again.

---

## [1.2.0] — 2026-08-24

### Added

- **Broker recovery from the UI.** Orders → Broker panel shows session state and
  offers two actions kept deliberately separate, because they carry different
  risk. **Reconnect** asks for a session immediately instead of waiting out the
  15s→300s backoff; it needs no privileges and fixes a stale socket. **Restart
  gateway** restarts the container — the only thing that clears a gateway that is
  running but unauthenticated — and is **off by default**, because it requires
  the host Docker socket inside the API container, which is root on the host.
  The panel says why the button is unavailable rather than leaving it greyed
  out, and warns that a restart usually triggers a 2FA push that must be
  approved on a phone or the session never returns.
- **Broker disconnection alerts.** A 5-minute job notifies through the existing
  Slack / WhatsApp channels once the session has been down for
  `BROKER_ALERT_AFTER_MINUTES` (default 15) — once per outage, plus a recovery
  notice. The threshold sits above the reconnect ceiling so a blip the loop
  fixes on its own never pages anyone. This failure was previously silent: the
  agent keeps scoring and the UI keeps working while every order is refused.
- **`runbooks/ib-gateway-offline.md`** — why the gateway goes offline (IBKR
  weekend maintenance, the daily forced logout, unanswered 2FA), how to tell
  which case you are in from the logs, and how to recover from the UI or over
  SSH. The in-app Guide covers setup only.
- `GET /trading/broker/status`, `POST /trading/broker/reconnect`,
  `POST /trading/broker/restart`.

### Fixed

- **Order refusals now say what is blocking them.** "Position already open for
  this ticker" gave no way to tell a filled holding from a stale order record
  that never reconciled, and those need opposite responses. `FILLED` /
  `PARTIAL` / `PENDING` now read differently and name the quantity, date, and
  order id. The `FILLED` case also explains why the guard stands: the first
  entry's bracket is still working, so a second entry would put two stops on one
  holding and could oversell into a short.
- **`Close` reported success while doing nothing when the broker was
  unreachable.** Second instance of the bug fixed in 1.1.1 — that fix covered
  the `enabled` gate and missed the connectivity gate four lines below it.
  User-initiated closes now return 503; the scheduled agent still fails quietly
  because it retries next cycle.

### Known gaps

- **Runbooks live outside `docs/`** because that directory is gitignored as
  developer planning material. An operational runbook has to be in the repo, so
  it went to `runbooks/`. The nine documents in `docs/` remain untracked and
  exist only on whoever's machine wrote them.
- The UI restart path has not been exercised against a real Docker socket — it
  is off by default and was tested only for its refusal behaviour.

---

## [1.1.1] — 2026-08-22

Hotfix. **1.1.0 took the API down**, so login and everything else failed.

### Fixed

- **Startup crash.** The idempotency index added in 1.1.0 was declared
  `sparse=True`. A compound sparse index only skips a document when *every*
  indexed field is missing, and every trade has a `user_id` — so the whole
  existing `trades` collection was indexed with `idempotency_key: null`, and the
  second such document collided against `unique=True`. `create_index` raised
  inside `_ensure_indexes`, `connect_db` awaited it unguarded, and the exception
  propagated out of lifespan startup and killed the process. Now uses
  `partialFilterExpression`, the pattern the signal-history index three lines
  above already used for the same problem.
- **Index creation and data migration can no longer abort startup.** A defect in
  a *trades* index stopped people logging in, which is the wrong blast radius.
  Connecting to Mongo is the only load-bearing step in that sequence; the rest is
  maintenance, and maintenance failing should degrade the service rather than
  delete it. Both log at error level with the concrete consequence attached.

### Known gaps

- Not reproduced locally before shipping — no Docker daemon was available to run
  a MongoDB instance. **Every backend test at the time stubbed Mongo**, so
  `_ensure_indexes` never ran against a real database and a failure that only
  manifests against real documents was structurally invisible. Startup-path code
  needs a real database in test.

---

## [1.1.0] — 2026-08-22

The UI was showing roughly 60% of what the engine does, and misstating parts of
the rest. This release closes that gap, adds a user-initiated trading path, and
brings mobile to parity.

### Added

**Analysis that explains itself**

- **Score attribution** on the ticker page — each of the six sub-scores with its
  weight and the points of the composite it supplied. The sub-scores had always
  been computed and stored; nothing returned them, so the product showed a 0–100
  number with no attribution while offering sliders to reweight it.
- **Risk & Signal Gate panel** — the 0–10 risk score, the veto line, and which
  gate conditions passed. `risk` was a required field on every response and was
  rendered nowhere, though it gates every BUY.
- **Calibration screen** (`/calibration`, both clients) — whether the score ranks
  outcomes, what each candidate BUY cutoff would have returned, and whether
  stated confidence tracks being right. Every row carries its sample size; under
  30 settled records a bucket is marked *thin* rather than shown as a confident
  percentage.
- **Price chart** — candlesticks with SMA-20/50 and volume. The product had none.

**A user-initiated trading path**

- **Trading modes**: `MANUAL` / `SEMI_AUTO` / `AUTO`. Under MANUAL — and under
  SEMI_AUTO below the conviction bar — the agent runs every guard, sizes the
  order, then records it as a proposal for a human decision instead of sending
  it. New accounts default to MANUAL.
- **Order ticket** on the ticker page, pre-filled from the quantity, stop, and
  target the engine already computed.
- **Orders screen** — proposal queue, open positions with a close action, and
  full order history labelled by who decided (Agent / Approved / You).
- `POST /trading/order`, `GET /trading/proposals`, and proposal approve/decline.
- `GET /chart/{ticker}/series` — OHLCV plus server-computed moving averages.

**Interface**

- Toast notifications with an undo window; watchlist delete now defers its
  request rather than firing immediately with no way back.
- ⌘K ticker lookup from any page, and a `/search` screen — previously you could
  only search a ticker while adding it to a watchlist.
- Sortable watchlist columns.
- Realised performance splits three ways that are never pooled: agent-placed,
  agent-proposed-human-approved, and human-chosen.
- `npm run lint:a11y` in `frontend/` — jsx-a11y, which must stay clean.

### Changed

- **Autonomy is a dial, not a switch.** Existing accounts already trading
  unattended are migrated to `AUTO` explicitly on startup, so the safer MANUAL
  default cannot silently stop a running system. See `db._migrate_trading_mode`.
- **All order paths share one guard chain** (`_prepare_entry`). A user-initiated
  order differs in exactly two documented ways — no signal-score threshold and
  no whitelist — and still obeys the CIRO restriction, the position cap, the
  daily-loss kill switch, the cash reserve, and the refusal to open an
  unbracketed position.
- **Client-supplied order quantities are requests, not instructions.** The server
  re-derives the fundable quantity from live account state and takes the smaller
  of the two, so sizing cannot be escaped from a form field.
- Orders carry an idempotency key, backed by a unique sparse index — a
  double-clicked Buy places one order.
- Live-money orders and proposal approvals require typing the ticker to confirm.
- **Price history moved behind a provider seam** (`price_providers.py`).
  Switching to licensed data is `PRICE_PROVIDER=polygon` rather than an edit to
  the ingestion path. A licensed provider failing does *not* fall back to the
  unlicensed one.
- Data-source badges: seven yfinance-backed rows moved from **Live** to **Dev
  data**, with the licensing position stated.
- The analyst model shown in the UI now comes from config and reports honestly
  when the analyst did not run.
- Mobile reached parity: chart, calibration, attribution, risk gate, holdings,
  orders, and the autonomy ladder.

### Fixed

- **Dead "Analyze" tab.** The mobile bottom bar pointed at `/ticker/search`,
  which resolved as a ticker named "search" and rendered a full-page error.
- **Dark mode was broken on the Performance page.** 55 hardcoded light-mode hex
  values painted `#14110c` text on the `#0e0c09` dark background — the accuracy
  dashboard rendered as a near-black rectangle. Colours are design tokens now.
- **`POST /trading/close/{ticker}` did nothing for manual-mode users.** It ran
  through the agent's `enabled` gate, so it returned `close_order_submitted`
  while no order was submitted.
- A route handler named `get_settings` shadowed the config accessor in
  `trading.py`, which would have failed every order request.
- Mobile profile save sent a bare string where the API expects an object, so
  changing your display name failed.
- The Signal Weights panel offered a Volatility slider defaulting to 10% when
  the engine deliberately sets it to 0 — volatility is priced at the risk gate.
  The panel's Reset also disagreed with the server's own defaults.
- The UI named the wrong Claude model.
- Duplicate "By Ticker" heading and two columns both labelled "Exit".

### Accessibility

The frontend had 13 `<label>` elements and **zero** `htmlFor` — not one input
was programmatically named — and watchlist rows were `div onClick` with no role,
`tabIndex`, or key handler, making the expandable row keyboard-unreachable.

- Labels bound to their controls; rows are real disclosure controls with
  Enter/Space, `aria-expanded`, and `aria-controls`.
- Error banners are `role="alert"`; sort headers announce their direction;
  filter chips carry `aria-pressed`.
- The command palette traps Tab and restores focus on close.
- Skip-to-content link.
- Linting added, which caught four defects a manual sweep had missed.

### Security & compliance

- **"Not financial advice" now appears on every screen**, web and mobile. It
  previously existed only on the Guide page and inside exported PDFs, in an
  application that routes live orders to a broker.
- Price history was being fetched from Yahoo's undocumented
  `/v8/finance/chart` endpoint with a spoofed browser User-Agent. That remains
  the development default and is now labelled as such, with a licensed path
  available by configuration.

### Known gaps

- The **Polygon price adapter has never made a live request.** It is tested for
  the refusal path (no key → raises) but unproven against real data; it needs a
  plan covering aggregates.
- Short interest, options flow, and insider activity still use yfinance.
- Calibration will show mostly *thin* buckets until more signals settle. This is
  the honest state of a young track record, not a defect.
- Three mobile TypeScript errors remain — library typing noise
  (`react-hook-form` generic variance, a `<P style>` prop, one route literal)
  with no runtime impact.
- Mobile screens hardcode a light-only palette; the web design tokens are the
  reference if they are ever themed.
- The per-user subdomain split (`sta.` vs a custom domain) is presentational.
  There is no hostname check and all users share one broker account, which is
  correct for a single operator and would need real tenant isolation before a
  second one.

---

## [1.0.0] — before 2026-08-22

Baseline: the system as it stood before this changelog began. FastAPI + MongoDB
ingestion and scoring pipeline, React SPA, Expo mobile app, IBKR automated
trading, AI analyst reports, and the signal-history performance tracker.

History before this point is in the git log rather than here.

[1.1.0]: https://github.com/SAMSBPM-Technologies-Inc/SAMSTradingAgent/pull/3

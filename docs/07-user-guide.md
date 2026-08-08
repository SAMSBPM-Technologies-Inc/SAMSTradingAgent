# SAMSTradingAgent User Guide

**sta.samsbpm.com** — AI-powered stock analysis for retail investors and swing traders

---

> **Before you begin:** SAMSTradingAgent is a decision-support tool. It surfaces signals, data, and research notes to help you make better-informed decisions. It is not a trading bot and does not place trades on your behalf. You are always in control of what you buy or sell.

---

## 1. What is SAMSTradingAgent?

SAMSTradingAgent is a stock analysis platform that pulls together four things most retail investors have to check separately:

- **Technical analysis** — price patterns, momentum, and trend indicators
- **AI research notes** — a Claude-powered analyst that writes a research note in plain English, just like a Wall Street report but without the jargon
- **Alternative data** — insider buying/selling activity and options market flow, which institutional investors use but most retail tools ignore
- **Macro context** — interest rates, VIX fear index, and inflation data that affect the overall market environment

All of this gets combined into a single **BUY / SELL / HOLD signal** with a **score from 0 to 100** and a **conviction rating**. The goal is to help you cut through noise and focus your research time on the setups that look most compelling.

What it is not: a guarantee, a financial advisor, or an automated trading system. Think of it as a smart research assistant that does the data gathering and initial analysis for you, so you can spend your time on the decisions that matter.

---

## 2. Getting Started

### Create an Account

1. Go to **sta.samsbpm.com** in your browser
2. Click **Register** (or the "Sign up" link on the login screen)
3. Enter your **email address**, choose a **password**, and enter a **display name** (this is what appears in your alerts)
4. Click **Create account**
5. You will be logged in immediately and taken to your dashboard

No credit card is required to get started.

### Add Stocks to Your Watchlist

Your watchlist is the list of stocks you want to track. You can add any US-listed stock.

1. From the dashboard, click or tap the **search bar** at the top of the page
2. Start typing a company name (e.g., "Palantir") or a ticker symbol (e.g., "PLTR")
3. A dropdown list appears — select the stock you want
4. The stock is immediately added to your watchlist and the system begins analyzing it
5. Within about 30–60 seconds, the signal card for that stock will appear on your dashboard

**Tip:** You can add as many stocks as you want. The system runs analysis automatically throughout the trading day.

To remove a stock from your watchlist, open the ticker detail page and click the **Remove from watchlist** button.

---

## 3. Understanding Your Dashboard

The dashboard shows a card for every stock on your watchlist. Here is what each element means:

### Ticker Name, Price, and Day Change

At the top of each card you will see the ticker symbol (e.g., **AAPL**), the current price, and the percentage change from the previous close (e.g., **+1.4%** in green or **-2.1%** in red). These are sourced from Yahoo Finance and update each time a new analysis runs.

### Signal Badge

A colored badge shows the system's current recommendation:

| Badge | Color | Meaning |
|-------|-------|---------|
| **BUY** | Green | Multiple indicators are aligned bullishly — this looks like a potential entry opportunity |
| **SELL** | Red | Multiple indicators are deteriorating — worth considering a reduction or exit |
| **HOLD** | Gray | Signals are mixed or unclear — wait for a clearer picture before acting |

### Score Bar (0–100)

A horizontal bar shows the composite score, which is the numerical strength of the signal:

- **70–100**: Strong — multiple signals agree the setup looks bullish
- **40–70**: Moderate — mixed signals, lean cautious
- **0–40**: Weak — signals are broadly negative or inconclusive

A BUY signal at score 85 is a much stronger setup than a BUY signal at score 52. Pay attention to the number, not just the label.

### Conviction Badge

Three levels of conviction indicate how confident the AI is in the signal:

- **Strong Signal** (HIGH conviction): The AI found strong, consistent evidence across multiple data sources
- **Moderate** (MEDIUM conviction): The evidence is somewhat mixed, but the direction is reasonably clear
- **Weak Signal** (LOW conviction): The direction is positive/negative but the evidence is thin — treat with more skepticism

### Price Target and Thesis

Below the signal you will see the AI analyst's **price target** (where it thinks the stock could go) and a one-sentence **thesis** summarizing the core reason for the signal. For example: *"PLTR's government contract pipeline and improving margins support a near-term breakout above resistance."*

### Refresh Button

Each card has a refresh icon. Clicking it forces a fresh analysis for that ticker, bypassing the 30-minute cache. Use this if you know something has changed (e.g., earnings just came out) and want an updated signal immediately.

---

## 4. Reading a Full Analysis (Ticker Detail Page)

Click any ticker card on the dashboard to open the full analysis page. This is where the depth of the research is visible.

### Score Gauge

A semicircular meter at the top of the page shows the composite score from 0 to 100. Think of it as a "bullishness meter":

- **70–100**: Multiple signals agree — this looks bullish
- **40–70**: Mixed signals — lean cautious
- **0–40**: Multiple signals suggest caution or an exit

The gauge changes color: green for high scores, yellow for moderate, red for low.

### Signal and Conviction

The signal and conviction work together. Here is how to read the combinations:

| Combination | What it means |
|-------------|---------------|
| BUY + Strong Signal | Highest confidence entry signal — multiple data sources agree |
| BUY + Moderate | Directionally positive but worth doing additional research |
| BUY + Weak Signal | Direction is positive but the evidence is thin — size accordingly |
| HOLD | Unclear direction — wait for a clearer signal before committing |
| SELL + Strong Signal | Strong evidence of deterioration — consider reducing or exiting your position |
| SELL + Weak Signal | Slight lean bearish, but not a strong conviction call |

### Price Target and Stop Loss

The AI analyst's **price target** represents the level it believes the stock could reach within its stated time horizon, based on technical levels (ATR, support/resistance). The **stop loss** is the level where the investment thesis would be broken.

These are not guarantees. Markets are unpredictable and any price target can be wrong. Use these levels as reference points for your own risk management, not as definitive outcomes.

The **time horizon** tells you the window the analyst is thinking about (e.g., "2–4 weeks"). A price target makes no sense without understanding the timeframe.

### Investment Thesis (1–2 sentences)

This is the core reason for the signal in plain English. It summarizes what the data shows and why the AI reached its conclusion. Read this first — if it does not match what you know about the company, that is worth investigating.

### Analyst Note (2–3 paragraphs)

A deeper research note written in sell-side style by the AI. It covers:

- The **current technical picture** — what the price action and indicators are showing
- The **fundamental setup** — revenue growth, valuations, analyst consensus
- **Key catalysts and risks** — what could drive the stock up or down in the near term

This is the section where the AI shows its reasoning. Even if you disagree with the conclusion, the note tells you what data drove it.

### Bull Case and Bear Case

Even for a strong BUY signal, the analysis shows both perspectives:

- **Bull case**: The scenario where the investment works out — what needs to go right
- **Bear case**: The scenario where it does not — what could go wrong

Reading the bear case is especially important. A strong bull case that has a plausible, serious bear case (e.g., a binary clinical trial outcome) should inform how much you risk. A strong bull case with a weak bear case (e.g., "market conditions could deteriorate") is a much cleaner setup.

### Catalysts and Key Risks

Two to four specific items each, drawn from current data. These are not generic statements like "competition could increase" — they are specific to the company and the current moment. For example: "Q3 earnings report due in 12 days" or "Contract renewal decision expected from the Department of Defense."

### Entry and Exit

Specific suggested entry and exit levels derived from the price target and stop loss, with the time horizon stated. These are starting points for your own position sizing and risk management.

---

## 5. Alternative Data Section

This section is what sets SAMSTradingAgent apart from basic charting tools. Most retail investors do not have easy access to this data. Here is how to read each component.

### Options Flow — Put/Call Ratio

Options are contracts that give traders the right to buy (calls) or sell (puts) a stock at a specific price. The ratio of put volume to call volume tells us what the options market thinks about the stock's direction.

- **Put/call ratio above 1.5**: Bearish — institutions are buying put protection, which means they expect the stock to fall or are hedging existing positions
- **Put/call ratio 0.7–1.5**: Neutral to mildly bearish
- **Put/call ratio below 0.7**: Bullish — traders are buying calls, betting on upside

**How to use it alongside the signal:**

- BUY signal + BULLISH options flow = strong confirmation. Both the technical/fundamental picture and the options market agree.
- BUY signal + BEARISH options flow = a caution flag. Be more selective about timing and position size.
- SELL signal + BEARISH options flow = strong confirmation of the sell case.

Note that options data is sourced from the nearest expiry options chain. Very short-dated options can sometimes distort the ratio around earnings or major events.

### Short Interest

Short sellers borrow shares and sell them, hoping to buy them back cheaper later. High short interest means a lot of people are betting against the stock.

- **% of Float Shorted**: What percentage of the tradeable shares are being shorted. Above 20% is considered very high.
- **Days to Cover**: How many days it would take all short sellers to buy back their positions, at average daily volume. Higher = more potential squeeze.
- **Squeeze Risk**: Rated HIGH, MEDIUM, or LOW based on short % and days to cover.

**How to use it:**

- HIGH short interest is a caution flag on its own — it means sophisticated investors are betting heavily against the stock, and they may know something.
- However: if the stock is already rising sharply while short interest is HIGH, you may be seeing the beginning of a **short squeeze** — short sellers are being forced to buy back at a loss, which drives the price up even further. This is what happened with GameStop in 2021. These moves can be violent and fast in both directions.
- Do not chase a squeeze once it is already well underway. The squeeze risk indicator tells you the potential is there; the price action tells you if it is happening.

### Insider Activity (90 days)

This shows buying and selling activity by company insiders — executives, board members, and shareholders who own more than 10% of the company — based on their SEC Form 4 filings.

**Why buys matter more than sells:**

Insiders sell stock for many reasons that have nothing to do with the company's prospects: paying taxes, diversifying their wealth, funding a home purchase. Insider selling is normal and not necessarily negative.

But insiders only buy stock with their own money when they genuinely believe it is going up. A CEO buying $500,000 of stock in the open market is a meaningful signal.

**How to use it:**

- BUY signal + insider buying in the last 90 days = strong confirmation. The people who know the company best are putting their own money in.
- BUY signal + heavy insider selling = a reason to be more cautious. Do more research before acting.
- SELL signal + heavy insider selling = strong confirmation.

The table shows the six most recent insider transactions with date, insider name, transaction type, number of shares, and approximate value.

---

## 6. Performance Page

The Performance page tracks how accurate the system's signals have been historically. This is important for calibrating how much weight to give the signals.

### How Performance Is Measured

When the system generates a signal, it records the stock's price at that moment. Twenty trading days later (approximately one calendar month), the system checks the current price and calculates the return. For BUY signals, a positive return is "correct." For SELL signals, a negative return is "correct." HOLD signals are not evaluated directionally.

### What You Are Looking At

- **Win Rate**: The percentage of settled signals where the direction was correct. A win rate above 55% is generally considered meaningful for a directional strategy.
- **Average 20-Day Return**: The mean return across all settled signals of that type. A positive average return for BUY signals means the system has been adding value on average.
- **By Signal Type**: Separate statistics for BUY, SELL, and HOLD signals. You can see whether the system is better at identifying buy setups than sell setups.
- **Signal History Table**: A record of individual signals showing the ticker, signal type, score, price at signal, price 20 days later, return percentage, and whether it was correct.

### How to Use This Page

- If the BUY signal win rate has been below 50% recently, the model may be struggling in the current market environment (e.g., during a broad market downturn, most stocks go down regardless of their individual signals).
- If you see the system was consistently accurate in a particular sector or score range, you can use that to calibrate your own conviction.
- This page is not a promise of future accuracy. Past results do not guarantee future performance.

---

## 7. Setting Up Alerts

Alerts notify you when important things happen — a signal flips, a high-conviction opportunity appears, or your daily digest arrives at market open.

### Slack Alerts

If you use Slack for communication, you can receive real-time alerts directly in any Slack channel.

1. Go to **Profile** — tap your avatar in the top right corner, or the Profile tab in the mobile bottom bar
2. Scroll down to the **Alerts** section
3. In the **Slack Webhook URL** field, paste your Slack incoming webhook URL
   - To create a webhook: go to [api.slack.com/messaging/webhooks](https://api.slack.com/messaging/webhooks), create an app, enable incoming webhooks, and add a webhook to your workspace for the channel you want
4. Toggle **"Notify when signal flips"** to receive an alert whenever a stock's signal changes (e.g., from HOLD to BUY)
5. Toggle **"Notify on Strong Signal"** to receive an alert whenever any stock on your watchlist generates a HIGH conviction signal, even if the signal did not change
6. Click **Save**
7. Click **Test** — you should see a test message in your Slack channel within a few seconds

If the test message does not arrive, double-check the webhook URL. Slack webhooks are channel-specific, so make sure you created the webhook for the right channel.

### WhatsApp Alerts (via CallMeBot — free)

CallMeBot is a free service that can send WhatsApp messages to your phone via a simple API. Setup takes about five minutes.

1. Go to **callmebot.com** and follow the WhatsApp setup instructions to get the CallMeBot API number
2. Save the CallMeBot number to your WhatsApp contacts
3. Send the message **"I allow callmebot to send me messages"** to that number on WhatsApp
4. You will receive a reply containing your personal API key (a short string of numbers)
5. On the **Profile** page in SAMSTradingAgent, enter your phone number in **international format** (e.g., +12125551234 for a US number)
6. Enter the API key you received from CallMeBot
7. Click **Save**, then **Test**
8. You should receive a test WhatsApp message within about 30 seconds

**Note:** CallMeBot is a third-party service not affiliated with SAMSTradingAgent. Its availability depends on their service. If you do not receive the test message, check that you completed the opt-in step (step 3 above).

### Daily Digest

Toggle **"Daily digest at 9 AM ET (weekdays)"** on the Profile page to receive a morning summary of all your watchlist signals before the market opens. The digest lists every stock, its current signal, score, and conviction level, sorted from highest score to lowest. This lets you quickly see which setups look strongest before the opening bell.

The digest is sent via whichever channels you have configured (Slack and/or WhatsApp).

---

## 8. The Guide Page

The Guide page contains two companion tools: the **Buyer's Guide** and the **Seller's Guide**. These are designed to help you use the signals correctly depending on where you are in the trade lifecycle.

### Buyer's Guide

Use the Buyer's Guide when you are **considering adding a new position** to your portfolio. It walks you through:

- What score and conviction levels make a signal worth acting on
- How to read the bull case and alternative data to confirm an entry
- Timing considerations (e.g., avoid entering right before a major earnings release unless you understand the risk)
- How to set an appropriate position size based on the stop loss level

The key principle: a BUY signal with HIGH conviction + insider buying + BULLISH options flow is the strongest possible setup. A BUY signal with LOW conviction and BEARISH options flow is a much weaker case for entering.

### Seller's Guide

Use the Seller's Guide when you are **already holding a stock** and evaluating whether to stay in, take profit, or cut losses. It covers:

- What it means when a signal shifts from BUY to HOLD or HOLD to SELL while you are holding
- When to take profit (signal is still BUY but you are approaching the price target)
- When to cut losses (stop loss level has been breached, or signal flips to SELL)
- How to read the bear case when you are already invested — it is harder to see objectively when you own the stock

---

## 9. Important Disclaimers

Please read these before making any trading decisions.

- **SAMSTradingAgent is a decision-support tool, not financial advice.** The signals and research notes are generated by AI and automated algorithms. They do not constitute personalized investment advice.

- **Past signal accuracy does not guarantee future results.** The Performance page shows historical accuracy, but market conditions change. A strategy that worked in a bull market may not work in a bear market.

- **Always do your own research.** Use the signals as a starting point, not an endpoint. Read the analyst note, understand the bear case, check the news, and make sure you understand the business before putting money in.

- **Consider your personal risk tolerance.** Every stock on a watchlist carries the potential to go to zero. Only invest money you can afford to lose.

- **Data delays and lags exist.** Price data from Yahoo Finance is typically delayed 15 minutes during market hours. Options flow and short interest data may have reporting lags of up to a few days.

- **The AI analyst can make mistakes.** Claude is a powerful language model, but it can misinterpret data, generate incorrect numbers, or produce analysis that is confidently wrong. Always verify key numbers against primary sources before trading.

---

## 10. Tips for Best Results

**Use the right guide for where you are in the trade.** The Buyer's Guide before entry, the Seller's Guide when holding. These tools are calibrated for different decision contexts.

**Look for alignment across all signals.** The strongest setups are when the signal (BUY), conviction (HIGH), options flow (BULLISH), and insider activity (buying) all point in the same direction. Any one of these alone is less compelling.

**Do not trade purely on SELL signals without checking price action.** SELL signals are harder to time than BUY signals. A stock can show deteriorating technical signals while continuing to grind higher. Always confirm with price action and chart support levels.

**Watch the Performance page.** If the win rate for BUY signals has dropped below 50%, the current market environment may be challenging for the model. In bear markets or high-volatility periods, even good setups fail. Adjust your position sizes accordingly.

**Fresh signals matter.** Check the "Generated" timestamp on each signal. Signals generated more than a few hours ago may not reflect the latest price action, especially around market events. Use the refresh button if you need an up-to-date picture.

**The score bar is a spectrum, not a binary.** A BUY signal at 72 and a BUY signal at 91 are not the same thing. The higher the score, the more data points are aligned. Size your positions proportionally to your conviction in the signal strength.

# Portfolio watcher

A free program that checks your holdings twice a day, before the market opens and after it closes, and sends you one short Telegram message when something that matters to them has happened. On a quiet day it sends nothing.

Results season is when most of us check our holdings the most, and it is also when the news that moves them comes from the most places at once: the company's own results, a commodity it buys, a currency it earns in, a rate decision, a strait in the Gulf. Asking an AI to check all of that every day costs money and gives a slightly different answer every time. So this program uses AI once, when you build it, and after that it is plain code reading free public data, at no cost.

## What it watches

Your holdings are connected to each other through what they buy, what they sell and what they borrow at. Crude touches an airline, a ride-hailing company and a retailer at the same time; the euro touches every company that earns in Europe. So when you start the watcher, its first message is a map of how your portfolio connects: each commodity, currency and rate, and which of your names are tied to it.

After that, each check sends one message, in this order of priority, and only the parts that have something in them:

1. **Results.** When a company on your list files its results with the SEC (a form 8-K with item 2.02), the program opens the press release and quotes its own sentences on revenue, earnings per share and the outlook, word for word, with a link to the release. Each result gets its own message. If you like to write a test before results, you can also give it one number to check, and it tells you whether the release cleared your line.
2. **New filings.** Everything else a holder should hear about from the SEC, in plain words with a link to the filing: an insider buying shares on the open market, an insider selling outside a pre-set trading plan, a material 8-K (a major agreement signed or ended, an acquisition, new debt, restructuring costs, a write-down, a senior officer joining or leaving, a change of auditor, earlier accounts that can no longer be relied on), the quarterly and annual reports, and an investor filing an activist-size stake (13D). Routine insider sales under pre-set plans are added up and shown once a week instead.
3. **Big moves in your holdings.** A holding that moved 5% or more in a day, with its move over the past month for context.
4. **What your portfolio depends on.** A commodity or currency your holdings are tied to breaking out of its range: a new three-month high or low, with the range it had been in, and the names in your portfolio tied to it. A swing of a few percent inside a range is noise, so it never fires. Crude can go from 90 to 110 and back inside a month without telling you anything about a holding that buys fuel.
5. **Rates and markets.** The 10-year and 2-year Treasury yields, high-yield credit spreads and the dollar reaching a three-month high or low, and the VIX crossing above 25, each with one line on why it matters.
6. **In the morning only:** the day's high-impact US releases (CPI, jobs, the Fed), the newest headline that names each of your first three holdings, and one headline from a trusted outlet for each theme you follow in `themes.txt` (a strait, a war, a tariff).

**Every Monday morning, the portfolio as a whole:** your largest positions, how the portfolio moved over the last five trading days, how much of it has revenue or costs tied to each commodity and currency (for example, 43% of the portfolio earning revenue tied to the euro), which holdings report results in the next five trading days, and the insider sales under pre-set plans since the Monday before. It describes your portfolio; it never tells you what to do with it.

Once something fires, it stays quiet for five days, so a trend does not message you every day.

## What it costs

Nothing. GitHub runs it for free, the Telegram bot is free, and the SEC, the St. Louis Fed (FRED), Yahoo Finance and Google News are free to read.

A private copy on GitHub gets 2,000 free minutes of running time a month. Our own test with 23 names took 40 seconds a run, which GitHub counts as one minute, so two runs every weekday use about 44 minutes a month.

## Set it up in the browser, no code

You need a free GitHub account and Telegram on your phone. It takes about ten minutes.

**1. Make your own copy.** On this page, click **Use this template**, then **Create a new repository**. Give it a name and choose **Private**, so your holdings list is visible only to you.

**2. Make your Telegram bot.** In Telegram, open **@BotFather** and send `/newbot`. Give the bot a name, then a username that ends in `bot`. BotFather replies with a token, a long line of numbers and letters. Copy it and keep it to yourself, because anyone who has it can send messages as your bot. Then open your new bot and send it any message, "hi" is enough.

**3. Find your chat ID.** In your browser, open this address with your token in place of `TOKEN`:

`https://api.telegram.org/botTOKEN/getUpdates`

Look for `"chat":{"id":` followed by a number. That number is your chat ID.

**4. Add your three settings.** In your copy on GitHub, open **Settings**, then **Secrets and variables**, then **Actions**, and click **New repository secret** three times:

| Name | Value |
|---|---|
| `TELEGRAM_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | the number from step 3 |
| `SEC_EMAIL` | your email address. The SEC asks every program to say who is calling, and it is never sent anywhere else |

**5. Put in your stocks.** Open `stocks.txt`, click the pencil icon, and replace the examples with your own, one per line: the ticker, a space, and the number of shares you hold, like `UBER 120`. A ticker on its own is a name you watch but do not own. Click **Commit changes** to save. Whenever you buy or sell, change the line the same way.

**6. Switch it on.** Open the **Actions** tab. If GitHub asks, click to enable workflows. Click **Portfolio watcher**, then **Run workflow**. In a minute or two your bot writes to you. Its first messages are a hello and the map of how your holdings connect. From then on it runs by itself, before the US market opens and after it closes, every weekday.

## Your stocks, and the optional extras

`stocks.txt` is all most people need:

```
UBER 120
SPGI 15
NXPI
```

The shares are what the Monday check uses to weight your portfolio. For a listing outside the US, use Yahoo Finance's symbol (`RELIANCE.NS 10`); the results and filings checks cover companies that file with the SEC.

**What your stocks depend on is filled in for you where it is plain.** The program reads each company's industry code at the SEC and ties a copper miner to copper, a utility to natural gas, an apparel maker to cotton, an airline to crude, and so on. The codes are broad: a ride-hailing app is filed as "business services", so its fuel cost is not guessed, and currencies are never guessed. The first message tells you which names it filled in and which are still unknown.

**The extras live in `watchlist.csv`, and every column is optional.** Add a row only for a name you want to say more about; its ticker is enough to match it to `stocks.txt`.

| Column | What to put in | Example |
|---|---|---|
| `ticker` | the ticker | `UBER` |
| `exposures` | what the company buys (cost) or sells (revenue), separated by `;`. Yours replace the guess | `wti:cost; eurusd:revenue` |
| `keywords` | words that put matching stories first in the morning headline | `robotaxi` |
| `look_for` | for people who write a test before results: the words that sit right before the number you care about in the results release | `Gross Bookings grew ... to` |
| `test` | your line for that number, starting with at least, at most, above or below | `at least 45` |
| `note` | anything you want repeated back to you in the results message | `Fuel is the drivers' cost` |

A few things that help:

- **The exposure names** come from `data/commodities.json`. The common ones: `wti` and `brent` (crude), `natgas_us`, `gasoline`, `copper`, `aluminium`, `gold`, `silver`, `uranium`, `wheat`, `corn`, `coffee`, `cocoa`, `cotton`, `eurusd`, `gbpusd`, `usdjpy`, `usdcny`, `usdinr`.
- **Not sure what a company is exposed to?** Its annual report says. On your own computer, `python watch.py --exposures UBER` lists every commodity and currency word in Uber's latest annual report with the sentence around it. The program only counts words; you decide which ones are real. In Uber's report the word "sugar" turns up twice, and both times it is the chairman, Ronald Sugar. Or give the annual report to Claude or ChatGPT once and ask which commodities and currencies are a real cost or revenue for the business.
- **If you write a results line, copy `look_for` from the company's last release.** Apple writes "quarterly revenue of", Microsoft writes "Revenue was". Three dots stand for a few words in between. Write the `test` number in the units the company uses: if it reports in millions, your line is in millions.
- **Put your main holdings at the top of `stocks.txt`.** The morning headlines come from the top of the list down.
- **Headlines come from Yahoo Finance's news for each ticker** and must name the company. Themes that are not one company, a strait, a war, a tariff, go in `themes.txt`, one per line, and only trusted outlets count for those.

**Want to see a results message now?** In the **Actions** tab, click **Portfolio watcher**, then **Run workflow**, type a ticker in the box (for example `ACN`), and run it. It sends you that company's latest results again, marked as a replay.

## Connect your broker instead of keeping a list

The list in `stocks.txt` works with any broker, but you have to update it every time you buy or sell. If your broker offers an API (a door the broker opens so a program can read your account), the watcher can read your holdings from the broker before every check instead, so a new position is watched from the next run without you touching anything.

The watcher only reads. Nothing in it places an order. The broker files come from GreekSoup, the open-source one-person equity research desk.

**How to connect it:** add one more secret named `BROKER` with your broker's name from the table, then add the secrets that broker needs, the same way you added the Telegram ones. The keys come from your broker's own website. Each broker's name in the table links to a step-by-step page on the GreekSoup docs that shows where to find them, because GreekSoup connects to brokers the same way: [https://greeksoup.ai/docs/brokers/](https://greeksoup.ai/docs/brokers/).

| Broker | Where | `BROKER` | Secrets to add |
|---|---|---|---|
| [Alpaca](https://greeksoup.ai/docs/brokers/alpaca/) | United States | `alpaca` | `ALPACA_KEY`, `ALPACA_SECRET`, and `ALPACA_PAPER` set to `on` for a paper account |
| [Interactive Brokers](https://greeksoup.ai/docs/brokers/interactive-brokers/) | worldwide | `ibkr_flex` | `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY` (a Flex Query of your positions, made once in Client Portal) |
| [Tradier](https://greeksoup.ai/docs/brokers/tradier/) | United States | `tradier` | `TRADIER_TOKEN`, optional `TRADIER_ACCOUNT` |
| [tastytrade](https://greeksoup.ai/docs/brokers/tastytrade/) | United States | `tastytrade` | `TASTY_CLIENT_SECRET`, `TASTY_REFRESH_TOKEN`, optional `TASTY_ACCOUNT` |
| [Trading 212](https://greeksoup.ai/docs/brokers/trading-212/) | United Kingdom, Europe | `trading212` | `T212_KEY`, `T212_SECRET` |
| [Longbridge](https://greeksoup.ai/docs/brokers/longbridge/) | Hong Kong, Singapore | `longbridge` | `LONGBRIDGE_APP_KEY`, `LONGBRIDGE_APP_SECRET`, `LONGBRIDGE_ACCESS_TOKEN` (renew it every ninety days) |
| [Dhan](https://greeksoup.ai/docs/brokers/dhan/) | India | `dhan` | `DHAN_CLIENT_ID`, and either `DHAN_ACCESS_TOKEN` or `DHAN_PIN` with `DHAN_TOTP_SECRET` |
| [Angel One](https://greeksoup.ai/docs/brokers/angel-one/) | India | `angel_one` | `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET` |
| [Groww](https://greeksoup.ai/docs/brokers/groww/) | India | `groww` | `GROWW_API_KEY`, and `GROWW_API_SECRET` or `GROWW_TOTP_SECRET` |

With a broker connected, the watcher watches everything the broker holds, with the shares the broker reports, plus anything else in your lists: the names you watch without owning, and your extras in `watchlist.csv`. A holding that is not on the list is still watched for results, price moves and the morning headlines.

**What to know before you do it:**

- Your broker keys sit in your private copy's secrets, which GitHub encrypts and never shows again, even to you. Most brokers' keys can also trade, so treat them like a password: keep your copy private, and where your broker offers a read-only key, use that.
- The Indian brokers in the table need your trading PIN and the secret behind your authenticator app, because their rules ask for a fresh login each day and this is how the watcher logs in by itself. If you would rather not store those, keep the list.
- Brokers that need you to log in by hand every day (Schwab, Robinhood, Saxo, Zerodha, ICICI Direct, Upstox) cannot work on a schedule while you sleep, so for those the list is the way. Brokers with no API for individuals (Fidelity, Vanguard and most app-only brokers) are the same.
- **Not yet run from GitHub's computers.** The broker files are the same ones GreekSoup uses on readers' own computers, and we read a paper account with them on a Mac, but no broker has been connected to a copy of this watcher running on GitHub. If yours fails to connect, the run says why in plain words, and `stocks.txt` still works. GreekSoup's [broker will not connect](https://greeksoup.ai/docs/help/broker-will-not-connect/) page covers the usual causes.

## Set it for your market

It is set for the US market. To move it, open `.github/workflows/watch.yml`, click the pencil icon, and change the two `cron` lines. The times are in UTC, and `1-5` means Monday to Friday.

| Market | Before the open | After the close |
|---|---|---|
| United States (the default) | `"30 12 * * 1-5"` | `"30 21 * * 1-5"` |
| India | `"0 3 * * 1-5"` | `"0 11 * * 1-5"` |
| United Kingdom and Europe | `"0 6 * * 1-5"` | `"0 17 * * 1-5"` |

The results check reads SEC filings, so it covers companies that file in the US. The calendar is US releases. Everything else works for any market Yahoo Finance covers; for a listing outside the US, add a `yahoo` column with Yahoo's symbol for it (for example `RELIANCE.NS`).

## Changing the alerts

The thresholds sit at the top of `watch.py`, each with a line saying what it does: the daily move for a holding (5%), the range a breakout is measured against (about three months), how close to its five-year high a breakout has to be for the message to say so (2%), how long an item stays quiet after it fires (five days), and how many headlines you get. Change a number, commit, and the next run uses it.

## Where AI comes in

Only in two places, and both are optional. When you build your list, an AI can read each annual report once and tell you what each company buys and sells. And when a press release is laid out in a way the code cannot read, you can add an `OPENROUTER_API_KEY` secret, and a cheap model is asked for that one sentence. The program keeps the sentence only if it is word for word in the release, and the message says it was read by the model.

## Ask it questions (optional)

The watcher only talks; it does not answer. If you want to reply to an alert in Telegram and ask "what does this filing mean?", Claude Code can be connected to the same bot. Ask Claude to set it up for you: the Telegram channel for Claude Code works while Claude Code is running on your computer, and a routine in Anthropic's cloud can do it with your computer off. Both are research previews at the time of writing, so the steps may change.

## Limits

- A headline is matched on the first word of the company's name, so a story about Hilton Worldwide could appear under Hilton Grand Vacations; the link always shows which it is.
- The results quotes work on most US releases. A release laid out only as tables gives fewer lines, and a company that leads with its own measure (PTC leads with ARR) may show only the outlook; the link is always there. When the code cannot find your own words, the message says so.
- Companies listed outside the US do not file with the SEC, so they get the price, exposure and headline checks but no results check.
- Some commodities have no free daily price (uranium, lithium and a few others). They appear on the map, marked as not watched, because only a daily price can break out of a range.
- Yahoo Finance's price data is free but unofficial, and it can change without notice.
- This program sends information. It does not tell you what to buy or sell, and it places no orders.

## Run it on your own computer instead

If you would rather not use GitHub, it also runs on your own computer with Python and no installs: set the same settings as environment variables and run `python watch.py`. It only checks while the computer is on, so you need a scheduler (Task Scheduler on Windows, launchd or cron on a Mac) to run it twice a day.

Other ways to run it by hand:

- `python watch.py --dry-run` prints the message instead of sending it.
- `python watch.py --morning` includes the calendar and headlines now.
- `python watch.py --map` sends the map of how your holdings connect.
- `python watch.py --week` sends the Monday portfolio check now.
- `python watch.py --replay ACN` re-reads Accenture's latest results and sends them again.
- `python watch.py --chat-id` prints your chat ID after you message your bot.

## Credits and licence

The commodity and currency map in `data/commodities.json` comes from [GreekSoup](https://github.com/shubhamsborkar/greeksoup), the open-source one-person equity research desk, under the MIT licence. This program is MIT licensed too: copy it, change it and build on it. It is shared as it is, with no promise of updates.

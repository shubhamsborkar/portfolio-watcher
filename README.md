# Portfolio watcher

A free program that watches your holdings every hour and sends you a Telegram message when something that matters to them happens.

Results season is when most of us check our holdings the most, and it is also when the news that moves them comes from the most places at once: the company's own results, a commodity it buys, a currency it earns in, a rate decision, a strait in the Gulf. Asking an AI to check all of that every day costs money and gives a slightly different answer every time. So this program uses AI once, when you build it, and after that it is plain code reading free public data, every hour, at no cost.

## What it watches

Every hour, for every name on your list:

1. **Results.** When the company files its results with the SEC (a form 8-K with item 2.02), the program opens the press release, finds the number you wrote down for that company and tells you whether the release cleared your line, with the sentence it read and the link.
2. **The share price.** A move of 5% or more in a day.
3. **What the company buys and sells.** The commodities and currencies you tie to each holding: crude, copper, gold, natural gas, the euro, the yen and about fifty more. A big move gets a message that names your holdings and which way it cuts (a rise in crude hurts a holding that buys fuel and helps one that sells it).
4. **Macro.** A big move in the 10-year or 2-year Treasury yield, the VIX, high-yield credit spreads or the dollar.

Once a day, in the morning run (7:00 in New York):

5. **The calendar.** Any high-impact US release that day: CPI, jobs, the Fed.
6. **Headlines.** The latest headlines for the words you choose for each holding, a company name, a product, a war, a tariff, one line each.

Each alert fires once a day at most.

## What it costs

Nothing. GitHub runs it every hour for free, the Telegram bot is free, and the SEC, the St. Louis Fed (FRED), Yahoo Finance and Google News are free to read.

A private copy on GitHub gets 2,000 free minutes of running time a month. A list of about twenty names uses about two minutes an hour, which is around 1,500 minutes a month. A shorter list uses less.

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

**5. Put in your holdings.** Open `watchlist.csv`, click the pencil icon, and replace the example rows with your own (how to fill it in is below). Click **Commit changes** to save.

**6. Switch it on.** Open the **Actions** tab. If GitHub asks, click to enable workflows. Click **Portfolio watcher**, then **Run workflow**. In a minute or two your bot sends a message that says the watcher is running and lists your names. From then on it runs by itself at seven minutes past every hour.

## Filling in the watchlist

Each row is one holding. Only `ticker` is needed; every other column is optional.

| Column | What to put in | Example |
|---|---|---|
| `ticker` | the US ticker | `UBER` |
| `look_for` | the words that sit right before the number you care about in the company's results release | `Gross Bookings grew ... to` |
| `test` | your line for that number, starting with at least, at most, above or below | `at least 45` |
| `exposures` | what the company buys (cost) or sells (revenue), separated by `;` | `wti:cost` |
| `keywords` | words for the morning headlines, separated by `;` | `Uber; Strait of Hormuz` |
| `note` | anything you want repeated back to you in the results message | `Fuel is the drivers' cost` |

A few things that make it work well:

- **Copy `look_for` from the company's last release.** Apple writes "quarterly revenue of", Microsoft writes "Revenue was". Three dots stand for a few words in between. Write the `test` number in the same units the company uses: if it reports in millions, your line is in millions.
- **The exposure names** come from `data/commodities.json`. The common ones: `wti` and `brent` (crude), `natgas_us`, `gasoline`, `copper`, `aluminium`, `gold`, `silver`, `uranium`, `wheat`, `corn`, `coffee`, `cocoa`, `cotton`, `eurusd`, `gbpusd`, `usdjpy`, `usdcny`, `usdinr`.
- **Not sure what a company is exposed to?** Its annual report says. On your own computer, `python watch.py --exposures UBER` lists every commodity and currency word in Uber's latest annual report with the sentence around it. The program only counts words; you decide which ones are real. In Uber's report the word "sugar" turns up twice, and both times it is the chairman, Ronald Sugar. Or give the annual report to Claude or ChatGPT once and ask which commodities and currencies are a real cost or revenue for the business.
- **Pick specific words for headlines.** A company name alone brings in everything with that name in it, so "Walmart" will also bring you a golf tournament. A product, a project or a place usually works better.

## Changing the alerts

The thresholds sit at the top of `watch.py`, each with a line saying what it does: the daily move for a stock (5%), for a commodity (5% in a day, 20% in a month), for a currency (1%), how close to its five-year high a commodity has to be (2%), and the macro moves. Change a number, commit, and the next run uses it.

## Where AI comes in

Only in two places, and both are optional. When you build your list, an AI can read each annual report once and tell you what each company buys and sells. And when a press release is laid out in a way the code cannot read, you can add an `OPENROUTER_API_KEY` secret, and a cheap model is asked for that one sentence. The program keeps the sentence only if it is word for word in the release, and the message says it was read by the model.

## Limits

- Results reading works on most US releases. When the code cannot find your words, the message says so and gives you the link.
- Companies listed outside the US do not file with the SEC, so they get the price, exposure and headline checks but no results check.
- Some commodities have no free daily price. Uranium and a few others come from a monthly series that runs two to three months behind, and the message says so. The ones with only a paid source are not watched.
- Yahoo Finance's price data is free but unofficial, and it can change without notice.
- This program sends information. It does not tell you what to buy or sell, and it places no orders.

## Run it on your own computer instead

If you would rather not use GitHub, it also runs on your own computer with Python and no installs: set the same settings as environment variables and run `python watch.py`. It only checks while the computer is on, so you need a scheduler (Task Scheduler on Windows, launchd or cron on a Mac) to run it every hour.

Other ways to run it by hand:

- `python watch.py --dry-run` prints the messages instead of sending them.
- `python watch.py --digest` adds the morning calendar and headlines now.
- `python watch.py --replay ACN` re-reads Accenture's latest results and sends them again.
- `python watch.py --chat-id` prints your chat ID after you message your bot.

## Credits and licence

The commodity and currency map in `data/commodities.json` comes from [GreekSoup](https://github.com/shubhamsborkar/greeksoup), the open-source one-person equity research desk, under the MIT licence. This program is MIT licensed too: copy it, change it and build on it. It is shared as it is, with no promise of updates.

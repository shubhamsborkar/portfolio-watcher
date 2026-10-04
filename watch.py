"""
Portfolio watcher.

Every hour it checks, for every holding on your watchlist:

  1. Results     a new results filing at the SEC (form 8-K, item 2.02). It opens the
                 press release, finds the number you wrote down, and checks it against
                 your line.
  2. Price       a big daily move in the stock.
  3. Exposures   the commodities and currencies each holding buys or sells (crude,
                 copper, gold, the euro ...): a big move, and which way it cuts.
  4. Macro       a big move in rates, the VIX, credit spreads or the dollar.

Once a day, in the morning run, it also sends:

  5. Calendar    today's high-impact US releases (CPI, jobs, the Fed).
  6. Headlines   the latest headlines for the words you chose (a war, a strait, a tariff,
                 a product), one line each.

Every alert fires once a day at most. No AI runs in the hourly check: it is plain code
reading free public data. If a press release cannot be read by code and you have added an
OpenRouter key, a cheap model is asked for that one sentence, and the program keeps it
only if the sentence is really in the release.

Settings (GitHub repository secrets, or environment variables on your computer):
  TELEGRAM_TOKEN      the token @BotFather gave you
  TELEGRAM_CHAT_ID    your chat ID (run: python watch.py --chat-id)
  SEC_EMAIL           your email; the SEC asks every program to say who is calling
  OPENROUTER_API_KEY  optional, only for releases code cannot read
  OPENROUTER_MODEL    optional, default openai/gpt-6-luna

Run it by hand:
  python watch.py                    the hourly check: message only what is new
  python watch.py --dry-run          print the messages instead of sending them
  python watch.py --digest           add the morning calendar and headlines now
  python watch.py --replay ACN       re-read ACN's latest results and message them again
  python watch.py --exposures UBER   list the commodity and currency words in UBER's annual report
  python watch.py --chat-id          print the chat ID of whoever last messaged your bot

The commodity and currency map in data/commodities.json comes from GreekSoup
(github.com/shubhamsborkar/greeksoup, MIT licence).
"""

import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.environ.get("WATCHLIST") or os.path.join(HERE, "watchlist.csv")
STATE = os.environ.get("STATE") or os.path.join(HERE, "state.json")
COMMODITIES = os.path.join(HERE, "data", "commodities.json")

# ----------------------------------------------------------------------------- your thresholds
# Change any number here. Each alert fires once a day at most.

STOCK_DAY_MOVE = 5.0          # % a holding moves in a day
COMMODITY_DAY_MOVE = 5.0      # % a commodity moves in a day
COMMODITY_MONTH_MOVE = 20.0   # % a commodity moves in a month
CURRENCY_DAY_MOVE = 1.0       # % a currency pair moves in a day (currencies move far less)
NEAR_FIVE_YEAR_HIGH = 2.0     # a commodity within this % of its five-year high
DIGEST_HOUR_UTC = 11          # the morning run (11:00 UTC is 7:00 in New York)
RESULTS_LOOKBACK_DAYS = 3     # a filing older than this is never messaged
HEADLINES_PER_WORD = 3

# Macro series from FRED (the St. Louis Fed's free database). "change" fires when the last
# reading moved at least this much against the reading `days` rows earlier; "above" fires
# when the reading is above the number.
MACRO = [
    ("DGS10", "10-year Treasury yield", "change", 0.15, 1, "pp"),
    ("DGS2", "2-year Treasury yield", "change", 0.15, 1, "pp"),
    ("T10Y2Y", "2s10s curve", "change", 0.15, 1, "pp"),
    ("VIXCLS", "VIX", "above", 25, 0, ""),
    ("BAMLH0A0HYM2", "High-yield credit spread", "change", 0.40, 5, "pp"),
    ("DTWEXBGS", "Dollar index", "change_pct", 1.0, 1, "%"),
]

BROWSERS = [  # Yahoo answers ordinary browsers; when one is throttled the next is tried
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


# ----------------------------------------------------------------------------- fetching

def fetch(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": BROWSERS[0]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def sec_get(url):
    email = os.environ.get("SEC_EMAIL", "").strip()
    if not email:
        sys.exit("SEC_EMAIL is not set. The SEC refuses programs that do not say who is calling.")
    for attempt in range(3):
        try:
            text = fetch(url, {"User-Agent": f"portfolio-watcher {email}"})
            time.sleep(0.15)  # well under the SEC's limit of 10 requests a second
            return text
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"EDGAR did not answer {url}: {e}")
            time.sleep(3)


def yahoo(symbol, rng="5y"):
    """Daily closes [(date, close)] for a stock, commodity future or currency pair."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={rng}&interval=1d"
    for ua in BROWSERS:
        try:
            res = json.loads(fetch(url, {"User-Agent": ua}))["chart"]["result"][0]
            closes = res["indicators"]["quote"][0]["close"]
            out = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), c)
                   for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
            live = res["meta"].get("regularMarketPrice")
            if out and live:
                out[-1] = (out[-1][0], live)
            return out
        except Exception:
            time.sleep(1)
    return []


def fred(series):
    """[(date, value)] from FRED. FRED stalls Python's own web requests but serves curl."""
    try:
        r = subprocess.run(["curl", "-s", "-m", "25", f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"],
                           capture_output=True, text=True, timeout=30)
        out = []
        for line in r.stdout.strip().splitlines()[1:]:
            d, _, v = line.partition(",")
            if v.strip() not in ("", "."):
                out.append((d, float(v)))
        return out
    except Exception:
        return []


def pct(a, b):
    return (a / b - 1) * 100 if b else 0.0


# ----------------------------------------------------------------------------- watchlist and state

def read_watchlist():
    with open(WATCHLIST, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("ticker") or "").strip()]
    for r in rows:
        r["ticker"] = r["ticker"].strip().upper()
        r["exposures"] = [e.strip() for e in (r.get("exposures") or "").split(";") if ":" in e]
        r["keywords"] = [k.strip() for k in (r.get("keywords") or "").split(";") if k.strip()]
    return rows


def load_state():
    try:
        with open(STATE) as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        s = {}
    s.setdefault("filings", [])
    s.setdefault("fired", {})
    s.setdefault("headlines", [])
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    s["fired"] = {k: v for k, v in s["fired"].items() if v >= week_ago}
    s["today"] = datetime.now(timezone.utc).date().isoformat()
    return s


def save_state(s):
    s = {k: v for k, v in s.items() if k != "today"}
    s["filings"] = s["filings"][-500:]
    s["headlines"] = s["headlines"][-1000:]
    with open(STATE, "w") as fh:
        json.dump(s, fh, indent=0)


def first_today(state, key):
    """True the first time an alert fires today; False after that."""
    if state["fired"].get(key) == state["today"]:
        return False
    state["fired"][key] = state["today"]
    return True


# ----------------------------------------------------------------------------- 1. results

def ticker_to_cik():
    data = json.loads(sec_get("https://www.sec.gov/files/company_tickers.json"))
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


def results_filings(cik):
    recent = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        items = [x.strip() for x in (recent["items"][i] or "").split(",")]
        if form in ("8-K", "8-K/A") and "2.02" in items:
            out.append({"accession": recent["accessionNumber"][i], "date": recent["filingDate"][i],
                        "accepted": recent["acceptanceDateTime"][i]})
    return out


def release_url(cik, accession):
    """The press release is the 8-K's exhibit 99 (99.1 at most companies)."""
    folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    index = sec_get(folder + f"{accession}-index.html")
    best = None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4 and cells[3].upper().startswith("EX-99"):
            if best is None or cells[3].upper() in ("EX-99.1", "EX-99"):
                best = folder + cells[2].split()[0]
            if cells[3].upper() in ("EX-99.1", "EX-99"):
                break
    return best, folder


def page_text(raw_html):
    raw_html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw_html)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw_html))).strip()


NUMBER = re.compile(r"\(?-?\$?\s?\d[\d,]*(?:\.\d+)?\)?\s?(?:%|percent|million|billion|thousand)?")
SENTENCE_END = re.compile(r"[.;]\s+(?=[A-Z•])|•\s")  # "U.S. dollars" is not the end of a sentence


def to_float(token):
    neg = token.strip().startswith(("(", "-"))
    value = float(re.sub(r"[^\d.]", "", token))
    return -value if neg else value


def sentence_around(text, start, end):
    left = max(0, start - 200)
    for m in SENTENCE_END.finditer(text, left, start):
        left = m.end()
    m = SENTENCE_END.search(text, end)
    return text[left:m.start() + 1 if m else len(text)].strip(" •")[:400]


def phrase_pattern(look_for):
    """Your words, where "..." stands for any few words in between."""
    parts = [re.escape(p.strip()) for p in look_for.split("...") if p.strip()]
    return re.compile(r"[^.]{0,80}?".join(parts), re.I)


def find_number(text, look_for):
    """The first number after the words you wrote down, as written, and its sentence."""
    for m in phrase_pattern(look_for).finditer(text):
        n = NUMBER.search(text[m.end():m.end() + 160])
        if n and re.search(r"\d", n.group()):
            return to_float(n.group()), n.group().strip(), sentence_around(text, m.start(), m.end() + n.end())
    return None, None, None


def ask_model(text, look_for):
    """Fallback only: a cheap model quotes the sentence; kept only if the release contains it."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None, None, None
    prompt = (f"Below is a company's results press release. Copy, word for word, the one sentence "
              f"that gives this figure: {look_for}. Reply with the sentence only, or NONE.\n\n{text[:60000]}")
    body = json.dumps({"model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-6-luna"),
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            quote = json.loads(r.read())["choices"][0]["message"]["content"].strip().strip('"')
    except Exception as e:
        print(f"  the model fallback failed: {e}")
        return None, None, None
    if quote == "NONE" or quote not in text:
        return None, None, None
    value, as_written, _ = find_number(quote, look_for)
    return value, as_written, quote


TESTS = [("at least", lambda v, bar: v >= bar), ("at most", lambda v, bar: v <= bar),
         ("above", lambda v, bar: v > bar), ("below", lambda v, bar: v < bar)]


def judge(value, test):
    test = (test or "").strip().lower()
    for words, check in TESTS:
        if test.startswith(words):
            bar = float(re.sub(r"[^\d.\-]", "", test[len(words):]))
            return "PASSED" if check(value, bar) else "MISSED"
    return None


def results_message(row, filing, url, text):
    lines = [f"RESULTS: {row['ticker']} filed its results on {filing['date']}."]
    look_for, test = (row.get("look_for") or "").strip(), (row.get("test") or "").strip()
    if look_for:
        value, as_written, quote = find_number(text, look_for)
        how = "read by code"
        if value is None:
            value, as_written, quote = ask_model(text, look_for)
            how = "read by the model, checked against the release"
        if value is None:
            lines.append(f"Could not find \"{look_for}\" in the release. Open it and read it yourself.")
        else:
            verdict = judge(value, test)
            lines.append(f"Your line: \"{look_for}\" {test}".rstrip())
            lines.append(f"The release says {as_written}" + (f": {verdict}" if verdict else "") + f" ({how})")
            lines.append(f"\"{quote}\"")
    if (row.get("note") or "").strip():
        lines.append(f"Your note: {row['note'].strip()}")
    lines.append(url)
    return "\n".join(lines)


def check_results(rows, state, replay=False):
    messages, ciks = [], ticker_to_cik()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RESULTS_LOOKBACK_DAYS)
    for row in rows:
        cik = ciks.get(row["ticker"])
        if not cik:
            continue  # not filed with the SEC (a listing outside the US)
        filings = results_filings(cik)
        if replay:
            filings = filings[:1]
        else:
            filings = [f for f in filings if f["accession"] not in state["filings"]
                       and datetime.fromisoformat(f["accepted"].replace("Z", "+00:00")) >= cutoff]
        for f in filings:
            url, folder = release_url(cik, f["accession"])
            text = page_text(sec_get(url)) if url else ""
            msg = results_message(row, f, url or folder, text)
            messages.append(("REPLAY of a past filing. " + msg) if replay else msg)
            if not replay:
                state["filings"].append(f["accession"])
    return messages


# ----------------------------------------------------------------------------- 2. price

def check_prices(rows, state):
    lines = []
    for row in rows:
        series = yahoo(row.get("yahoo") or row["ticker"], "5d")
        if len(series) < 2:
            continue
        move = pct(series[-1][1], series[-2][1])
        day = series[-1][0]
        if abs(move) >= STOCK_DAY_MOVE and first_today(state, f"price|{row['ticker']}|{day}"):
            lines.append(f"{row['ticker']} {move:+.1f}% on {day}, at {series[-1][1]:,.2f}.")
    return lines


# ----------------------------------------------------------------------------- 3. exposures

def load_commodities():
    with open(COMMODITIES) as fh:
        return {c["id"]: c for c in json.load(fh)["commodities"]}


def commodity_read(c):
    """(level, day %, month %, % off the five-year high, how) for one commodity or currency."""
    src = c.get("sources", {})
    if src.get("yahoo"):
        s = yahoo(src["yahoo"], "5y")
        if len(s) >= 22:
            last, prev, month = s[-1][1], s[-2][1], s[-22][1]
            return last, pct(last, prev), pct(last, month), pct(last, max(v for _, v in s)), "daily", s[-1][0]
    if src.get("fred"):
        s = fred(src["fred"])  # monthly, two to three months behind
        if len(s) >= 2:
            return s[-1][1], None, pct(s[-1][1], s[-2][1]), None, f"monthly, last reading {s[-1][0]}", s[-1][0]
    return None


def check_exposures(rows, state):
    book = load_commodities()
    held = {}
    for row in rows:
        for e in row["exposures"]:
            cid, _, side = e.partition(":")
            held.setdefault(cid.strip(), []).append((row["ticker"], side.strip().lower()))
    lines = []
    for cid, who in sorted(held.items()):
        c = book.get(cid)
        if not c:
            lines.append(f"(\"{cid}\" is not in data/commodities.json; check the spelling.)")
            continue
        r = commodity_read(c)
        if not r:
            continue
        level, day, month, off_high, how, when = r
        is_fx = c.get("group") == "Currency"
        hits = []
        if day is not None and abs(day) >= (CURRENCY_DAY_MOVE if is_fx else COMMODITY_DAY_MOVE):
            hits.append(("day", day, f"{day:+.1f}% on {when}"))
        if month is not None and abs(month) >= COMMODITY_MONTH_MOVE:
            hits.append(("month", month, f"{month:+.1f}% in a month"))
        if off_high is not None and not is_fx and off_high >= -NEAR_FIVE_YEAR_HIGH:
            hits.append(("peak", 1, "at or near its five-year high"))
        for kind, move, words in hits:
            if not first_today(state, f"{kind}|{cid}|{when}"):
                continue
            cut = [f"{t} ({side}, {'helps' if (side == 'revenue') == (move > 0) else 'hurts'})" for t, side in who]
            lines.append(f"{c['label']} {words}, at {level:,.2f} {c.get('unit', '')}. "
                         f"Your names: {', '.join(cut)}." + (f" [{how}]" if how != "daily" else ""))
    return lines


# ----------------------------------------------------------------------------- 4. macro

def check_macro(state):
    lines = []
    for sid, label, rule, bar, days, unit in MACRO:
        s = fred(sid)
        if len(s) <= days:
            continue
        last = s[-1][1]
        if rule == "above":
            hit, words = last > bar, f"at {last:.2f}, above {bar}"
        else:
            then = s[-1 - days][1]
            change = pct(last, then) if rule == "change_pct" else last - then
            span = "a day" if days == 1 else f"{days} trading days"
            hit, words = abs(change) >= bar, f"{change:+.2f}{unit} in {span}, now {last:.2f}"
        if hit and first_today(state, f"macro|{sid}|{s[-1][0]}"):
            lines.append(f"{label} {words} (FRED, {s[-1][0]}).")
    return lines


# ----------------------------------------------------------------------------- 5 and 6. the morning digest

def calendar_today():
    try:
        week = json.loads(fetch("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    except Exception:
        return ["(The economic calendar did not answer this morning.)"]
    today = datetime.now(timezone(timedelta(hours=-4))).date().isoformat()
    out = []
    for e in week:
        if e.get("country") == "USD" and e.get("impact") == "High" and e.get("date", "").startswith(today):
            extra = ", ".join(x for x in (f"forecast {e['forecast']}" if e.get("forecast") else "",
                                          f"previous {e['previous']}" if e.get("previous") else "") if x)
            out.append(f"{e['date'][11:16]} New York: {e['title']}" + (f" ({extra})" if extra else ""))
    return out


def headlines(rows, state):
    words = []
    for row in rows:
        words += [k for k in row["keywords"] if k not in words]
    out = []
    for k in words:
        q = urllib.parse.quote(f"\"{k}\" when:1d")
        try:
            feed = fetch(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        except Exception:
            continue
        titles = [html.unescape(t) for t in re.findall(r"<item>.*?<title>(.*?)</title>", feed, re.S)]
        plain = k.lower().replace("'", "\u2019")  # the word must be in the headline itself
        fresh = [t for t in titles if t not in state["headlines"]
                 and (k.lower() in t.lower() or plain in t.lower())][:HEADLINES_PER_WORD]
        if fresh:
            who = [r["ticker"] for r in rows if k in r["keywords"]]
            out.append(f"\"{k}\" ({', '.join(who)}):")
            out += [f"  {t}" for t in fresh]
            state["headlines"] += fresh
        time.sleep(1)
    return out


# ----------------------------------------------------------------------------- 10-K helper

EXPOSURE_WORDS = {
    "wti": ["crude oil", "oil prices", "fuel prices", "fuel costs", "gasoline"], "natgas_us": ["natural gas"],
    "copper": ["copper"], "aluminium": ["aluminum", "aluminium"], "gold": ["gold"], "silver": ["silver"],
    "lithium": ["lithium"], "hrc_us": ["steel"], "wheat": ["wheat"], "corn": ["corn"], "sugar": ["sugar"],
    "coffee": ["coffee"], "cocoa": ["cocoa"], "cotton": ["cotton"], "uranium": ["uranium"],
    "polypropylene": ["resin", "plastics"], "eurusd": ["euro"], "gbpusd": ["british pound", "pound sterling"],
    "usdjpy": ["japanese yen"], "usdcny": ["chinese yuan", "renminbi"], "usdinr": ["indian rupee"],
}


def exposure_words(ticker):
    """Which commodities and currencies the latest annual report talks about. Code only: it
    counts words; you (or Claude, once) decide what is a real cost or revenue exposure."""
    cik = ticker_to_cik().get(ticker.upper())
    if not cik:
        sys.exit(f"{ticker} has no SEC filings.")
    recent = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
    i = next((i for i, f in enumerate(recent["form"]) if f in ("10-K", "20-F", "40-F")), None)
    if i is None:
        sys.exit(f"No annual report found for {ticker}.")
    acc = recent["accessionNumber"][i]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}"
    text = page_text(sec_get(url))
    print(f"{ticker} {recent['form'][i]} filed {recent['filingDate'][i]}: {url}\n")
    for cid, terms in EXPOSURE_WORDS.items():
        hits = [m for t in terms for m in re.finditer(r"\b" + re.escape(t) + r"\b", text, re.I)]
        if hits:
            m = hits[0]
            print(f"{cid:13} {len(hits):3} mentions  \"...{text[max(0, m.start() - 150):m.end() + 150]}...\"\n")


# ----------------------------------------------------------------------------- Telegram

def telegram(text, dry_run):
    if dry_run:
        print("\n----- message -----\n" + text + "\n-------------------")
        return
    token, chat = os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is not set.")
    for part in [text[i:i + 3900] for i in range(0, len(text), 3900)]:  # Telegram's limit is 4,096
        body = json.dumps({"chat_id": chat, "text": part, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()


def print_chat_id():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    updates = json.loads(fetch(f"https://api.telegram.org/bot{token}/getUpdates")).get("result", [])
    if not updates:
        sys.exit("No messages yet. Send your bot any message in Telegram, then run this again.")
    chat = (updates[-1].get("message") or updates[-1].get("channel_post") or {}).get("chat", {})
    print(f"Your chat ID is {chat.get('id')}")


# ----------------------------------------------------------------------------- the run

def main(argv):
    dry_run = "--dry-run" in argv
    if "--chat-id" in argv:
        return print_chat_id()
    if "--exposures" in argv:
        return exposure_words(argv[argv.index("--exposures") + 1])

    first_run = not os.path.exists(STATE)
    rows, state = read_watchlist(), load_state()

    if "--replay" in argv:
        t = argv[argv.index("--replay") + 1].upper()
        picked = [r for r in rows if r["ticker"] == t] or [{"ticker": t, "exposures": [], "keywords": []}]
        for m in check_results(picked, state, replay=True):
            telegram(m, dry_run)
        return

    if first_run:
        names = ", ".join(r["ticker"] for r in rows)
        telegram(f"The watcher is running. It is watching {len(rows)} names: {names}. "
                 f"You will hear from it when something moves.", dry_run)
    for m in check_results(rows, state):
        telegram(m, dry_run)

    sections = [("PRICES", check_prices(rows, state)),
                ("COMMODITIES AND CURRENCIES", check_exposures(rows, state)),
                ("MACRO", check_macro(state))]
    now = datetime.now(timezone.utc)
    if "--digest" in argv or (now.hour == DIGEST_HOUR_UTC and first_today(state, "digest")):
        sections += [("TODAY'S CALENDAR", calendar_today() or ["No high-impact US releases today."]),
                     ("HEADLINES", headlines(rows, state))]
    body = "\n\n".join(f"{name}\n" + "\n".join(lines) for name, lines in sections if lines)
    if body:
        telegram(body, dry_run)

    if not dry_run:
        save_state(state)
    print(f"Checked {len(rows)} name{'s' if len(rows) != 1 else ''} at {now:%Y-%m-%d %H:%M} UTC.")


if __name__ == "__main__":
    main(sys.argv[1:])

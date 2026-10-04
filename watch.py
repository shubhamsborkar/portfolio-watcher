"""
Portfolio watcher.

Twice a day on weekdays (before the market opens and after it closes) it checks every
holding on your watchlist and sends you ONE short message, and only when something matters:

  1. Results     a new results filing at the SEC (form 8-K, item 2.02). It opens the press
                 release, finds the number you wrote down, and checks it against your line.
  2. Big moves   a holding that moved 5% or more in a day.
  3. What your   a commodity, currency or rate your holdings depend on breaking out of its
     portfolio   range: a new three-month high or low, with the range for context and the
     depends on  names in your portfolio that buy it, sell it or borrow against it.
  4. Morning     the day's high-impact US releases (CPI, jobs, the Fed) and the top headline
                 for your first few holdings.

A quiet day sends nothing. The first run sends a map of how your holdings connect.

No AI runs in the check: it is plain code reading free public data. If a press release
cannot be read by code and you have added an OpenRouter key, a cheap model is asked for
that one sentence, and the program keeps it only if the sentence is really in the release.

Settings (GitHub repository secrets, or environment variables on your computer):
  TELEGRAM_TOKEN      the token @BotFather gave you
  TELEGRAM_CHAT_ID    your chat ID (run: python watch.py --chat-id)
  SEC_EMAIL           your email; the SEC asks every program to say who is calling
  OPENROUTER_API_KEY  optional, only for releases code cannot read
  OPENROUTER_MODEL    optional, default openai/gpt-6-luna

Run it by hand:
  python watch.py                    the check: message only what is new
  python watch.py --dry-run          print the message instead of sending it
  python watch.py --morning          include the calendar and headlines now
  python watch.py --map              send the map of how your holdings connect
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
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.environ.get("WATCHLIST") or os.path.join(HERE, "watchlist.csv")
STATE = os.environ.get("STATE") or os.path.join(HERE, "state.json")
COMMODITIES = os.path.join(HERE, "data", "commodities.json")

# ----------------------------------------------------------------------------- your thresholds
# Change any number here.

STOCK_DAY_MOVE = 5.0          # % a holding moves in a day
RANGE_DAYS = 63               # a breakout means a new high or low over this many trading days (about three months)
NEAR_FIVE_YEAR_HIGH = 2.0     # a commodity within this % of its five-year high
QUIET_DAYS = 5                # once an item has fired, it stays quiet this many days
RESULTS_LOOKBACK_DAYS = 3     # a filing older than this is never messaged
HEADLINES_PER_HOLDING = 1
HEADLINES_IN_TOTAL = 3        # taken from the top of your watchlist down, so put your main holdings first

# Rates and markets from FRED (the St. Louis Fed's free database): a new three-month high or
# low fires, and the VIX fires when it crosses above 25. The last field says why it matters.
MACRO = [
    ("DGS10", "10-year Treasury yield", "%",
     "Long-term borrowing costs. A higher yield usually weighs most on companies valued on profits far in the future."),
    ("DGS2", "2-year Treasury yield", "%",
     "This yield moves with what the market expects the Fed to do next."),
    ("BAMLH0A0HYM2", "High-yield credit spread", "%",
     "How much extra lenders want to hold riskier company debt. Wider means more caution."),
    ("DTWEXBGS", "US dollar index", "",
     "A stronger dollar shrinks what US companies earn abroad once it is converted back."),
    ("VIXCLS", "VIX", "",
     "The market's expected swing in the S&P 500 over the next month. Above 25 is a nervous market."),
]

# Sites that publish machine-made stock pages rather than news. Add any you do not want.
NOISY_SOURCES = ["Stock Traders Daily", "IndexBox", "MEXC", "TradingView", "MarketBeat", "ChartMill",
                 "Yahoo Finance Singapore", "Yahoo! Finance Canada", "GuruFocus", "Simply Wall St", "simplywall", "AD HOC NEWS"]

BROWSERS = [  # Yahoo answers ordinary browsers; when one is throttled the next is tried
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


# ----------------------------------------------------------------------------- small helpers

def esc(text):
    return html.escape(str(text), quote=False)


def nice_date(iso):
    """2026-10-02 -> 2 Oct 2026"""
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b %Y}"


def pct(a, b):
    return (a / b - 1) * 100 if b else 0.0


def link(url, words):
    return f'<a href="{html.escape(url)}">{esc(words)}</a>'


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


_YAHOO = {}


def yahoo(symbol, rng="5y"):
    """Daily closes [(date, close)] for a stock, commodity future or currency pair (cached per run)."""
    if (symbol, rng) not in _YAHOO:
        _YAHOO[(symbol, rng)] = _yahoo(symbol, rng)
    return _YAHOO[(symbol, rng)]


def _yahoo(symbol, rng):
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


# ----------------------------------------------------------------------------- watchlist, broker and state

def read_watchlist():
    rows = []
    if os.path.exists(WATCHLIST):
        with open(WATCHLIST, newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("ticker") or "").strip()]
    for r in rows:
        r["ticker"] = r["ticker"].strip().upper()
        r["exposures"] = [e.strip() for e in (r.get("exposures") or "").split(";") if ":" in e]
        r["keywords"] = [k.strip() for k in (r.get("keywords") or "").split(";") if k.strip()]
    return rows


def broker_holdings():
    """[(ticker, yahoo symbol, market value)] read from your broker, when BROKER is set; [] when it is not.
    The broker files come from GreekSoup's broker layer; they only read, they never trade."""
    bid = (os.environ.get("BROKER") or "").strip().lower()
    if not bid:
        return []
    import brokers  # needs the requests library; the GitHub workflow installs it
    module = brokers.load(bid)
    if not module:
        sys.exit(f"BROKER is set to \"{bid}\", which the watcher does not know. "
                 f"The ones it knows: {', '.join(brokers.REGISTRY)}.")
    client = module.connect(brokers.config(bid))
    out = []
    for row in module.equity(client):
        ysym = (row.get("ysym") or row.get("code") or "").strip()
        ticker = ysym.split(".")[0].upper() if ysym.endswith((".NS", ".BO", ".L", ".TO")) else ysym.upper()
        if ticker and (row.get("qty") or 0):
            out.append((ticker, ysym, row.get("value") or 0))
    return out


def portfolio(rows):
    """The names to watch: everything your broker holds, plus anything else on your list.
    The list's columns (your line, exposures, headline words) apply to a broker holding
    with the same ticker."""
    held = broker_holdings()
    if not held:
        return rows, ""
    by_ticker = {r["ticker"]: r for r in rows}
    merged = []
    for ticker, ysym, value in held:
        row = by_ticker.pop(ticker, {"ticker": ticker, "exposures": [], "keywords": []})
        row["value"] = value
        if ysym and ysym.upper() != ticker:
            row["yahoo"] = ysym
        row["held"] = True
        merged.append(row)
    merged += list(by_ticker.values())  # the rest of your list: names you watch but do not hold
    return merged, f"{len(held)} from your broker and {len(merged) - len(held)} more from your list"


def load_state():
    try:
        with open(STATE) as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        s = {}
    s.setdefault("filings", [])
    s.setdefault("fired", {})
    s.setdefault("headlines", [])
    week_ago = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
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


def quiet_since(state, key):
    """True if this item has not fired in the last QUIET_DAYS days; marks it as fired."""
    last = state["fired"].get(key)
    if last and (date.fromisoformat(state["today"]) - date.fromisoformat(last)).days < QUIET_DAYS:
        return False
    state["fired"][key] = state["today"]
    return True


# ----------------------------------------------------------------------------- the SEC's company list

_COMPANIES = {}


def companies():
    """{ticker: (cik, name)} from the SEC's own list, fetched once per run."""
    if not _COMPANIES:
        data = json.loads(sec_get("https://www.sec.gov/files/company_tickers.json"))
        for v in data.values():
            _COMPANIES[v["ticker"].upper()] = (int(v["cik_str"]), v["title"])
    return _COMPANIES


def name_of(ticker):
    """Accenture plc (ACN): the SEC's own company name, tidied, with the ticker."""
    entry = companies().get(ticker)
    if not entry:
        return ticker
    raw = re.sub(r"\s*/.*$|\s+A[/ ]S$", "", entry[1].strip())
    raw = re.sub(r"(?i),?\s+(inc|corp|corporation|ltd|limited|plc|n\.v|s\.a|co|holdings|group holding|athletica inc)\.?$", "", raw)
    raw = re.sub(r"(?i),?\s+(inc|corp|athletica)\.?$", "", raw)
    if raw.isupper():  # PTC stays PTC; UBER TECHNOLOGIES becomes Uber Technologies
        raw = " ".join(w if len(w) <= 3 else w.title() for w in raw.split())
    words = raw
    return ticker if words.upper() == ticker else f"{words} ({ticker})"


# ----------------------------------------------------------------------------- 1. results

def results_filings(cik):
    recent = submissions(cik)
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
    if not best:  # no press release attached: link the 8-K's own page, never the folder of files
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) >= 4 and cells[3].upper().startswith("8-K") and cells[2].lower().endswith((".htm", ".html")):
                return None, folder + cells[2].split()[0]
    return best, folder


def page_text(raw_html):
    raw_html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw_html)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw_html))).strip()


NUMBER = re.compile(r"\(?-?\$?\s?\d[\d,]*(?:\.\d+)?\)?\s?(?:%|percent|million|billion|thousand)?")
SENTENCE_END = re.compile(r"[.;]\s+(?=[A-Z•◦])|[•◦]\s|\so\s(?=[A-Z])")  # "U.S. dollars" is not the end of a sentence; •, ◦ and "o" are bullets


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


HIGHLIGHTS = [  # what a holder reads first in a results release; the figure must follow the word closely
    ("Revenue", re.compile(r"\b(revenues?|net sales|total sales)\b(?:(?!guidance|outlook)[^.$%]){0,60}?(\$\s?\d|\d\s?(%|percent))", re.I)),
    ("Earnings per share", re.compile(r"\b(EPS|earnings per (diluted )?share)\b(?:(?!guidance|outlook)[^.$]){0,40}?\$\s?\d", re.I)),
    ("Outlook", re.compile(r"\b(expects?|outlook|guidance)\b[^.]{0,80}?(\$\s?\d|\d\s?(%|percent))", re.I)),
]
CLAUSE_START = re.compile(r"(?<![\w-])(For|In|The|Our|Total|Revenues?|Net|Diluted|GAAP|Non-GAAP|Adjusted|Company|Full|Fourth|Third|Second|First)\b")


def highlights(text):
    """[(label, quote)]: the first sentence in the release where revenue, earnings per share and the
    outlook each come with a figure. Quoted word for word, so nothing is computed or reworded; a
    release laid out only as tables gives fewer lines, and the message says so."""
    head = text[:len(text) // 2]  # the narrative sits before the financial tables
    sentences, start = [], 0
    for m in SENTENCE_END.finditer(head):
        sentences.append(head[start:m.start() + 1].strip(" •◦o"))
        start = m.end()
    out, used = [], set()
    for label, pattern in HIGHLIGHTS:
        for sent in sentences:
            hit = pattern.search(sent)
            if (not hit or sent in used or len(re.findall(r"\d[\d,.]*", sent)) > 12
                    or re.search(r"forward-looking|safe harbor|“|\"", sent)):
                continue
            quote = sent
            if hit.start() > 50:  # a run-on line: start at the clause that holds the figure
                starts = [m.start() for m in CLAUSE_START.finditer(sent, 0, hit.start() + 1)]
                quote = sent[starts[-1]:] if starts else sent[hit.start():]
            if 30 <= len(quote) <= 320:
                out.append((label, quote))
                used.add(sent)
                break
    return out


TESTS = [("at least", lambda v, bar: v >= bar), ("at most", lambda v, bar: v <= bar),
         ("above", lambda v, bar: v > bar), ("below", lambda v, bar: v < bar)]


def judge(value, test):
    test = (test or "").strip().lower()
    for words, check in TESTS:
        if test.startswith(words):
            bar = float(re.sub(r"[^\d.\-]", "", test[len(words):]))
            return "Passed your line" if check(value, bar) else "Missed your line"
    return None


def results_message(row, filing, url, text, replay):
    head = "📄 <b>Results filed: " + esc(name_of(row["ticker"])) + "</b>"
    lines = [head, f"Filed with the SEC on {nice_date(filing['date'])}."
             + (" <i>(A replay of a past filing.)</i>" if replay else ""), ""]
    look_for, test = (row.get("look_for") or "").strip(), (row.get("test") or "").strip()
    shown = None
    if look_for:
        value, as_written, quote = find_number(text, look_for)
        how = ""
        if value is None:
            value, as_written, quote = ask_model(text, look_for)
            how = " <i>(read by a model and checked word for word against the release)</i>"
        if value is None:
            lines.append(f"I could not find \"{esc(look_for)}\" in the release, so this one needs your own read.")
        else:
            verdict = judge(value, test)
            lines.append(f"<b>{esc(as_written)}</b>" + (f": {verdict} ({esc(test)})." if verdict else ".") + how)
            lines.append(f"<i>\"{esc(quote)}\"</i>")
            lines.append("")
            shown = quote
    found = [(label, q) for label, q in highlights(text) if q != shown]  # never quote the same line twice
    if found:
        lines += ["<b>From the release</b>"] + [f"• <b>{label}:</b> <i>\"{esc(sent)}\"</i>" for label, sent in found]
    elif not look_for:
        lines.append("The release is laid out as tables, so open it for the figures.")
    if (row.get("note") or "").strip():
        lines += ["", f"Your note: {esc(row['note'].strip())}"]
    lines += ["", link(url, "Read the release")]
    return "\n".join(lines)


def check_results(rows, state, replay=False):
    messages = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RESULTS_LOOKBACK_DAYS)
    for row in rows:
        entry = companies().get(row["ticker"])
        if not entry:
            continue  # not filed with the SEC (a listing outside the US)
        cik = entry[0]
        filings = results_filings(cik)
        if replay:
            filings = filings[:1]
        else:
            filings = [f for f in filings if f["accession"] not in state["filings"]
                       and datetime.fromisoformat(f["accepted"].replace("Z", "+00:00")) >= cutoff]
        for f in filings:
            url, folder = release_url(cik, f["accession"])
            text = page_text(sec_get(url)) if url else ""
            messages.append(results_message(row, f, url or folder, text, replay))
            if not replay:
                state["filings"].append(f["accession"])
    return messages


# ----------------------------------------------------------------------------- 1b. every other filing that matters

ITEMS_8K = {  # the 8-K items a holder wants to hear about, in plain words
    "1.01": "signed a major agreement", "1.02": "ended a major agreement", "1.03": "filed for bankruptcy",
    "1.05": "disclosed a cybersecurity incident", "2.01": "completed an acquisition or a sale of assets",
    "2.03": "took on a major new debt or obligation", "2.04": "had a debt obligation accelerated",
    "2.05": "announced restructuring or exit costs", "2.06": "booked an impairment (a write-down)",
    "3.01": "received a delisting notice", "3.02": "sold shares outside a public offering",
    "4.01": "changed its auditor", "4.02": "said earlier financial statements can no longer be relied on",
    "5.01": "had a change in control", "5.02": "had a director or senior officer join or leave",
    "5.03": "changed its bylaws or fiscal year", "7.01": "published a disclosure to investors (often guidance or a presentation)",
    "8.01": "reported another event it considers important",
}
_SUBMISSIONS = {}


def submissions(cik):
    """The company's recent filings at the SEC, fetched once per run."""
    if cik not in _SUBMISSIONS:
        _SUBMISSIONS[cik] = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
    return _SUBMISSIONS[cik]


def doc_url(cik, accession, document):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"


def money(v):
    return f"${v / 1e9:,.1f}bn" if v >= 1e9 else f"${v / 1e6:,.1f}m" if v >= 1e6 else f"${v:,.0f}"


ROLES = {"chief executive officer": "CEO", "chief financial officer": "CFO", "chief operating officer": "COO",
         "chairman": "Chair", "president": "President"}


def insider_trade(cik, accession, document):
    """One Form 4 about this company: (who, role, bought $, sold $, under a pre-set plan).
    Only open-market buys (P) and sales (S) count; grants, option exercises and tax withholding do not.
    None when the filing is about a different company (a holding can itself be an insider elsewhere)."""
    raw = document.split("/")[-1]  # the SEC renders xslF345X06/x.xml as a page; the data is x.xml
    try:
        x = sec_get(doc_url(cik, accession, raw))
    except RuntimeError:
        return None
    field = lambda tag, text: (re.search(rf"<{tag}>\s*(?:<value>)?\s*([^<]*)", text) or [None, ""])[1].strip()
    if int(field("issuerCik", x) or 0) != cik:
        return None
    who = field("rptOwnerName", x)
    if " " in who:  # the SEC writes "Sweet Julie"; people say "Julie Sweet"
        last, first = who.split(" ", 1)
        who = f"{first} {last}"
    if who.isupper():
        who = who.title()
    title = field("officerTitle", x)
    role = ROLES.get(title.lower(), title) if title and "remarks" not in title.lower() else (
        "director" if field("isDirector", x) in ("1", "true") else "officer" if field("isOfficer", x) in ("1", "true") else "")
    bought = sold = 0.0
    days = []
    for t in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", x, re.S):
        try:
            n, px = float(field("transactionShares", t) or 0), float(field("transactionPricePerShare", t) or 0)
        except ValueError:
            continue
        code = field("transactionCode", t)
        bought += n * px if code == "P" else 0
        sold += n * px if code == "S" else 0
        if code in ("P", "S") and field("transactionDate", t):
            days.append(field("transactionDate", t)[:10])
    if not bought and not sold:
        return None
    traded = (f"on {nice_date(min(days))}" if len(set(days)) == 1 else
              f"between {nice_date(min(days))} and {nice_date(max(days))}") if days else ""
    return who, role, bought, sold, field("aff10b5One", x) in ("1", "true"), traded


def subject_is(cik, accession, holding_cik):
    """True when a 13D is about the holding (and not the holding's own stake in another company)."""
    try:
        index = sec_get(doc_url(cik, accession, f"{accession}-index.html"))
    except RuntimeError:
        return False
    block = re.search(r"\(Subject\).*?CIK.*?(\d{10})", index, re.S)
    return bool(block) and int(block.group(1)) == holding_cik


def check_filings(rows, state):
    """Every new filing that matters, except results, which get their own message."""
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RESULTS_LOOKBACK_DAYS)
    for row in rows:
        entry = companies().get(row["ticker"])
        if not entry:
            continue
        cik, r, lines = entry[0], submissions(entry[0]), []
        for i, form in enumerate(r["form"][:80]):
            acc = r["accessionNumber"][i]
            if acc in state["filings"]:
                continue
            if datetime.fromisoformat(r["acceptanceDateTime"][i].replace("Z", "+00:00")) < cutoff:
                break  # newest first, so everything after this is older
            items = [x.strip() for x in (r["items"][i] or "").split(",") if x.strip()]
            url, when = doc_url(cik, acc, r["primaryDocument"][i]), nice_date(r["filingDate"][i])
            line = None
            if form in ("8-K", "8-K/A") and "2.02" not in items:
                said = [ITEMS_8K[x] for x in items if x in ITEMS_8K]
                if said:
                    line = f"The company {'; '.join(said)} (8-K, filed {when}). {link(url, 'Read it')}"
            elif form == "4":
                trade = insider_trade(cik, acc, r["primaryDocument"][i])
                if trade:
                    who, role, bought, sold, plan, traded = trade
                    person = f"{who} ({role})" if role else who
                    dated = f"{traded}, filed {when}" if traded else f"filed {when}"
                    if bought:
                        line = f"{esc(person)} <b>bought</b> {money(bought)} of stock on the open market {dated}. {link(url, 'Form 4')}"
                    elif not plan:
                        line = f"{esc(person)} sold {money(sold)} of stock {dated}, not under a pre-set plan. {link(url, 'Form 4')}"
                    else:  # routine: added up in the Monday portfolio check
                        state.setdefault("plan_sales", {}).setdefault(row["ticker"], 0)
                        state["plan_sales"][row["ticker"]] += sold
            elif form in ("10-Q", "10-K", "20-F", "40-F"):
                kind = "quarterly report" if form == "10-Q" else "annual report"
                line = f"Filed its {kind} ({form}) on {when}. {link(url, 'Read it')}"
            elif form.startswith(("SC 13D", "SCHEDULE 13D")) and subject_is(cik, acc, cik):
                line = f"An investor filed or updated an activist-size stake (13D, filed {when}). {link(url, 'Read it')}"
            if line:
                lines.append("• " + line)
            if not (form in ("8-K", "8-K/A") and "2.02" in items):
                state["filings"].append(acc)  # results are marked by the results check
        if lines:
            out.append(f"<b>{esc(name_of(row['ticker']))}</b>\n" + "\n".join(lines))
    return out


# ----------------------------------------------------------------------------- 2. price

def check_prices(rows, state):
    out = []
    for row in rows:
        series = yahoo(row.get("yahoo") or row["ticker"], "3mo")
        if len(series) < 23:
            continue
        move, day, last = pct(series[-1][1], series[-2][1]), series[-1][0], series[-1][1]
        if abs(move) >= STOCK_DAY_MOVE and first_today(state, f"price|{row['ticker']}|{day}"):
            month = pct(last, series[-22][1])
            out.append(f"<b>{esc(name_of(row['ticker']))}</b>\n"
                       f"{'Up' if move > 0 else 'Down'} {abs(move):.1f}% on {nice_date(day)}, to ${last:,.2f}.\n"
                       f"{'Up' if month >= 0 else 'Down'} {abs(month):.1f}% over the past month.")
    return out


# ----------------------------------------------------------------------------- 3. what the portfolio depends on

def load_commodities():
    with open(COMMODITIES) as fh:
        return {c["id"]: c for c in json.load(fh)["commodities"]}


def breakout(series, digits=2, unit=""):
    """A new high or low over the last RANGE_DAYS readings: (kind, fact line, range line)."""
    if len(series) <= RANGE_DAYS:
        return None
    last_day, last = series[-1]
    before = [v for _, v in series[-RANGE_DAYS - 1:-1]]
    lo, hi, start = min(before), max(before), series[-RANGE_DAYS - 1][0]
    fmt = lambda v: f"{v:,.{digits}f}{unit}"
    span = f"Range since {nice_date(start)}: {fmt(lo)} to {fmt(hi)}."
    if last > hi:
        return "high", f"{fmt(last)} on {nice_date(last_day)}, its highest in three months.", span
    if last < lo:
        return "low", f"{fmt(last)} on {nice_date(last_day)}, its lowest in three months.", span
    return None


def who_line(who, short=False):
    """Two plain lines: the names with costs tied to the item, and the names with revenue."""
    show = (lambda t: t) if short else name_of
    costs = [show(t) for t, side in who if side == "cost"]
    revenue = [show(t) for t, side in who if side == "revenue"]
    lines = []
    if costs:
        lines.append("Costs tied to it: " + ", ".join(costs))
    if revenue:
        lines.append("Revenue tied to it: " + ", ".join(revenue))
    return "\n".join(lines)


def exposure_map(rows):
    held = {}
    for row in rows:
        for e in row["exposures"]:
            cid, _, side = e.partition(":")
            held.setdefault(cid.strip(), []).append((row["ticker"], side.strip().lower()))
    return held


def check_exposures(rows, state):
    book, out = load_commodities(), []
    for cid, who in sorted(exposure_map(rows).items()):
        c = book.get(cid)
        if not c:
            print(f"\"{cid}\" is not in data/commodities.json; check the spelling.")
            continue
        src = c.get("sources", {})
        series = yahoo(src["yahoo"], "5y") if src.get("yahoo") else []
        if not series:
            continue  # only daily prices can break out; monthly series are too slow for this
        is_fx = c.get("group") == "Currency"
        hit = breakout(series, 4 if is_fx else 2, "")
        unit = "" if is_fx else f" ({c.get('unit', '')})"
        if hit and quiet_since(state, f"range|{cid}"):
            out.append(f"<b>{esc(c['label'])}</b>{esc(unit)}\n{esc(hit[1])}\n{esc(hit[2])}\n{esc(who_line(who, short=True))}")
        elif not is_fx:
            top = max(v for _, v in series)
            if pct(series[-1][1], top) >= -NEAR_FIVE_YEAR_HIGH and quiet_since(state, f"peak|{cid}"):
                out.append(f"<b>{esc(c['label'])}</b>{esc(unit)}\n{series[-1][1]:,.2f}, within "
                           f"{NEAR_FIVE_YEAR_HIGH:g}% of its highest price in five years.\n{esc(who_line(who, short=True))}")
    return out


# ----------------------------------------------------------------------------- 4. rates and markets

def check_macro(state):
    out = []
    for sid, label, unit, why in MACRO:
        s = fred(sid)
        if len(s) < 2:
            continue
        if sid == "VIXCLS":
            if s[-1][1] > 25 >= s[-2][1] and quiet_since(state, "macro|VIXCLS"):
                out.append(f"<b>VIX</b>\n{s[-1][1]:.2f} on {nice_date(s[-1][0])}, above 25.\n<i>{esc(why)}</i>")
            continue
        hit = breakout(s, 2, unit)
        if hit and quiet_since(state, f"macro|{sid}"):
            out.append(f"<b>{esc(label)}</b>\n{esc(hit[1])}\n{esc(hit[2])}\n<i>{esc(why)}</i>")
    return out


# ----------------------------------------------------------------------------- 5 and 6. the morning digest

def calendar_today():
    try:
        week = json.loads(fetch("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    except Exception:
        return ["The economic calendar did not answer this morning."]
    today = datetime.now(timezone(timedelta(hours=-4))).date().isoformat()
    out = []
    for e in week:
        if e.get("country") == "USD" and e.get("impact") == "High" and e.get("date", "").startswith(today):
            extra = ", ".join(x for x in (f"forecast {e['forecast']}" if e.get("forecast") else "",
                                          f"previous {e['previous']}" if e.get("previous") else "") if x)
            out.append(f"• {e['date'][11:16]} New York: {esc(e['title'])}" + (f" ({esc(extra)})" if extra else ""))
    return out


TRUSTED_SOURCES = ["Reuters", "Bloomberg", "Associated Press", "AP News", "CNBC", "Financial Times", "FT.com",
                   "The Wall Street Journal", "WSJ", "Barron's", "MarketWatch", "Nikkei", "The Economist",
                   "Fortune", "Forbes", "Business Insider", "Axios", "Yahoo Finance", "Investopedia",
                   "Seeking Alpha", "The Motley Fool", "Investor's Business Daily", "Morningstar", "BBC", "CNN",
                   "The New York Times", "The Guardian", "Al Jazeera", "Economic Times", "Mint", "Moneycontrol"]
THEMES = os.path.join(HERE, "themes.txt")


def google_news(query):
    """[(headline, source, link)] for the last day, newest search first."""
    q = urllib.parse.quote(f"{query} when:1d")
    try:
        feed = fetch(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    except Exception:
        return []
    out = []
    for title, url in re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>", feed, re.S):
        headline, _, source = html.unescape(title).rpartition(" - ")
        if headline and not any(n.lower() in source.lower() for n in NOISY_SOURCES):
            out.append((headline, source, url))
    return out


def trusted_first(items):
    return sorted(items, key=lambda i: not any(t.lower() in i[1].lower() for t in TRUSTED_SOURCES))


def yahoo_news(ticker):
    """[(headline, source, link, published)] from Yahoo Finance's news feed for one ticker."""
    from email.utils import parsedate_to_datetime
    try:
        feed = fetch(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(ticker)}&region=US&lang=en-US")
    except Exception:
        return []
    out = []
    for item in re.findall(r"<item>(.*?)</item>", feed, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        url = re.search(r"<link>(.*?)</link>", item, re.S)
        when = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if title and url and when:
            try:
                out.append((html.unescape(title.group(1)).strip(), "Yahoo Finance", url.group(1).strip(),
                            parsedate_to_datetime(when.group(1).strip())))
            except (TypeError, ValueError):
                pass
    return out


def headlines(rows, state):
    """The newest headline that names the company, for your first holdings, from Yahoo Finance's
    news feed for the ticker. Your keywords put matching stories first. Nothing recent, no line."""
    out, total = [], 0
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=3 if now.weekday() == 0 else 2)  # a Monday looks back over the weekend
    for row in rows:
        if total >= HEADLINES_IN_TOTAL:
            break
        name = name_of(row["ticker"]).rsplit(" (", 1)[0]
        first_word = next((w for w in re.split(r"[\s,]+", name) if len(w) >= 3), name)
        named = lambda h: (first_word.lower() in h.lower() or re.search(rf"\b{re.escape(row['ticker'])}\b", h))
        fresh = lambda h, src: f"{h} - {src}" not in state["headlines"]
        candidates = [(h, src, u) for h, src, u, when in yahoo_news(row.get("yahoo") or row["ticker"])
                      if when >= recent and named(h) and fresh(h, src)]
        # no search fallback: a wrong company's headline (PTC India for PTC) is worse than none
        keys = [k.lower() for k in row["keywords"]]
        candidates.sort(key=lambda c: not any(k in c[0].lower() for k in keys))
        if candidates:
            headline, source, url = candidates[0]
            out.append(f"<b>{esc(name_of(row['ticker']))}</b>\n{link(url, headline)} <i>({esc(source)})</i>")
            state["headlines"].append(f"{headline} - {source}")
            total += 1
    return out


def theme_headlines(state):
    """One headline from a trusted outlet for each theme in themes.txt (a strait, a war, a tariff)."""
    if not os.path.exists(THEMES):
        return []
    out = []
    for theme in [t.strip() for t in open(THEMES) if t.strip() and not t.startswith("#")][:5]:
        for headline, source, url in google_news(f'"{theme}"'):
            if (any(t.lower() in source.lower() for t in TRUSTED_SOURCES)
                    and f"{headline} - {source}" not in state["headlines"]):
                out.append(f"<b>{esc(theme)}</b>\n{link(url, headline)} <i>({esc(source)})</i>")
                state["headlines"].append(f"{headline} - {source}")
                break
        time.sleep(1)
    return out


# ----------------------------------------------------------------------------- the Monday portfolio check

def results_this_week(tickers):
    """{ticker: 'Tue 27 Oct, before the open'} from Nasdaq's free earnings calendar, next five weekdays."""
    d, days = datetime.now(timezone.utc).date(), []
    while len(days) < 5:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    found = {}
    for d in days:
        try:
            data = json.loads(fetch(f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}",
                                    {"User-Agent": BROWSERS[0], "Accept": "application/json"}))
        except Exception:
            continue
        for row in (data.get("data") or {}).get("rows") or []:
            if row.get("symbol") in tickers:
                when = {"time-pre-market": "before the open", "time-after-hours": "after the close"}.get(row.get("time"), "")
                found[row["symbol"]] = f"{d:%a} {d.day} {d:%b}" + (f", {when}" if when else "")
    return found


def weights(rows):
    """{ticker: share of the portfolio}: broker values, else shares x price from your list, else equal."""
    values = {}
    for r in rows:
        v = float(r.get("value") or 0)
        if not v and (r.get("shares") or "").strip():
            series = yahoo(r.get("yahoo") or r["ticker"], "3mo")
            v = float(r["shares"]) * series[-1][1] if series else 0
        if v:
            values[r["ticker"]] = v
    if values:
        total = sum(values.values())
        return {t: v / total for t, v in values.items()}, True
    held = [r["ticker"] for r in rows]
    return {t: 1 / len(held) for t in held}, False


def portfolio_week(rows, state):
    """Monday morning: the portfolio as a whole. Facts about the book, never instructions."""
    w, real = weights(rows)
    held = [r for r in rows if r["ticker"] in w]
    lines = [f"🧭 <b>Your portfolio this week, {nice_date(datetime.now(timezone.utc).date().isoformat())}</b>"]
    if not real:
        lines.append("<i>Weights are equal because your list has no shares column and no broker is connected.</i>")

    top = sorted(w.items(), key=lambda kv: -kv[1])[:5]
    lines += ["", "<b>Largest positions</b>"] + [f"{esc(name_of(t))}: {v * 100:.1f}%" for t, v in top]

    moves = []
    for r in held:
        series = yahoo(r.get("yahoo") or r["ticker"], "3mo")
        if len(series) >= 6:
            moves.append((r["ticker"], pct(series[-1][1], series[-6][1])))
    if moves:
        book = sum(w[t] * m for t, m in moves) / sum(w[t] for t, _ in moves)
        best, worst = max(moves, key=lambda m: m[1]), min(moves, key=lambda m: m[1])
        lines += ["", "<b>Last five trading days</b>",
                  f"The portfolio {'rose' if book >= 0 else 'fell'} {abs(book):.1f}%. "
                  f"Best: {esc(best[0])} {best[1]:+.1f}%. Worst: {esc(worst[0])} {worst[1]:+.1f}%."]

    book_map, labels = exposure_map(held), {k: v["label"] for k, v in load_commodities().items()}
    rows_out = []
    for cid, who in book_map.items():
        cost = sum(w[t] for t, side in who if side == "cost")
        rev = sum(w[t] for t, side in who if side == "revenue")
        rows_out.append((cost + rev, labels.get(cid, cid), cost, rev))
    if rows_out:
        lines += ["", "<b>What the portfolio depends on</b>"]
        for _, label, cost, rev in sorted(rows_out, reverse=True)[:6]:
            parts = ([f"{rev * 100:.0f}% of the portfolio has revenue tied to it"] if rev else []) + \
                    ([f"{cost * 100:.0f}% has costs tied to it"] if cost else [])
            lines.append(f"{esc(label)}: {'; '.join(parts)}.")

    due = results_this_week({r["ticker"] for r in held})
    if due:
        lines += ["", "<b>Reporting results in the next five trading days</b>"] + [f"{esc(name_of(t))}: {when}" for t, when in due.items()]

    sales = state.pop("plan_sales", {})
    if sales:
        lines += ["", "<b>Insider sales under pre-set plans since last Monday</b>"] + \
                 [f"{esc(name_of(t))}: {money(v)}" for t, v in sorted(sales.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


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
    entry = companies().get(ticker.upper())
    if not entry:
        sys.exit(f"{ticker} has no SEC filings.")
    cik = entry[0]
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
        print("\n----- message -----\n" + re.sub(r"<[^>]+>", "", text) + "\n-------------------")
        return
    token, chat = os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is not set.")
    parts, current = [], ""
    for block in text.split("\n\n"):  # Telegram's limit is 4,096 characters; split between blocks
        if current and len(current) + len(block) > 3800:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    parts.append(current)
    for part in parts:
        body = json.dumps({"chat_id": chat, "text": part, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
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

def portfolio_map(rows):
    """How the watchlist connects: each commodity, currency or rate, and the names tied to it."""
    book = load_commodities()
    lines = ["🌳 <b>How your portfolio connects</b>", ""]
    held = exposure_map(rows)
    for cid, who in sorted(held.items(), key=lambda kv: -len(kv[1])):
        label = book.get(cid, {}).get("label", cid)
        lines.append(f"<b>{esc(label)}</b>\n{esc(who_line(who, short=True))}\n")
    alone = [r["ticker"] for r in rows if not r["exposures"]]
    if alone:
        lines += [f"No commodity or currency set yet: {esc(', '.join(alone))}."]
    lines += ["", "Every holding also shares the same rates, credit spreads and dollar, which the "
                  "watcher checks for all of them."]
    return "\n".join(lines)


def main(argv):
    dry_run = "--dry-run" in argv
    if "--chat-id" in argv:
        return print_chat_id()
    if "--exposures" in argv:
        return exposure_words(argv[argv.index("--exposures") + 1])

    first_run = not os.path.exists(STATE)
    rows, source = portfolio(read_watchlist())
    state = load_state()

    if "--replay" in argv:
        t = argv[argv.index("--replay") + 1].upper()
        picked = [r for r in rows if r["ticker"] == t] or [{"ticker": t, "exposures": [], "keywords": []}]
        for m in check_results(picked, state, replay=True):
            telegram(m, dry_run)
        return
    if "--map" in argv:
        return telegram(portfolio_map(rows), dry_run)

    if first_run:
        telegram(f"👋 <b>Your portfolio watcher is running.</b>\n\nIt is watching {len(rows)} "
                 f"name{'s' if len(rows) != 1 else ''}" + (f" ({source})" if source else "") + ". It checks before the market opens and after it "
                 f"closes, and it only writes when something matters.", dry_run)
        telegram(portfolio_map(rows), dry_run)

    # results are the most important thing, so each one gets its own message
    for m in check_results(rows, state):
        telegram(m, dry_run)

    now = datetime.now(timezone.utc)
    morning = "--morning" in argv or first_today(state, "morning")  # the first run of the day
    monday = now.date() - timedelta(days=now.weekday())
    if "--week" in argv or (morning and state["fired"].get("week") != monday.isoformat()):
        state["fired"]["week"] = monday.isoformat()  # the first morning of each week
        telegram(portfolio_week(rows, state), dry_run)
    sections = [("🗂 New filings", check_filings(rows, state)),
                ("📈 Big moves in your holdings", check_prices(rows, state)),
                ("🛢 What your portfolio depends on", check_exposures(rows, state)),
                ("🏦 Rates and markets", check_macro(state))]
    if morning:
        cal = calendar_today()
        if cal:
            sections.append((f"🗓 Today's US releases", cal))
        sections.append(("📰 Top headlines", headlines(rows, state)))
        sections.append(("🌍 Themes you follow", theme_headlines(state)))

    body = "\n\n".join(f"<b>{title}</b>\n" + "\n\n".join(blocks) for title, blocks in sections if blocks)
    if body:
        telegram(f"<b>{'Morning' if morning else 'Evening'} note, {nice_date(now.date().isoformat())}</b>\n\n" + body, dry_run)

    if not dry_run:
        save_state(state)
    print(f"Checked {len(rows)} name{'s' if len(rows) != 1 else ''} at {now:%Y-%m-%d %H:%M} UTC."
          + ("" if body else " Nothing to report."))


if __name__ == "__main__":
    main(sys.argv[1:])

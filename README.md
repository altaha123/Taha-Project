# Altaha Screener — Where Logic Meets Validations

Type any Indian (NSE/BSE) or US stock symbol. Get a 0–100 composite score built from a
validated technical engine (EMA structure, Hull MA, RSI, MACD, ADX, Supertrend, 52-week
position) and a fundamental engine (full 9-point Piotroski F-Score, ROCE, leverage,
growth, valuation). Every score expands into an audit trail: inputs → formula → points.
Every check teaches the concept in one plain-English line.

**Scores and evidence everywhere; calls in one place.** Stock pages, the scan, the
screener and the daily email show scores and evidence, never buy/sell directives.
The **portfolio review** is the exception: it gives every holding a rule-based call —
hold, trim, average down, add or exit — with stronger alternatives and industries to
move into (`backend/action_plan.py`). That was the owner's decision, taken knowing that
in India advice on someone's holdings is regulated by SEBI (Investment Advisers
Regulations) and stock recommendations are research (Research Analysts Regulations),
and that this project is not registered under either. The page says so in plain words
(`action_plan.DISCLAIMER`); keep that sentence true, and take legal advice before
charging for the calls.

---

## The four products

The site is not one screener with a row of tabs. It is four products, and each
one exists to answer a single question somebody actually arrives with. Where a
destination goes is decided by which question it answers — not by which feed it
happens to read.

| Product | The question it answers | What lives there |
|---|---|---|
| **Discover** | *Where are opportunities now?* | The opportunities hub, the live intraday scanner, delivery trends, bulk & block deals, WOW orders, options activity |
| **Allocate** | *What should I do with my money?* | The guided card — how much, what risk it can carry, which asset classes follow ([`ALLOCATE-FLOW.md`](ALLOCATE-FLOW.md)) — and the money planner behind it |
| **Portfolio** | *How are my existing investments doing?* | The holdings review — see [`IC-REVIEW.md`](IC-REVIEW.md) for what happens to an uploaded file, end to end — and the record of ideas you added |
| **Research** | *What does the evidence say?* | The stock screener, stock analysis, the Altaha Score, factors, fundamentals, ownership, technicals, delivery, news — and the glossary |

`frontend/nav.js` holds the map and owns routing; `frontend/shell.js` renders
the same map as the header menu. A destination has exactly one owner, and every
address the site has ever published still resolves — `#screener`, `#ideas`,
`#planner`, `#social` and the `#section/tab` pairs all map onto the product that
now owns them. `frontend/tests/nav-products-browser.cjs` asserts all of that in
a real browser, because none of it throws when it breaks.

The two hubs are new surfaces rather than renamed tabs: `frontend/discover.js`
builds Discover out of the feeds that already have tabs of their own, and
`frontend/allocate-flow.js` asks for an amount, profiles the risk it can carry
and turns the two into asset classes, entirely in the browser. Neither names a
product or issues a recommendation — see the SEBI note above.

---

## Advisors — talk to a person

`advisors.html` lists SEBI-registered investment advisers, registered research
analysts and well-known market educators, and lets any signed-in reader chat
with them about their portfolio, a stock, a fund, retirement or a career.
People register themselves; nobody is listed until the owner has checked the
registration number on SEBI's register (`advisors.html#admin`). Chats are free.

A call made in a chat is the adviser's, under their own registration — not
Altaha's. Educators are not registered, so a message from one that reads as a
buy or sell call is not sent; nobody may promise returns or move a reader to a
phone, a payment app or WhatsApp. A reader can show their saved portfolio to a
registered investment adviser and take it back at any time.

Everything — the three kinds and what each may do, what may be said, why it
polls instead of holding sockets, why there are no star ratings, and the
decisions paid chats would need — is in [`ADVISORS.md`](ADVISORS.md).

---

## Folder map

```
altaha/
├── backend/          the scoring engine (Python / FastAPI)
│   ├── engine.py     all indicator math + scoring, fully commented
│   ├── main.py       the API server
│   └── requirements.txt
├── frontend/
│   └── index.html    the whole website — one file, no build step
└── README.md
```

---

## Run it on your laptop first (10 minutes)

1. Install Python 3.11+ from python.org if you don't have it.
2. In a terminal:
   ```
   cd altaha/backend
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```
3. Open `frontend/index.html` in your browser (just double-click it).
4. Type `RELIANCE` and press Analyse. Done — it's talking to the engine on your machine.

---

## Put it on the internet, free (30 minutes, no credit card)

### Step 1 — Backend on Render
1. Create a free account at github.com. Create a new repository, upload the whole
   `altaha` folder.
2. Create a free account at render.com → **New → Web Service** → connect your GitHub repo.
3. Settings:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Set these environment variables** (Render → Environment). They are not
   optional on a 512 MB instance — without the first two the service will hit
   its memory limit and restart, which looks from the outside like the tabs
   being broken:

   | Variable | Value | Why |
   |---|---|---|
   | `MALLOC_ARENA_MAX` | `2` | glibc gives a threaded process up to 8 memory arenas **per CPU**. This app runs eight-plus threads. Measured on a scan-shaped workload: 93.2 MB unrestricted, 79.7 MB at 2. |
   | `WEB_CONCURRENCY` | `1` | One uvicorn worker. Two doubles the ~99 MB library floor (numpy + pandas + yfinance) before any data. |
   | `DATA_DIR` | `/data` | Must match the **mount path of your Render disk** (check Render → Disk; it cannot be changed after the disk is created). The tracker ledger, the point-in-time store and the Altaha Special delivery panels all live here and are otherwise rebuilt from nothing on every deploy. |
   | `ADMIN_KEY` | your own secret | Guards the control endpoints. |

   `render.yaml` in the repo root declares all of this — point Render at it as
   a Blueprint and it is applied for you.

5. Deploy. Render gives you a URL like `https://altaha-api.onrender.com`.
   Open `https://altaha-api.onrender.com/analyze?ticker=TCS` — if you see JSON, it's live.
   Then open `/health/memory`: it reports resident memory, the peak, the thread
   count, whether the arena cap is actually set, and which subsystem is holding
   what. Check it before assuming a slow site is a frontend problem.

### Step 2 — Frontend on Vercel or Netlify
1. Edit `frontend/index.html`: near the bottom, change
   `const API_BASE = "http://localhost:8000";`
   to your Render URL, e.g. `const API_BASE = "https://altaha-api.onrender.com";`
2. Create a free account at netlify.com → drag-and-drop the `frontend` folder onto the
   dashboard. That's it. You get `something.netlify.app` — rename it to
   `altaha-screener.netlify.app` in site settings.
3. Put the link in your Instagram bio.

### Free-tier honesty
- Render free tier sleeps after 15 min idle; first request after sleep takes ~30 s.
  The frontend already shows a friendly message for this. Upgrade ($7/mo) removes it.
- Data comes from Yahoo Finance via `yfinance` — free, unofficial, fine for launch.
  If traffic grows, swap in your Dhan/Fyers feed for India and Polygon for US — the
  engine only needs OHLCV + statements, so only `main.py` changes.

---

### Delivery, per company

`/delivery?ticker=SYM` returns the delivered share of each session's volume for
one stock, and the Delivery pane on `stock.html` renders it. NSE publishes the
figure per stock per day in the full bhavcopy and no OHLCV feed carries it,
which is the same disclosure the Altaha Special book is ranked on — both read
the one panel in `backend/special.py`, so the book and the stock page can never
quote different numbers for the same session.

The store holds **every EQ symbol the bhavcopy lists** — about 2,665 a session,
not the ~820 that clear the book's turnover floor. It used to keep only the
liquid ones, on an argument inherited from the v2 long-format cache where the
saving was real; against wide float32 panels it was discarding roughly 1,845
companies to save some 11 MB on a 512 MB instance, and those are exactly the
small and mid caps somebody opens a screener to look up. The BOOK is narrowed
instead, at rank time, by `_rank_cols` — which matters more than it sounds,
because `_components` uses the cross-sectional median of the panel as its
market proxy, so a wider file would otherwise have re-scored every name in the
Altaha Special book. `test_store_the_whole_exchange.py` pins that: same names,
same order, same scores to floating-point equality, wide file or narrow.

Sessions stored before the widening carry only the liquid names. They are
detected per date by their coverage and handed back to the builder as if they
were missing, so the history backfills itself and an interrupted backfill
resumes; `/special/status` reports how many days are left as `backfilling`. A
company whose history is still filling says so on the page rather than
presenting a short average as a considered one.

The delivered QUANTITY is derived — traded quantity multiplied by the published share —
because storing NSE's `DELIV_QTY` would be a seventh float32 panel on a 512 MB
instance for a column that is the product of two already held. The percentage
is the exchange's own figure; the quantity carries that percentage's rounding,
and the page says so.

---

### "Explain this score" — plain English, free (optional)

Every scored stock page (`stock.html`) has a floating **Smart AI** button,
bottom right. It opens a small panel over the page that offers one question —
*"What does this score mean, in simple words?"* When a reader asks it,
`/explain?ticker=SYM&horizon=position` hands the numbers the
engine already computed — score, pillars, what helped, what hurt, the checks,
the ratios — to OpenAI's open-weight `gpt-oss-120b` on **Groq's free tier**,
and shows back three short paragraphs labelled as AI-written. The model sees
nothing else: not the news, and not the levels or observation plan, which it
would turn into entry and exit talk. Code: `backend/score_explain.py`.

**To switch it on:** create a free account at console.groq.com (no card),
create an API key, and add it in the Render dashboard → Environment as
`GROQ_API_KEY`. Unset, the section says it is off and nothing is called.

**Staying inside the free allowance** (about 200,000 tokens a day, roughly a
hundred fresh explanations):
- One explanation per stock, per horizon, per IST day, stored in
  `$DATA_DIR/explanations.db`. Every later reader that day costs nothing.
- The service stops at `EXPLAIN_DAILY_TOKENS` (default 180,000) — before the
  provider starts refusing — and says so on the page.
- One visitor can cause at most `EXPLAIN_PER_VISITOR` (default 15) fresh
  explanations a day, so a single person cannot spend everyone's allowance.
- `EXPLAIN_MODEL` swaps the model without a code change.

**The SEBI line holds here too.** The prompt forbids advice, and every reply is
checked again before it is shown: one that reads as a buy/sell call, target,
stop-loss or recommendation is withheld, not shown with a warning.
`backend/tests/test_score_explain.py` and
`frontend/tests/stock-explain-browser.cjs` pin all of the above.

## Where the accuracy lives (read before you market it)

- "Accuracy" here means: textbook-correct indicator formulas (validated against
  synthetic trends in testing), real exchange data, and full transparency — every user
  can audit every point. It does **not** mean prediction. Never market it as predicting
  prices.
- Fundamental data on yfinance can be sparse for small/mid-cap NSE names. The engine
  detects this and falls back to technical-only scoring with a clear label rather than
  showing a misleading zero.
- Tune the scoring weights in `engine.py` — they're plainly commented. If you change
  them, the audit trail updates automatically because formulas are stored with each check.

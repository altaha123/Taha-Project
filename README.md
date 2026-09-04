# Altaha Screener — Where Logic Meets Validations

Type any Indian (NSE/BSE) or US stock symbol. Get a 0–100 composite score built from a
validated technical engine (EMA structure, Hull MA, RSI, MACD, ADX, Supertrend, 52-week
position) and a fundamental engine (full 9-point Piotroski F-Score, ROCE, leverage,
growth, valuation). Every score expands into an audit trail: inputs → formula → points.
Every check teaches the concept in one plain-English line.

**This is an educational tool. It shows scores and evidence, never buy/sell directives.**
Keep it that way — issuing recommendations to the public requires SEBI RA registration.

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
   | `DATA_DIR` | `/var/data` | Must be a **mounted disk**. The tracker ledger, the point-in-time store and the Altaha Special delivery panels all live here and are otherwise rebuilt from nothing on every deploy. |
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

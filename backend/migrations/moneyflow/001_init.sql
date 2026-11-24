-- Money Flow: where institutional money is moving. Applied by
-- money_flow_store.migrate(), once, in file order; the applied set is
-- recorded in schema_migrations. A later change is a new numbered file.

-- NSDL's fortnightly sector-wise FPI report: equity net investment and equity
-- assets under custody, one row per sector per fortnight. Every fortnight is
-- published in two reports (its own and the next one's), so a row is written
-- twice over time; `revisions` counts how often the second copy disagreed.
CREATE TABLE IF NOT EXISTS fpi_sector_fortnight (
  period_end         TEXT NOT NULL,     -- ISO date, the 15th or the month end
  sector             TEXT NOT NULL,     -- canonical name (money_flow_config)
  period_start       TEXT,
  equity_net_inr_cr  REAL,
  equity_net_usd_mn  REAL,
  total_net_inr_cr   REAL,              -- equity + debt + hybrid + funds
  equity_auc_inr_cr  REAL,              -- as on period_end
  source_url         TEXT,
  revisions          INTEGER NOT NULL DEFAULT 0,
  updated_utc        TEXT NOT NULL,
  PRIMARY KEY (period_end, sector)
);

-- Which report pages have been read, so a job asks only for new ones.
CREATE TABLE IF NOT EXISTS fpi_reports (
  url          TEXT PRIMARY KEY,
  report_date  TEXT NOT NULL,
  status       TEXT NOT NULL,           -- ok | error
  note         TEXT,
  rows         INTEGER,
  fetched_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fpi_reports_date ON fpi_reports (report_date);

-- NSE's provisional FII and DII cash-market figures, one row per session.
CREATE TABLE IF NOT EXISTS inst_flow_daily (
  date         TEXT PRIMARY KEY,
  fii_buy      REAL, fii_sell REAL, fii_net REAL,
  dii_buy      REAL, dii_sell REAL, dii_net REAL,
  provisional  INTEGER NOT NULL DEFAULT 1,
  source       TEXT,
  updated_utc  TEXT NOT NULL
);

-- Every NSE index's close, one row per index per session.
CREATE TABLE IF NOT EXISTS index_close_daily (
  date        TEXT NOT NULL,
  index_name  TEXT NOT NULL,            -- upper case, single spaces
  close       REAL NOT NULL,
  PRIMARY KEY (date, index_name)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_index_close_name ON index_close_daily (index_name, date);

-- Calendar days already asked for: a session that was stored, or a day NSE
-- has no file for. A refused or failed day is not written here, so it is
-- asked for again.
CREATE TABLE IF NOT EXISTS index_days (
  date         TEXT PRIMARY KEY,
  status       TEXT NOT NULL,           -- ok | absent
  rows         INTEGER NOT NULL DEFAULT 0,
  fetched_utc  TEXT NOT NULL
);

-- Bulk and block deals as disclosed. The key is the whole disclosure, so
-- reading the same file twice writes nothing new.
CREATE TABLE IF NOT EXISTS deals_daily (
  date     TEXT NOT NULL,
  symbol   TEXT NOT NULL,
  client   TEXT NOT NULL,
  side     TEXT NOT NULL,               -- BUY | SELL
  kind     TEXT NOT NULL,               -- bulk | block
  qty      REAL NOT NULL,
  price    REAL NOT NULL,
  name     TEXT,
  remarks  TEXT,
  PRIMARY KEY (date, symbol, client, side, kind, qty, price)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_deals_symbol ON deals_daily (symbol, date);

-- Windows of deal history already read from NSE's history API.
CREATE TABLE IF NOT EXISTS deals_windows (
  kind         TEXT NOT NULL,
  start_date   TEXT NOT NULL,
  end_date     TEXT NOT NULL,
  rows         INTEGER NOT NULL DEFAULT 0,
  fetched_utc  TEXT NOT NULL,
  PRIMARY KEY (kind, start_date)
);

-- The Sector Money Flow Score, one row per sector per computed session.
-- History, so a sector's move between quadrants can be seen and alerted on.
CREATE TABLE IF NOT EXISTS sector_score_daily (
  date      TEXT NOT NULL,
  sector    TEXT NOT NULL,
  score     REAL,
  rank      INTEGER,
  quadrant  TEXT,
  payload   TEXT NOT NULL,              -- the sector card, as JSON
  PRIMARY KEY (date, sector)
);

-- The strongest accumulation readings inside each sector on that session.
CREATE TABLE IF NOT EXISTS stock_accumulation_daily (
  date     TEXT NOT NULL,
  sector   TEXT NOT NULL,
  symbol   TEXT NOT NULL,
  score    REAL,
  payload  TEXT NOT NULL,
  PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_accum_sector ON stock_accumulation_daily (sector, date);

-- The whole page, as the endpoint serves it. One row per computed session.
CREATE TABLE IF NOT EXISTS snapshots (
  date       TEXT PRIMARY KEY,
  payload    TEXT NOT NULL,
  built_utc  TEXT NOT NULL
);

-- One row per job run, with what each step did or why it failed.
CREATE TABLE IF NOT EXISTS job_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job           TEXT NOT NULL,
  started_utc   TEXT NOT NULL,
  finished_utc  TEXT,
  ok            INTEGER,
  summary       TEXT                    -- JSON: steps, counts, errors
);
CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs (job, id);

-- Alerts already sent, so a sector is announced once per fortnight.
CREATE TABLE IF NOT EXISTS alerts_sent (
  key       TEXT PRIMARY KEY,
  sent_utc  TEXT NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 0,
  text      TEXT
);

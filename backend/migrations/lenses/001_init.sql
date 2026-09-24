-- Lenses: the per-company inputs the fundamentals tables do not carry, and
-- the nightly results cache. Applied by lens_store.migrate(), once, in file
-- order; the applied set is recorded in schema_migrations.

-- NSE's four-level industry classification, issued share count and a price,
-- from the exchange's quote API. One row per company, refreshed by the crawl.
CREATE TABLE IF NOT EXISTS lens_company (
  symbol          TEXT PRIMARY KEY,
  company         TEXT,
  macro           TEXT,
  sector          TEXT,
  industry        TEXT,
  basic_industry  TEXT,
  issued_shares   REAL,
  face_value      REAL,
  last_price      REAL,
  price_date      TEXT,
  updated_utc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lens_company_industry ON lens_company (industry);

-- One row per company per quarter-end shareholding filing: the category
-- totals and the promoter pledge, which the investor ledger does not keep.
CREATE TABLE IF NOT EXISTS lens_shareholding (
  symbol          TEXT NOT NULL,
  period_end      TEXT NOT NULL,
  promoter_pct    REAL,
  fii_pct         REAL,
  dii_pct         REAL,
  public_pct      REAL,
  pledged         INTEGER,          -- 1 yes, 0 no, NULL not stated
  pledge_pct      REAL,             -- % of total shares pledged by promoters
  dii_derived     INTEGER NOT NULL DEFAULT 0,
  source_url      TEXT,
  updated_utc     TEXT NOT NULL,
  PRIMARY KEY (symbol, period_end)
);

-- Which companies the lens crawl has tried, so each slice continues the last.
CREATE TABLE IF NOT EXISTS lens_coverage (
  symbol          TEXT PRIMARY KEY,
  last_try_utc    TEXT,
  last_ok_utc     TEXT,
  status          TEXT,
  note            TEXT
);

-- One row per nightly compute.
CREATE TABLE IF NOT EXISTS lens_runs (
  run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  started_utc     TEXT NOT NULL,
  finished_utc    TEXT,
  config_version  INTEGER,
  universe        INTEGER,
  companies       INTEGER,
  status          TEXT,
  note            TEXT
);

-- The cache the endpoints read: one row per company per lens per run.
-- `rules` is the JSON list of per-rule results (pass / fail / na, the value
-- and how it was computed).
CREATE TABLE IF NOT EXISTS lens_results (
  run_id          INTEGER NOT NULL,
  lens_id         TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  company         TEXT,
  industry        TEXT,
  status          TEXT NOT NULL,    -- pass | near_miss | fail | insufficient
  passed          INTEGER NOT NULL,
  failed          INTEGER NOT NULL,
  na              INTEGER NOT NULL,
  total           INTEGER NOT NULL,
  coverage        REAL NOT NULL,
  rules           TEXT NOT NULL,
  PRIMARY KEY (run_id, lens_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_lens_results_symbol ON lens_results (symbol, run_id);
CREATE INDEX IF NOT EXISTS idx_lens_results_status ON lens_results (run_id, lens_id, status);

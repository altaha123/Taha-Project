"""Published NSE index composition, with automatic source refresh on access.

The catalogue and weight files are the same public feeds used by Nifty Indices.
Never execute the JSONP or replace missing weights with market-cap estimates.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import sector_benchmarks as B
import nse_http

ROOT = 'https://liveindexsa.niftyindices.com/jsonfiles/'
LEVELS = {'sector': ('Sector', 'Sector'), 'industry': ('Industry', 'Industry'),
          'basic': ('Basic Industry', 'BasicIndustry'),
          'macro': ('MacroEconomicSector', 'MacroEconomicSector')}
_cache = {}
_guard = threading.Lock()
_locks = {}


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=10) as r:
        return r.read(5_000_000).decode('utf-8-sig')


def cached(key, loader, ttl=3600):
    """Persist last good composition across deploys when DATA_DIR is durable."""
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        now = time.time()
        slot = _cache.get(key)
        path = Path(os.environ.get('DATA_DIR', '/tmp/altaha-data')) / 'index-explorer' / (hashlib.sha256(key.encode()).hexdigest()+'.json')
        if slot is None:
            try:
                slot = json.loads(path.read_text())
            except (OSError, ValueError):
                slot = None
        if slot and now - slot['checked'] < (60 if slot.get('stale') else ttl):
            return slot
        try:
            data = loader()
            if not data:
                raise ValueError('Empty source')
            slot = {'data': data, 'checked': now, 'stale': False}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(slot)); os.replace(temp, path)
            except OSError:
                pass
        except Exception:
            slot = {**(slot or {'data': None}), 'checked': now, 'stale': True}
        _cache[key] = slot
        return slot


def catalog():
    slot = cached('catalog', lambda: json.loads(fetch(ROOT+'IndexType.json')))
    rows = []
    for r in slot['data'] or []:
        if r.get('IndexTradingname') and r.get('Title'):
            rows.append({'id': r['IndexTradingname'].strip().upper(), 'name': r['Title'].strip(),
                         'category': r.get('IndexType', ''), 'kind': r.get('IndextypeShort', '')})
    return {'indices': rows, 'stale': slot['stale'], 'source': ROOT+'IndexType.json'}


def resolve(index):
    key = B.name(index)
    for r in catalog()['indices']:
        if key in (B.name(r['id']), B.name(r['name'])):
            return r
    raise ValueError('Index is not in the published NSE catalogue')


def parse_weights(text):
    if not text.lstrip().startswith('modelDataAvailable('):
        raise ValueError('Unexpected composition format')
    raw = text[text.index('(')+1:]
    # Source JSONP contains trailing commas; decode only its first data object.
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    data, _ = json.JSONDecoder().raw_decode(raw.lstrip())
    dates, symbols, groups = set(), set(), []
    def clean_label(label):
        return re.sub(r'\s+[\d.]+%\s*$', '', str(label)).strip()
    for g in data.get('groups', []):
        stocks = []
        for s in g.get('groups', []):
            symbol, weight = clean_label(s.get('label', '')), B.number(s.get('weight'))
            day = B.date(s.get('date'))
            if not symbol or symbol in symbols or weight is None or not 0 <= weight <= 100 or not day:
                raise ValueError('Invalid or undated constituent weight')
            symbols.add(symbol); dates.add(day.isoformat())
            stocks.append({'symbol': symbol, 'weight_pct': weight})
        weight = B.number(g.get('weight'))
        if not stocks or weight is None or abs(sum(s['weight_pct'] for s in stocks)-weight) > .15:
            raise ValueError('Incomplete composition group')
        groups.append({'name': clean_label(g.get('label','')), 'weight_pct': weight, 'stocks': stocks})
    if not groups or len(dates) != 1 or abs(sum(g['weight_pct'] for g in groups)-100) > 1:
        raise ValueError('Incomplete or mixed-date composition')
    return {'groups': groups, 'as_of': next(iter(dates))}


def composition(index, level='sector'):
    meta = resolve(index)
    level = level if level in LEVELS else 'sector'
    folder, suffix = LEVELS[level]
    filename = meta['id'].replace('NIFTY TATA GROUP 25% CAP', 'NIFTY TATA GROUP 25 CAP')
    url = ROOT + quote(folder+'/SectorialIndexData'+filename+'_'+suffix+'.js', safe='/')
    slot = cached('weights:'+meta['id']+':'+level, lambda: parse_weights(fetch(url)))
    return {**meta, **(slot['data'] or {'groups': [], 'as_of': None}), 'available': bool(slot['data']),
            'level': level, 'stale': slot['stale'], 'source': url,
            'checked_at': dt.datetime.fromtimestamp(slot['checked'], dt.timezone.utc).isoformat(),
            'refresh': 'Source checked hourly when viewed; failed refreshes retain dated last-good weights.'}


def stock_baseline(target):
    for offset in range(8):
        day = target-dt.timedelta(days=offset)
        url = 'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_'+day.strftime('%d%m%Y')+'.csv'
        try:
            text = fetch(url)
        except HTTPError as e:
            if e.code == 404:
                continue
            return None
        rows = {}
        for raw in csv.DictReader(io.StringIO(text)):
            r = {k.strip(): str(v or '').strip() for k,v in raw.items() if k}
            close = B.number(r.get('CLOSE_PRICE'))
            if r.get('SERIES') == 'EQ' and B.date(r.get('DATE1')) == day and close and close > 0:
                rows[r['SYMBOL']] = close
        if rows:
            return {'date': day.isoformat(), 'closes': rows}
        return None
    return None


def performance(index, window='1D'):
    meta = resolve(index)
    window = window if window in ('1D','1W','1M') else '1D'
    snap = cached('quotes:'+meta['id'], lambda: nse_http.get_json(
        'https://www.nseindia.com/api/equity-stockIndices', params={'index': meta['id']}), 60)
    body = snap['data'] or {}
    stamp = body.get('timestamp')
    day = B.date(stamp)
    baseline = None
    if window != '1D' and day:
        target = day-dt.timedelta(days=7 if window=='1W' else 30)
        baseline = cached('stock-close:'+target.isoformat(), lambda: stock_baseline(target), 86400)['data']
    stocks = {}
    for r in body.get('data', []):
        sym = str(r.get('symbol', ''))
        if not sym or sym.upper().startswith('NIFTY '):
            continue
        last = B.number(r.get('lastPrice'))
        prev = B.number(r.get('previousClose')) if window=='1D' else (baseline or {}).get('closes',{}).get(sym)
        value = round((last/prev-1)*100,2) if day and last and prev and prev>0 else None
        stocks[sym] = {'change_pct': value, 'price': last}
    # Use the published index level, not a reconstruction from current weights.
    snapshot = cached('all-indices', lambda: nse_http.get_json('https://www.nseindia.com/api/allIndices'),60)
    data = snapshot['data'] or {}
    record = next((r for r in data.get('data',[]) if B.name(r.get('index')) == B.name(meta['id'])), {})
    index_day = B.date(data.get('timestamp'))
    previous = B.number(record.get('previousClose'))
    baseline_date = None
    if window != '1D' and index_day:
        baseline_date, closes = B.archive_on_or_before(index_day-dt.timedelta(days=7 if window=='1W' else 30))
        previous = closes.get(B.name(meta['id']))
    last = B.number(record.get('last'))
    change = round((last/previous-1)*100,2) if index_day and last and previous and previous>0 else None
    return {'index': meta['id'], 'window': window, 'index_level': last, 'change_pct': change,
            'index_as_of': data.get('timestamp'), 'stocks_as_of': stamp, 'stocks': stocks,
            'stale': snap['stale'] or snapshot['stale'],
            'baseline_date': baseline_date.isoformat() if baseline_date else None,
            'stock_baseline_date': (baseline or {}).get('date'),
            'method': 'Day: previous close. Week/month: close on or before 7/30 calendar days earlier. Stock price changes are not adjusted for corporate actions. Group changes use current published weights, not historical index contributions.'}

/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — Portfolio Review
   ═══════════════════════════════════════════════════════════════════════════

   Replaces the in-page portfolio code entirely. Four things changed:

   1. CSV parsing is a real parser. The previous one was line.split(','),
      which breaks on the first quoted company name containing a comma —
      i.e. on every actual broker export. This one handles quoted fields,
      escaped quotes, tabs, semicolons, preamble rows above the header, and
      maps broker column names onto ours. Anything it can't place, the user
      maps by hand rather than being told the file is invalid.

   2. Analysis is job-based. Start returns an id, the client polls, progress
      is visible. A fifty-holding book no longer risks dying at a proxy.

   3. The book persists in localStorage under named portfolios. Nothing is
      sent anywhere except the symbols and quantities needed to score them,
      and nothing is stored server-side.

   4. Charts are hand-rolled SVG. No charting library, so the bundle stays
      where it is.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) || '';
  var MAX_ROWS = 50;
  var STORE_KEY = 'altaha-portfolios';
  var POLICY_KEY = 'altaha-policy';

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined) n.textContent = txt;
    return n;
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function inr(n) {
    if (n === null || n === undefined || !isFinite(n)) return '\u2014';
    return '\u20B9' + Math.round(n).toLocaleString('en-IN');
  }
  function inrShort(n) {
    if (n === null || n === undefined || !isFinite(n)) return '\u2014';
    var a = Math.abs(n), s = n < 0 ? '\u2212' : '';
    if (a >= 1e7) return s + '\u20B9' + (a / 1e7).toFixed(2) + ' Cr';
    if (a >= 1e5) return s + '\u20B9' + (a / 1e5).toFixed(2) + ' L';
    return s + '\u20B9' + Math.round(a).toLocaleString('en-IN');
  }
  function pct(n, dp) {
    if (n === null || n === undefined || !isFinite(n)) return '\u2014';
    return n.toFixed(dp === undefined ? 1 : dp) + '%';
  }

  /* ── 1. CSV PARSING ─────────────────────────────────────────────────────
     A proper state machine. Handles quoted fields containing the delimiter,
     doubled quotes as escapes, and CRLF inside quotes. Delimiter is sniffed
     from the first non-empty line rather than assumed to be a comma, because
     several brokers export semicolon-separated files and Excel does too in
     locales where the comma is a decimal separator. */

  function sniffDelimiter(text) {
    var line = text.split(/\r?\n/).find(function (l) { return l.trim(); }) || '';
    var counts = { ',': 0, ';': 0, '\t': 0, '|': 0 };
    var inQ = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (c === '"') inQ = !inQ;
      else if (!inQ && counts[c] !== undefined) counts[c]++;
    }
    var best = ',', bestN = 0;
    Object.keys(counts).forEach(function (d) {
      if (counts[d] > bestN) { bestN = counts[d]; best = d; }
    });
    return best;
  }

  function parseCSV(text, delim) {
    delim = delim || sniffDelimiter(text);
    var rows = [], field = '', row = [], inQ = false;

    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (inQ) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; }
          else inQ = false;
        } else field += c;
        continue;
      }
      if (c === '"') { inQ = true; continue; }
      if (c === delim) { row.push(field); field = ''; continue; }
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue; }
      if (c === '\r') continue;
      field += c;
    }
    if (field.length || row.length) { row.push(field); rows.push(row); }

    return rows
      .map(function (r) { return r.map(function (f) { return f.trim(); }); })
      .filter(function (r) { return r.some(function (f) { return f !== ''; }); });
  }

  /* Broker column vocabularies. Matching is on a normalised key — lowercase,
     punctuation and spaces stripped — so "Avg. cost", "avg cost" and
     "AvgCost" all collapse to the same thing. */

  var COLUMN_HINTS = {
    symbol: ['symbol', 'instrument', 'tradingsymbol', 'scrip', 'scripname',
             'stockname', 'stock', 'company', 'companyname', 'security',
             'securityname', 'name', 'ticker', 'nsecode', 'bsecode'],
    qty: ['qty', 'quantity', 'shares', 'holdingqty', 'netqty', 'totalqty',
          'quantityavailable', 'freeqty', 'balance', 'units', 'noofshares'],
    buy: ['buyprice', 'avgcost', 'averagecost', 'avgprice', 'averageprice',
          'buyavg', 'avgbuyprice', 'averagebuyprice', 'costprice', 'price',
          'purchaseprice', 'rate', 'avgtradedprice'],
    date: ['buydate', 'purchasedate', 'date', 'tradedate', 'transactiondate',
           'dateofpurchase']
  };

  function normKey(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  function matchColumn(header, kind) {
    var k = normKey(header);
    if (!k) return false;
    var hints = COLUMN_HINTS[kind];
    if (hints.indexOf(k) !== -1) return true;
    return hints.some(function (h) { return k === h || k.indexOf(h) === 0; });
  }

  /* Find the header row. Broker exports frequently carry two or three lines
     of account metadata before it, so scan the first fifteen rows for the one
     that looks most like a header — that is, the one where the most cells
     match a known column name. */

  function findHeader(rows) {
    var best = { index: -1, score: 0, map: null };
    var limit = Math.min(15, rows.length);

    for (var i = 0; i < limit; i++) {
      var cells = rows[i], map = {}, score = 0;
      for (var c = 0; c < cells.length; c++) {
        ['symbol', 'qty', 'buy', 'date'].forEach(function (kind) {
          if (map[kind] === undefined && matchColumn(cells[c], kind)) {
            map[kind] = c; score++;
          }
        });
      }
      if (map.symbol !== undefined && map.qty !== undefined && score > best.score) {
        best = { index: i, score: score, map: map };
      }
    }
    return best.index === -1 ? null : best;
  }

  function cleanNumber(raw) {
    if (raw === null || raw === undefined) return null;
    var s = String(raw).replace(/[\u20B9$,\s]/g, '').replace(/[()]/g, '');
    if (s === '' || s === '-' || s === '\u2014') return null;
    var n = Number(s);
    return isFinite(n) ? n : null;
  }

  function cleanSymbol(raw) {
    return String(raw || '').trim().toUpperCase()
      .replace(/\.(NS|BO)$/i, '')
      .replace(/[^A-Z0-9&\-]/g, '');
  }

  function cleanDate(raw) {
    if (!raw) return null;
    var s = String(raw).trim();
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[0];
    m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/);
    if (m) {
      var y = m[3].length === 2 ? '20' + m[3] : m[3];
      return y + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[1]).slice(-2);
    }
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
  }

  function rowsFromMap(rows, headerIndex, map) {
    var out = [];
    for (var i = headerIndex + 1; i < rows.length; i++) {
      var cells = rows[i];
      var sym = cleanSymbol(cells[map.symbol]);
      var qty = cleanNumber(cells[map.qty]);
      if (!sym || qty === null || qty <= 0) continue;
      out.push({
        symbol: sym,
        qty: qty,
        buy: map.buy !== undefined ? cleanNumber(cells[map.buy]) : null,
        date: map.date !== undefined ? cleanDate(cells[map.date]) : null
      });
    }
    return out;
  }

  /* ── 2. STATE ───────────────────────────────────────────────────────────── */

  var state = {
    rows: [],
    report: null,
    pollTimer: null,
    jobId: null,
    pendingCSV: null,
    activeName: null
  };

  function readStore() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function writeStore(obj) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(obj)); return true; }
    catch (e) { return false; }
  }
  function readPolicy() {
    try { return JSON.parse(localStorage.getItem(POLICY_KEY) || 'null'); }
    catch (e) { return null; }
  }
  function writePolicy(p) {
    try { localStorage.setItem(POLICY_KEY, JSON.stringify(p)); } catch (e) {}
  }

  var POLICY_FIELDS = [
    ['max_stock_pct', 'Max in one stock', '%', 15],
    ['max_sector_pct', 'Max in one sector', '%', 35],
    ['min_composite', 'Minimum score', '/100', 45],
    ['review_drawdown', 'Review if down', '%', 25],
    ['min_holdings', 'Minimum holdings', 'names', 8]
  ];

  function currentPolicy() {
    var p = {};
    POLICY_FIELDS.forEach(function (f) {
      var node = $('pol_' + f[0]);
      var v = node ? Number(node.value) : NaN;
      p[f[0]] = isFinite(v) && node.value !== '' ? v : f[3];
    });
    return p;
  }

  /* ── 3. HOLDINGS EDITOR ─────────────────────────────────────────────────── */

  function addRow(data) {
    data = data || {};
    if (state.rows.length >= MAX_ROWS) {
      note('Limit is ' + MAX_ROWS + ' holdings per analysis.', 'warn');
      return;
    }
    state.rows.push({
      symbol: data.symbol || '', qty: data.qty || '',
      buy: data.buy === undefined ? '' : (data.buy === null ? '' : data.buy),
      date: data.date || ''
    });
    renderRows();
  }

  function renderRows() {
    var host = $('pf_rows');
    if (!host) return;
    host.innerHTML = '';

    state.rows.forEach(function (r, i) {
      var row = el('div', 'pfrow');
      row.innerHTML =
        '<input class="pf_sym" placeholder="RELIANCE" spellcheck="false" ' +
          'aria-label="Symbol, row ' + (i + 1) + '" value="' + esc(r.symbol) + '">' +
        '<input class="pf_qty" type="number" min="0" step="any" placeholder="10" ' +
          'aria-label="Quantity, row ' + (i + 1) + '" value="' + esc(r.qty) + '">' +
        '<input class="pf_buy" type="number" min="0" step="any" placeholder="2400" ' +
          'aria-label="Average buy price, row ' + (i + 1) + '" value="' + esc(r.buy) + '">' +
        '<input class="pf_date" type="date" ' +
          'aria-label="Buy date, row ' + (i + 1) + '" value="' + esc(r.date) + '">' +
        '<button class="pfdel" type="button" aria-label="Remove row ' + (i + 1) + '">\u2715</button>';

      var sym = row.querySelector('.pf_sym');
      var qty = row.querySelector('.pf_qty');

      sym.addEventListener('input', function () {
        r.symbol = cleanSymbol(sym.value);
        validateRow(row, r);
        clearNote();
      });
      sym.addEventListener('blur', function () { sym.value = r.symbol; });
      qty.addEventListener('input', function () {
        r.qty = qty.value; validateRow(row, r); clearNote();
      });
      row.querySelector('.pf_buy').addEventListener('input', function () {
        r.buy = this.value;
      });
      row.querySelector('.pf_date').addEventListener('input', function () {
        r.date = this.value;
      });
      row.querySelector('.pfdel').addEventListener('click', function () {
        state.rows.splice(i, 1); renderRows(); clearNote();
      });

      host.appendChild(row);
    });

    var count = $('pf_count');
    if (count) {
      var filled = state.rows.filter(function (r) {
        return r.symbol && Number(r.qty) > 0;
      }).length;
      count.textContent = filled + ' of ' + state.rows.length + ' rows ready';
    }
  }

  /* Inline validation, live. The old module validated only on submit and had
     no way to show which row was at fault — a single banner said "add at
     least one holding" while the user was looking at holdings they had just
     typed. Marking the offending field directly removes that whole class of
     confusion. */
  function validateRow(row, r) {
    var symOK = !!r.symbol;
    var qtyOK = Number(r.qty) > 0;
    var touched = r.symbol !== '' || String(r.qty) !== '';
    row.querySelector('.pf_sym').classList.toggle('bad', touched && !symOK);
    row.querySelector('.pf_qty').classList.toggle('bad', touched && !qtyOK);
  }

  function collect() {
    return state.rows
      .filter(function (r) { return r.symbol && Number(r.qty) > 0; })
      .map(function (r) {
        var buy = r.buy === '' || r.buy === null ? null : Number(r.buy);
        return {
          symbol: r.symbol,
          qty: Number(r.qty),
          buy_price: isFinite(buy) ? buy : null,
          buy_date: r.date || null
        };
      });
  }

  function note(msg, kind) {
    var n = $('pf_note');
    if (!n) return;
    n.textContent = msg;
    n.className = 'brun-note' + (kind ? ' ' + kind : '');
  }
  function clearNote() { note('', ''); }

  /* ── 4. IMPORT ──────────────────────────────────────────────────────────── */

  function ingestText(text, sourceLabel) {
    var rows = parseCSV(text);
    if (!rows.length) { note('That file appears to be empty.', 'warn'); return; }

    var found = findHeader(rows);
    if (!found) {
      // Nothing recognisable. Rather than reject the file, show the user
      // their own columns and let them say which is which.
      state.pendingCSV = rows;
      openMapper(rows);
      return;
    }

    var parsed = rowsFromMap(rows, found.index, found.map);
    if (!parsed.length) {
      state.pendingCSV = rows;
      openMapper(rows);
      return;
    }
    applyImport(parsed, sourceLabel, found.map);
  }

  function applyImport(parsed, sourceLabel, map) {
    var over = parsed.length > MAX_ROWS;
    state.rows = parsed.slice(0, MAX_ROWS).map(function (p) {
      return {
        symbol: p.symbol, qty: p.qty,
        buy: p.buy === null || p.buy === undefined ? '' : p.buy,
        date: p.date || ''
      };
    });
    renderRows();

    var bits = ['Loaded ' + state.rows.length + ' holdings'];
    if (sourceLabel) bits.push('from ' + sourceLabel);
    if (over) bits.push('(first ' + MAX_ROWS + ' of ' + parsed.length + ')');
    if (map && map.buy === undefined) bits.push('\u2014 no cost column found, so profit and loss is unavailable');
    note(bits.join(' '), 'good');
  }

  /* Column mapper — the fallback that makes any broker's file work. */
  function openMapper(rows) {
    var panel = $('pf_mapper');
    if (!panel) return;
    var headerRow = rows[0] || [];

    var options = headerRow.map(function (h, i) {
      return '<option value="' + i + '">' + esc(h || ('Column ' + (i + 1))) + '</option>';
    }).join('');

    panel.innerHTML =
      '<div class="pfmap-head">We could not recognise the columns in that file. ' +
      'Tell us which is which \u2014 the first few rows are shown below.</div>' +
      '<div class="pfmap-grid">' +
        '<label><span>Symbol</span><select id="map_symbol">' + options + '</select></label>' +
        '<label><span>Quantity</span><select id="map_qty">' + options + '</select></label>' +
        '<label><span>Buy price <i>optional</i></span><select id="map_buy">' +
          '<option value="">\u2014 none \u2014</option>' + options + '</select></label>' +
        '<label><span>Header row</span><select id="map_head">' +
          rows.slice(0, 10).map(function (r, i) {
            return '<option value="' + i + '">Row ' + (i + 1) + ': ' +
                   esc(r.slice(0, 4).join(' | ').slice(0, 48)) + '</option>';
          }).join('') + '</select></label>' +
      '</div>' +
      '<div class="pfmap-preview">' +
        rows.slice(0, 4).map(function (r) {
          return '<div>' + r.slice(0, 6).map(function (c) {
            return '<span>' + esc(c.slice(0, 20)) + '</span>';
          }).join('') + '</div>';
        }).join('') +
      '</div>' +
      '<div class="pfmap-act">' +
        '<button type="button" class="pfbtn" id="map_go">Use these columns</button>' +
        '<button type="button" class="pfbtn ghost" id="map_cancel">Cancel</button>' +
      '</div>';

    panel.style.display = 'block';

    $('map_go').addEventListener('click', function () {
      var map = {
        symbol: Number($('map_symbol').value),
        qty: Number($('map_qty').value)
      };
      if ($('map_buy').value !== '') map.buy = Number($('map_buy').value);
      var head = Number($('map_head').value);
      var parsed = rowsFromMap(state.pendingCSV, head, map);
      if (!parsed.length) {
        panel.querySelector('.pfmap-head').textContent =
          'No usable rows with that mapping \u2014 check the quantity column holds numbers.';
        return;
      }
      applyImport(parsed, 'your mapping', map);
      closeMapper();
    });
    $('map_cancel').addEventListener('click', closeMapper);
  }

  function closeMapper() {
    var panel = $('pf_mapper');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    state.pendingCSV = null;
  }

  /* ── 5. SAVED PORTFOLIOS ────────────────────────────────────────────────── */

  function refreshSaved() {
    var sel = $('pf_saved');
    if (!sel) return;
    var store = readStore();
    var names = Object.keys(store).sort();
    sel.innerHTML = '<option value="">Saved portfolios\u2026</option>' +
      names.map(function (n) {
        return '<option value="' + esc(n) + '"' +
               (n === state.activeName ? ' selected' : '') + '>' + esc(n) + '</option>';
      }).join('');
    var del = $('pf_delete');
    if (del) del.disabled = !state.activeName;
  }

  function saveCurrent() {
    var holdings = collect();
    if (!holdings.length) { note('Nothing to save yet.', 'warn'); return; }
    var name = prompt('Name this portfolio', state.activeName || 'My portfolio');
    if (!name) return;
    name = name.trim().slice(0, 40);
    if (!name) return;

    var store = readStore();
    store[name] = { rows: state.rows, saved_at: new Date().toISOString() };
    if (!writeStore(store)) {
      note('Could not save \u2014 browser storage is full or blocked.', 'warn');
      return;
    }
    state.activeName = name;
    refreshSaved();
    note('Saved as "' + name + '". It stays in this browser only.', 'good');
  }

  function loadSaved(name) {
    if (!name) return;
    var entry = readStore()[name];
    if (!entry) return;
    state.rows = (entry.rows || []).slice(0, MAX_ROWS);
    state.activeName = name;
    renderRows();
    refreshSaved();
    note('Loaded "' + name + '".', 'good');
  }

  function deleteSaved() {
    if (!state.activeName) return;
    if (!confirm('Delete "' + state.activeName + '"? This cannot be undone.')) return;
    var store = readStore();
    delete store[state.activeName];
    writeStore(store);
    state.activeName = null;
    refreshSaved();
    note('Deleted.', '');
  }

  /* ── 6. ANALYSIS ────────────────────────────────────────────────────────── */

  function setBusy(on, msg) {
    var btn = $('pf_go');
    if (btn) { btn.disabled = on; btn.textContent = on ? 'Analysing\u2026' : 'Analyse portfolio'; }
    var st = $('pf_state');
    if (st) {
      st.style.display = on || msg ? 'block' : 'none';
      if (msg) st.innerHTML = msg;
    }
  }

  function progressBar(done, total) {
    var p = total ? Math.round(100 * done / total) : 0;
    return '<div class="pfprog"><i style="width:' + p + '%"></i></div>' +
           '<div class="pfprogtx">Scored ' + done + ' of ' + total + ' holdings</div>';
  }

  function analyse() {
    var holdings = collect();
    if (!holdings.length) {
      note('Enter a symbol and a quantity in at least one row.', 'warn');
      state.rows.forEach(function (r, i) {
        var row = $('pf_rows').children[i];
        if (row) validateRow(row, r);
      });
      return;
    }
    clearNote();
    closeMapper();
    var report = $('pf_report');
    if (report) report.style.display = 'none';

    setBusy(true, progressBar(0, holdings.length));
    var policy = currentPolicy();
    writePolicy(policy);

    fetch(API + '/portfolio/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: holdings, policy: policy })
    })
      .then(function (res) {
        return res.json().then(function (d) {
          if (!res.ok) throw new Error(d.detail || 'Analysis could not start.');
          return d;
        });
      })
      .then(function (d) { state.jobId = d.job_id; poll(); })
      .catch(function (err) {
        setBusy(false, '<b>' + esc(err.message) + '</b>');
      });
  }

  function poll() {
    clearTimeout(state.pollTimer);
    fetch(API + '/portfolio/status?job=' + encodeURIComponent(state.jobId))
      .then(function (res) {
        return res.json().then(function (d) {
          if (!res.ok) throw new Error(d.detail || 'Lost track of that analysis.');
          return d;
        });
      })
      .then(function (d) {
        if (d.status === 'running') {
          setBusy(true, progressBar(d.done, d.total));
          state.pollTimer = setTimeout(poll, 1400);
          return;
        }
        if (d.status === 'error') {
          setBusy(false, 'Analysis failed: ' + esc(d.error || 'unknown error'));
          return;
        }
        setBusy(false, '');
        render(d.report);
      })
      .catch(function (err) {
        setBusy(false, esc(err.message));
      });
  }

  /* ── 7. CHARTS ──────────────────────────────────────────────────────────── */
  /* Hand-rolled SVG. Every chart reads its colours from the stylesheet's
     custom properties, so dark mode needs no separate code path. */

  var PALETTE = ['#C8A84B', '#4C7A9E', '#7A9E6B', '#B5735C', '#8A7BA8',
                 '#C4915C', '#5E8F86', '#9E6B84', '#6B7A9E', '#A89060'];

  function svg(w, h, body, label) {
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" role="img" ' +
           'aria-label="' + esc(label || '') + '" class="pfsvg">' + body + '</svg>';
  }

  /* Donut — where the money sits. */
  function chartDonut(sectors) {
    var total = sectors.reduce(function (a, s) { return a + s.weight_pct; }, 0) || 1;
    var cx = 110, cy = 110, r = 84, thick = 30;
    var angle = -Math.PI / 2, out = '';

    sectors.forEach(function (s, i) {
      var frac = s.weight_pct / total;
      if (frac <= 0) return;
      var sweep = frac * Math.PI * 2;
      var end = angle + sweep;
      var large = sweep > Math.PI ? 1 : 0;
      var x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
      var x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
      out += '<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) +
             ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x2.toFixed(1) + ' ' + y2.toFixed(1) +
             '" fill="none" stroke="' + PALETTE[i % PALETTE.length] + '" ' +
             'stroke-width="' + thick + '"><title>' + esc(s.sector) + ' \u2014 ' +
             pct(s.weight_pct) + '</title></path>';
      angle = end;
    });

    out += '<text x="' + cx + '" y="' + (cy - 4) + '" text-anchor="middle" class="pfsvg-big">' +
           sectors.length + '</text>' +
           '<text x="' + cx + '" y="' + (cy + 14) + '" text-anchor="middle" class="pfsvg-sm">' +
           (sectors.length === 1 ? 'sector' : 'sectors') + '</text>';

    var legend = sectors.map(function (s, i) {
      return '<div class="pflg"><i style="background:' + PALETTE[i % PALETTE.length] + '"></i>' +
             '<span>' + esc(s.sector) + '</span><b>' + pct(s.weight_pct) + '</b></div>';
    }).join('');

    return '<div class="pfchart-split">' +
             svg(220, 220, out, 'Sector allocation') +
             '<div class="pflegend">' + legend + '</div>' +
           '</div>';
  }

  /* Active weight — your book against the index, diverging from centre. */
  function chartActive(sectors) {
    var rows = sectors.filter(function (s) { return s.active_weight_pct !== null; });
    if (!rows.length) return '';
    rows.sort(function (a, b) { return b.active_weight_pct - a.active_weight_pct; });

    var max = Math.max.apply(null, rows.map(function (s) {
      return Math.abs(s.active_weight_pct);
    })) || 1;
    var W = 620, mid = 300, barMax = 230, rowH = 30, pad = 16;
    var h = pad * 2 + rows.length * rowH + 18;
    var out = '<line x1="' + mid + '" y1="' + (pad - 4) + '" x2="' + mid + '" y2="' +
              (h - pad - 8) + '" class="pfaxis"/>';

    rows.forEach(function (s, i) {
      var y = pad + i * rowH;
      var w = Math.abs(s.active_weight_pct) / max * barMax;
      var over = s.active_weight_pct >= 0;
      var x = over ? mid : mid - w;
      out += '<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + w.toFixed(1) +
             '" height="17" rx="2" fill="' + (over ? 'var(--pf-over)' : 'var(--pf-under)') +
             '"><title>' + esc(s.sector) + ': you ' + pct(s.weight_pct) +
             ', index ' + pct(s.benchmark_weight_pct) + '</title></rect>';
      var lx = over ? mid - 8 : mid + 8;
      out += '<text x="' + lx + '" y="' + (y + 13) + '" class="pfsvg-sm" text-anchor="' +
             (over ? 'end' : 'start') + '">' + esc(s.sector) + '</text>';
      var vx = over ? mid + w + 8 : mid - w - 8;
      out += '<text x="' + vx.toFixed(1) + '" y="' + (y + 13) + '" class="pfsvg-num" ' +
             'text-anchor="' + (over ? 'start' : 'end') + '">' +
             (s.active_weight_pct >= 0 ? '+' : '') + s.active_weight_pct.toFixed(1) + '</text>';
    });

    out += '<text x="' + (mid - 8) + '" y="' + (h - 6) + '" class="pfsvg-sm" text-anchor="end">' +
           'underweight the index</text>' +
           '<text x="' + (mid + 8) + '" y="' + (h - 6) + '" class="pfsvg-sm">overweight</text>';

    return svg(W, h, out, 'Active weight versus the index');
  }

  /* Momentum quadrant. Relative strength across, direction of travel up. */
  function chartQuadrant(sectors) {
    var rows = sectors.filter(function (s) {
      return s.relative && s.relative['3M'] !== null && s.relative['3M'] !== undefined;
    });
    if (rows.length < 2) return '';

    var W = 620, H = 380, pad = 46;
    var xs = rows.map(function (s) { return s.relative['3M']; });
    var ys = rows.map(function (s) {
      var six = s.relative['6M'];
      return six === null || six === undefined ? 0 : s.relative['3M'] - six;
    });
    var xMax = Math.max(6, Math.max.apply(null, xs.map(Math.abs)) * 1.25);
    var yMax = Math.max(4, Math.max.apply(null, ys.map(Math.abs)) * 1.25);

    function px(v) { return pad + (v + xMax) / (2 * xMax) * (W - pad * 2); }
    function py(v) { return H - pad - (v + yMax) / (2 * yMax) * (H - pad * 2); }

    var cx = px(0), cy = py(0);
    var out =
      '<rect x="' + cx + '" y="' + pad + '" width="' + (W - pad - cx) + '" height="' + (cy - pad) +
        '" fill="var(--pf-q-lead)"/>' +
      '<rect x="' + pad + '" y="' + pad + '" width="' + (cx - pad) + '" height="' + (cy - pad) +
        '" fill="var(--pf-q-improve)"/>' +
      '<rect x="' + cx + '" y="' + cy + '" width="' + (W - pad - cx) + '" height="' + (H - pad - cy) +
        '" fill="var(--pf-q-weaken)"/>' +
      '<rect x="' + pad + '" y="' + cy + '" width="' + (cx - pad) + '" height="' + (H - pad - cy) +
        '" fill="var(--pf-q-lag)"/>' +
      '<line x1="' + pad + '" y1="' + cy + '" x2="' + (W - pad) + '" y2="' + cy + '" class="pfaxis"/>' +
      '<line x1="' + cx + '" y1="' + pad + '" x2="' + cx + '" y2="' + (H - pad) + '" class="pfaxis"/>' +
      '<text x="' + (W - pad - 8) + '" y="' + (pad + 16) + '" class="pfsvg-sm" text-anchor="end">Leading</text>' +
      '<text x="' + (pad + 8) + '" y="' + (pad + 16) + '" class="pfsvg-sm">Improving</text>' +
      '<text x="' + (W - pad - 8) + '" y="' + (H - pad - 8) + '" class="pfsvg-sm" text-anchor="end">Weakening</text>' +
      '<text x="' + (pad + 8) + '" y="' + (H - pad - 8) + '" class="pfsvg-sm">Lagging</text>';

    var maxW = Math.max.apply(null, rows.map(function (s) { return s.weight_pct || 0; })) || 1;

    rows.forEach(function (s, i) {
      var x = px(s.relative['3M']);
      var six = s.relative['6M'];
      var y = py(six === null || six === undefined ? 0 : s.relative['3M'] - six);
      var held = s.weight_pct || 0;
      var r = held > 0 ? 7 + Math.sqrt(held / maxW) * 16 : 5;
      var fill = held > 0 ? 'var(--pf-dot-held)' : 'var(--pf-dot-idle)';
      out += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + r.toFixed(1) +
             '" fill="' + fill + '" fill-opacity="' + (held > 0 ? '.62' : '.28') +
             '" stroke="' + (held > 0 ? 'var(--pf-dot-held)' : 'var(--pf-dot-idle)') +
             '" stroke-width="1.2"><title>' + esc(s.sector) + ' \u2014 ' + esc(s.state) +
             '. You hold ' + pct(held) + '</title></circle>' +
             '<text x="' + x.toFixed(1) + '" y="' + (y - r - 5).toFixed(1) +
             '" class="pfsvg-sm" text-anchor="middle">' + esc(shortSector(s.sector)) + '</text>';
    });

    out += '<text x="' + (W / 2) + '" y="' + (H - 10) +
           '" class="pfsvg-sm" text-anchor="middle">3-month return vs Nifty 50 \u2192</text>';

    return svg(W, H, out, 'Sector momentum quadrant');
  }

  function shortSector(s) {
    var map = {
      'Financial Services': 'Financials', 'Consumer Defensive': 'Cons. staples',
      'Consumer Cyclical': 'Cons. cyclical', 'Communication Services': 'Comms',
      'Basic Materials': 'Materials', 'Information Technology': 'Tech'
    };
    return map[s] || s;
  }

  /* Quality against weight. The quadrant that costs money is top-left:
     large positions carrying weak scores. No other retail dashboard shows
     this, and it is the single most useful view of a book. */
  function chartQualityWeight(holdings, policy) {
    var rows = holdings.filter(function (h) { return h.composite !== null && h.composite !== undefined; });
    if (rows.length < 2) return '';

    var W = 620, H = 360, pad = 52;
    var maxW = Math.max.apply(null, rows.map(function (h) { return h.weight_pct; }));
    var xTop = Math.max(maxW * 1.15, policy.max_stock_pct * 1.3);

    function px(v) { return pad + (v / xTop) * (W - pad * 2); }
    function py(v) { return H - pad - (v / 100) * (H - pad * 2); }

    var capX = px(policy.max_stock_pct);
    var floorY = py(policy.min_composite);

    var out =
      '<rect x="' + capX + '" y="' + floorY + '" width="' + (W - pad - capX) +
        '" height="' + (H - pad - floorY) + '" fill="var(--pf-q-lag)"/>' +
      '<line x1="' + capX + '" y1="' + pad + '" x2="' + capX + '" y2="' + (H - pad) +
        '" class="pfrule"/>' +
      '<line x1="' + pad + '" y1="' + floorY + '" x2="' + (W - pad) + '" y2="' + floorY +
        '" class="pfrule"/>' +
      '<text x="' + (capX + 6) + '" y="' + (pad + 12) + '" class="pfsvg-sm">your ' +
        policy.max_stock_pct + '% cap</text>' +
      '<text x="' + (pad + 4) + '" y="' + (floorY - 6) + '" class="pfsvg-sm">your score floor ' +
        policy.min_composite + '</text>' +
      '<text x="' + (W - pad - 6) + '" y="' + (H - pad - 8) + '" class="pfsvg-sm" ' +
        'text-anchor="end">large position, low score</text>';

    rows.forEach(function (h) {
      var x = px(h.weight_pct), y = py(h.composite);
      var breach = h.weight_pct > policy.max_stock_pct || h.composite < policy.min_composite;
      out += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="6" fill="' +
             (breach ? 'var(--pf-bad)' : 'var(--pf-good)') + '" fill-opacity=".75"><title>' +
             esc(h.symbol) + ' \u2014 ' + pct(h.weight_pct) + ' of book, score ' +
             h.composite + '</title></circle>' +
             '<text x="' + (x + 9).toFixed(1) + '" y="' + (y + 4).toFixed(1) +
             '" class="pfsvg-sm">' + esc(h.symbol) + '</text>';
    });

    out += '<text x="' + (W / 2) + '" y="' + (H - 12) + '" class="pfsvg-sm" text-anchor="middle">' +
           'weight in the book \u2192</text>' +
           '<text x="14" y="' + (H / 2) + '" class="pfsvg-sm" transform="rotate(-90 14 ' +
           (H / 2) + ')" text-anchor="middle">composite score \u2192</text>';

    return svg(W, H, out, 'Score against weight');
  }

  /* Contribution in rupees. Percentages hide the fact that a 40% gain on a
     small position matters less than a 9% gain on a large one. */
  function chartContribution(contributors) {
    if (!contributors || contributors.length < 2) return '';
    var top = contributors.slice(0, 5);
    var bottom = contributors.slice(-5).filter(function (c) {
      return top.indexOf(c) === -1;
    });
    var rows = top.concat(bottom);
    if (!rows.length) return '';

    var max = Math.max.apply(null, rows.map(function (c) { return Math.abs(c.pnl); })) || 1;
    var W = 620, mid = 250, barMax = 250, rowH = 28, pad = 14;
    var h = pad * 2 + rows.length * rowH;
    var out = '<line x1="' + mid + '" y1="' + (pad - 4) + '" x2="' + mid + '" y2="' +
              (h - pad + 2) + '" class="pfaxis"/>';

    rows.forEach(function (c, i) {
      var y = pad + i * rowH;
      var w = Math.abs(c.pnl) / max * barMax;
      var up = c.pnl >= 0;
      var x = up ? mid : mid - w;
      out += '<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + w.toFixed(1) +
             '" height="16" rx="2" fill="' + (up ? 'var(--pf-good)' : 'var(--pf-bad)') +
             '"><title>' + esc(c.symbol) + ': ' + inr(c.pnl) + '</title></rect>' +
             '<text x="' + (mid - (up ? 8 : w + 8)).toFixed(1) + '" y="' + (y + 12) +
             '" class="pfsvg-sm" text-anchor="end">' + esc(c.symbol) + '</text>' +
             '<text x="' + (up ? mid + w + 8 : mid - w - 8).toFixed(1) + '" y="' + (y + 12) +
             '" class="pfsvg-num" text-anchor="' + (up ? 'start' : 'end') + '">' +
             inrShort(c.pnl) + '</text>';
    });

    return svg(W, h, out, 'Contribution to profit and loss');
  }

  /* ── 8. RENDER ──────────────────────────────────────────────────────────── */

  function render(d) {
    state.report = d;
    var host = $('pf_report');
    if (!host) return;
    host.style.display = 'block';

    var pol = d.policy || {};
    var conc = d.concentration || {};
    var mom = d.sector_momentum || {};

    var pnlTxt, pnlCls = '';
    if (d.total_pnl === null || d.total_pnl === undefined) {
      pnlTxt = 'No buy prices entered \u2014 profit and loss unavailable';
      pnlCls = 'mute';
    } else {
      pnlTxt = (d.total_pnl >= 0 ? '+' : '\u2212') + inr(Math.abs(d.total_pnl)) +
               ' (' + (d.total_pnl_pct >= 0 ? '+' : '') + d.total_pnl_pct + '%) against cost ' +
               inr(d.total_cost);
      pnlCls = d.total_pnl >= 0 ? 'up' : 'down';
    }

    var breaches = (d.breaches || []).filter(function (b) { return b.level === 'breach'; });
    var notes = (d.breaches || []).filter(function (b) { return b.level !== 'breach'; });

    var html = '';

    /* Verdict */
    html +=
      '<div class="psec">' +
        '<div class="lh"><h3>Verdict</h3><span>' +
          (d.peer_source ? 'Peers from scan of ' + esc(d.peer_source) : '') + '</span></div>' +
        '<div class="pvhead">' +
          '<div class="pvbig"><span class="k">Current value</span>' +
            '<span class="pvnum">' + inr(d.total_value) + '</span>' +
            '<span class="pvsub ' + pnlCls + '">' + esc(pnlTxt) + '</span></div>' +
          '<div class="pvgrade"><span class="k">Weighted score</span>' +
            '<span class="pvletter g' + esc(d.grade).replace(/\+/, 'p') + '">' + esc(d.grade) + '</span>' +
            '<span class="pvsub">' + (d.weighted_score !== null ? d.weighted_score + '/100' : '') +
            '</span></div>' +
        '</div>' +
        '<div class="pfstats">' +
          stat('Holdings', conc.count) +
          stat('Effective holdings', conc.effective_n, 'Weights concentrate ' + conc.count +
               ' names into the equivalent of this many equally-sized positions.') +
          stat('Top 3 weight', pct(conc.top3_pct)) +
          stat('Largest position', pct(conc.top1_pct)) +
          stat('Rule breaches', breaches.length) +
        '</div>' +
      '</div>';

    /* Rulebook audit */
    html += '<div class="psec">' +
      '<div class="lh"><h3>Rulebook</h3><span>' + breaches.length +
        ' breach' + (breaches.length === 1 ? '' : 'es') + ' of your limits</span></div>';

    if (!breaches.length) {
      html += '<div class="pff good">At current prices and weights the book sits inside ' +
              'every limit you set.</div>';
    } else {
      html += breaches.map(function (b) {
        return '<div class="pfbreach">' +
          '<div class="pfb-head"><span class="pfb-title">' + esc(b.title) + '</span>' +
          '<span class="pfb-meter">' + fmtMeasured(b) + '</span></div>' +
          '<p>' + esc(b.text) + '</p></div>';
      }).join('');
    }
    html += notes.map(function (b) {
      return '<div class="pff note">' + esc(b.text) + '</div>';
    }).join('');
    html += (d.observations || []).map(function (o) {
      return '<div class="pff ' + esc(o.level) + '"><b>' + esc(o.title) + '</b> ' +
             esc(o.text) + '</div>';
    }).join('');
    html += '</div>';

    /* Allocation */
    html += '<div class="psec">' +
      '<div class="lh"><h3>Where the money sits</h3><span>By current value</span></div>' +
      chartDonut(d.sectors || []) + '</div>';

    /* Active weight + momentum */
    if (mom.available) {
      var active = chartActive(d.sectors || []);
      if (active) {
        html += '<div class="psec">' +
          '<div class="lh"><h3>Against the index</h3><span>Nifty 500 weights, ' +
            esc(mom.benchmark_weights_asof || '') + '</span></div>' +
          '<p class="pfnote">Holding 30% financials is not by itself a bet \u2014 the index ' +
          'already carries roughly that much. What follows is the difference.</p>' +
          active + '</div>';
      }

      var quad = chartQuadrant(mom.sectors || []);
      if (quad) {
        html += '<div class="psec">' +
          '<div class="lh"><h3>Sector momentum</h3><span>Measured ' +
            esc(mom.measured_at || '') + '</span></div>' +
          '<p class="pfnote">Every NSE sector index placed against the Nifty 50. ' +
          'Filled circles are sectors you hold, sized by weight. This is measured ' +
          'past return over the stated windows \u2014 not a forecast.</p>' +
          quad +
          '<details class="pfmeth"><summary>How this is measured</summary><p>' +
            esc(mom.method || '') + '</p></details>' +
          '</div>';
      }

      html += '<div class="psec">' +
        '<div class="lh"><h3>Sector detail</h3><span>Your weight against index returns</span></div>' +
        sectorTable(d.sectors || []) + '</div>';
    } else {
      html += '<div class="psec"><div class="pff note">' +
        esc(mom.message || 'Sector momentum is unavailable right now.') + '</div></div>';
    }

    /* Quality vs weight */
    var qw = chartQualityWeight(d.holdings || [], pol);
    if (qw) {
      html += '<div class="psec">' +
        '<div class="lh"><h3>Score against weight</h3><span>Your rules drawn on</span></div>' +
        '<p class="pfnote">The shaded corner is the one worth attention: positions that are ' +
        'both larger than your cap and weaker than your floor.</p>' + qw + '</div>';
    }

    /* Contribution */
    var contrib = chartContribution(d.contributors || []);
    if (contrib) {
      html += '<div class="psec">' +
        '<div class="lh"><h3>What moved the book</h3><span>Unrealised, in rupees</span></div>' +
        '<p class="pfnote">In rupees rather than percentages \u2014 a 40% gain on a small ' +
        'position moves less money than a 9% gain on a large one.</p>' + contrib + '</div>';
    }

    /* Holdings ledger */
    html += '<div class="psec">' +
      '<div class="lh"><h3>Holdings</h3><span>Tap a row for detail</span></div>' +
      (d.holdings || []).map(function (r) { return holdingRow(r, d, pol); }).join('') +
      ((d.failed || []).length
        ? '<div class="ideas-note">Could not analyse: ' +
          d.failed.map(function (f) { return esc(f.symbol) + ' (' + esc(f.error) + ')'; }).join(', ') +
          '</div>'
        : '') +
      '</div>';

    html += '<p class="disc">' + esc(d.disclaimer || '') + '</p>';

    host.innerHTML = html;
    host.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function fmtMeasured(b) {
    if (b.rule === 'min_holdings') return b.measured + ' vs ' + b.limit + ' min';
    if (b.rule === 'min_composite') return b.measured + ' vs ' + b.limit + ' floor';
    if (b.rule === 'review_drawdown') return b.measured + '% vs ' + b.limit + '%';
    return Number(b.measured).toFixed(1) + '% vs ' + Number(b.limit).toFixed(0) + '% cap';
  }

  function stat(label, value, tip) {
    return '<div class="pfstat"' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' +
           '<span class="k">' + esc(label) + '</span>' +
           '<span class="v">' + esc(value === null || value === undefined ? '\u2014' : value) +
           '</span></div>';
  }

  function sectorTable(sectors) {
    return '<div class="pfsectbl"><div class="pfst-head">' +
      '<span>Sector</span><span>You</span><span>Index</span><span>Active</span>' +
      '<span>3M vs Nifty</span><span>State</span></div>' +
      sectors.map(function (s) {
        var rel = s.relative && s.relative['3M'];
        return '<div class="pfst-row">' +
          '<span class="nm">' + esc(s.sector) + '<small>' + s.count + ' holding' +
            (s.count === 1 ? '' : 's') + (s.index_name ? ' \u00B7 ' + esc(s.index_name) : '') +
            '</small></span>' +
          '<span>' + pct(s.weight_pct) + '</span>' +
          '<span class="mute">' + (s.benchmark_weight_pct !== null ? pct(s.benchmark_weight_pct) : '\u2014') + '</span>' +
          '<span class="' + (s.active_weight_pct > 0 ? 'up' : s.active_weight_pct < 0 ? 'down' : '') + '">' +
            (s.active_weight_pct === null || s.active_weight_pct === undefined ? '\u2014' :
             (s.active_weight_pct > 0 ? '+' : '') + s.active_weight_pct.toFixed(1)) + '</span>' +
          '<span class="' + (rel > 0 ? 'up' : rel < 0 ? 'down' : '') + '">' +
            (rel === null || rel === undefined ? '\u2014' : (rel > 0 ? '+' : '') + rel.toFixed(1) + '%') + '</span>' +
          '<span class="pfstate ' + esc(String(s.state || '').toLowerCase()) + '">' +
            esc(s.state || '\u2014') + '</span>' +
        '</div>';
      }).join('') + '</div>';
  }

  function holdingRow(r, d, pol) {
    var breach = r.weight_pct > pol.max_stock_pct ||
                 (r.composite !== null && r.composite < pol.min_composite);
    var pnl = (r.pnl_pct === null || r.pnl_pct === undefined) ? '' :
      '<span class="' + (r.pnl_pct >= 0 ? 'up' : 'down') + '">' +
      (r.pnl_pct >= 0 ? '+' : '') + r.pnl_pct + '%</span>';

    var peers = (r.peers && r.peers.length)
      ? 'Sector peers by score: ' + r.peers.map(function (p) {
          return '<b>' + esc(p.symbol) + '</b> ' + (p.composite === null ? '\u2014' : p.composite);
        }).join(', ')
      : esc(d.peers_note || 'No same-sector peers in the last scan.');

    return '<details class="pfh' + (breach ? ' breach' : '') + '"><summary>' +
      '<span class="sym">' + esc(r.symbol) + '<small>' + esc(r.sector || 'sector n/a') +
        (r.sector_source === 'bundled map' ? ' \u00B7 inferred' : '') +
        ' \u00B7 ' + pct(r.weight_pct) + ' of book</small></span>' +
      '<span class="m">' + r.qty + ' \u00D7 \u20B9' +
        Number(r.price).toLocaleString('en-IN') + '</span>' +
      '<span class="m">' + pnl + '</span>' +
      '<span class="setup">' + esc(r.setup || '\u2014') + '</span>' +
      '<span class="comp' + (r.composite >= 72 ? ' hi' : r.composite < 40 ? ' lo' : '') + '">' +
        (r.composite === null || r.composite === undefined ? '\u2014' : r.composite) + '</span>' +
      '</summary><div class="body">' +
        '<div class="pfpeer">Value ' + inr(r.value) +
          (r.cost !== null && r.cost !== undefined ? ' \u00B7 cost ' + inr(r.cost) : '') +
          ' \u00B7 Technical ' + (r.technical === null ? '\u2014' : r.technical) +
          ' \u00B7 Fundamental ' + (r.fundamental === null ? '\u2014' : r.fundamental) +
          (r.horizon && r.horizon !== '\u2014' ? ' \u00B7 typical hold ' + esc(r.horizon) : '') +
          ' \u2014 the full ledger is in the Screener</div>' +
        '<div class="pfpeer">' + peers + '</div>' +
      '</div></details>';
  }

  /* ── 9. EXPORT ──────────────────────────────────────────────────────────── */

  function exportCSV() {
    var d = state.report;
    if (!d) { note('Run an analysis first.', 'warn'); return; }
    var lines = [['Symbol', 'Sector', 'Qty', 'Price', 'Value', 'Cost',
                  'PnL', 'PnL%', 'Weight%', 'Score', 'Setup'].join(',')];
    (d.holdings || []).forEach(function (r) {
      lines.push([r.symbol, '"' + (r.sector || '') + '"', r.qty, r.price, r.value,
                  r.cost === null ? '' : r.cost, r.pnl === null ? '' : r.pnl,
                  r.pnl_pct === null ? '' : r.pnl_pct, r.weight_pct,
                  r.composite === null ? '' : r.composite,
                  '"' + (r.setup || '') + '"'].join(','));
    });
    var blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'altaha-portfolio-' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ── 10. INIT ───────────────────────────────────────────────────────────── */

  function init() {
    if (!$('pf_rows')) return;

    // Restore the rulebook the user last used.
    var saved = readPolicy();
    if (saved) {
      POLICY_FIELDS.forEach(function (f) {
        var node = $('pol_' + f[0]);
        if (node && saved[f[0]] !== undefined) node.value = saved[f[0]];
      });
    }

    // Start with one empty row, not three pre-filled samples. Sample rows
    // made users unsure whether to edit or replace them.
    if (!state.rows.length) addRow();

    $('pf_addrow').addEventListener('click', function () { addRow(); });
    $('pf_go').addEventListener('click', analyse);

    $('pf_file').addEventListener('change', function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () { ingestText(String(reader.result), f.name); };
      reader.onerror = function () { note('That file could not be read.', 'warn'); };
      reader.readAsText(f);
      ev.target.value = '';
    });

    // Paste straight from a broker's web page. The clipboard carries the
    // table as tab-separated text, which the same parser handles.
    var paste = $('pf_paste');
    if (paste) {
      paste.addEventListener('paste', function (ev) {
        var text = (ev.clipboardData || window.clipboardData).getData('text');
        if (!text || !text.trim()) return;
        ev.preventDefault();
        ingestText(text, 'pasted table');
        paste.value = '';
      });
    }

    $('pf_tmpl').href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(
      'Symbol,Quantity,BuyPrice,BuyDate\n' +
      'RELIANCE,10,2450,2024-06-14\n' +
      'TCS,5,3900,2024-08-02\n' +
      'HDFCBANK,15,,\n');

    $('pf_save').addEventListener('click', saveCurrent);
    $('pf_delete').addEventListener('click', deleteSaved);
    $('pf_saved').addEventListener('change', function () { loadSaved(this.value); });
    $('pf_clear').addEventListener('click', function () {
      if (!confirm('Clear all rows?')) return;
      state.rows = []; state.activeName = null;
      addRow(); refreshSaved(); clearNote();
      var rep = $('pf_report'); if (rep) rep.style.display = 'none';
    });
    var exp = $('pf_export');
    if (exp) exp.addEventListener('click', exportCSV);

    var reset = $('pol_reset');
    if (reset) reset.addEventListener('click', function () {
      POLICY_FIELDS.forEach(function (f) {
        var node = $('pol_' + f[0]);
        if (node) node.value = f[3];
      });
      writePolicy(currentPolicy());
    });

    refreshSaved();
    renderRows();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.AltahaPortfolio = { parseCSV: parseCSV, findHeader: findHeader, init: init };
})();

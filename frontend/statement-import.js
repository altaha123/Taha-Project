/* Altaha — reading a broker's holdings statement, in the browser

   WHAT THIS IS FOR
   A portfolio manager downloads each client's holdings statement from the
   broker — Groww, Zerodha, Upstox, Angel One, Dhan, ICICI Direct — and wants
   the desk brought up to date from it. Every broker lays the file out its own
   way: a few lines of account details, then a table whose columns are named
   "Stock Name" or "Instrument" or "Scrip", "Quantity" or "Qty.", "Average buy
   price" or "Avg. cost". This finds the table, reads it, and turns every row
   into {symbol, qty, avg, close}.

   THE FILE NEVER LEAVES THE BROWSER
   The first lines of a statement carry the client's name and client code,
   sometimes a phone number and an email address. None of that is needed to
   update a portfolio, so the file is opened here, on this device. What is sent
   is one row per holding — the symbol, how many, at what price — and, to turn
   an ISIN into a symbol, the ISINs, which identify a security, not a person.
   The client's name is read only to warn when a statement is somebody else's.

   XLSX WITHOUT A LIBRARY
   An .xlsx file is a zip of XML. The zip's directory says where each part
   is; the parts are deflated, and every browser this site supports can
   inflate them (DecompressionStream). The sheet's cells are read with a few
   regular expressions — machine-written XML, not prose — so no parser and
   no third-party script are needed. An old binary .xls is not this format:
   the page asks for .xlsx or CSV instead.

   Exposed as window.AltahaStatement, and to node for the unit test.
*/

(function (root) {
  'use strict';

  /* ── CSV ─────────────────────────────────────────────────────────────── */

  function sniffDelimiter(text) {
    var line = String(text).split(/\r?\n/).find(function (l) { return l.trim(); }) || '';
    var counts = { ',': 0, ';': 0, '\t': 0, '|': 0 }, inQ = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (c === '"') inQ = !inQ;
      else if (!inQ && counts[c] !== undefined) counts[c]++;
    }
    var best = ',', n = 0;
    Object.keys(counts).forEach(function (d) { if (counts[d] > n) { n = counts[d]; best = d; } });
    return best;
  }

  function parseCSV(text, delim) {
    text = String(text || '').replace(/^﻿/, '');
    delim = delim || sniffDelimiter(text);
    var rows = [], field = '', row = [], inQ = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (inQ) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
        else field += c;
        continue;
      }
      if (c === '"') { inQ = true; continue; }
      if (c === delim) { row.push(field); field = ''; continue; }
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue; }
      if (c === '\r') continue;
      field += c;
    }
    if (field.length || row.length) { row.push(field); rows.push(row); }
    return rows.map(function (r) { return r.map(function (f) { return f.trim(); }); });
  }

  /* ── XLSX ────────────────────────────────────────────────────────────── */

  function u32(dv, o) { return dv.getUint32(o, true); }
  function u16(dv, o) { return dv.getUint16(o, true); }

  function zipIndex(buf) {
    var u8 = new Uint8Array(buf), dv = new DataView(buf), eocd = -1;
    for (var i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) {
      if (u32(dv, i) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('This does not look like an .xlsx file.');
    var n = u16(dv, eocd + 10), off = u32(dv, eocd + 16), files = {};
    var dec = new TextDecoder();
    for (var k = 0; k < n && off + 46 <= u8.length; k++) {
      if (u32(dv, off) !== 0x02014b50) break;
      var nlen = u16(dv, off + 28), xlen = u16(dv, off + 30), clen = u16(dv, off + 32);
      var name = dec.decode(u8.subarray(off + 46, off + 46 + nlen));
      files[name] = { method: u16(dv, off + 10), size: u32(dv, off + 20), at: u32(dv, off + 42) };
      off += 46 + nlen + xlen + clen;
    }
    return { u8: u8, dv: dv, files: files };
  }

  function zipText(z, name) {
    var f = z.files[name];
    if (!f) return Promise.resolve(null);
    var p = f.at, start = p + 30 + u16(z.dv, p + 26) + u16(z.dv, p + 28);
    var data = z.u8.slice(start, start + f.size);
    if (f.method === 0) return Promise.resolve(new TextDecoder().decode(data));
    if (f.method !== 8) return Promise.reject(new Error('This .xlsx is compressed in a way that cannot be read here. Save it as CSV.'));
    if (typeof DecompressionStream === 'undefined') {
      return Promise.reject(new Error('This browser cannot open .xlsx files. Save the statement as CSV and upload that.'));
    }
    var stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Response(stream).arrayBuffer().then(function (b) { return new TextDecoder().decode(b); });
  }

  function unxml(s) {
    return String(s)
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'")
      .replace(/&#x([0-9a-f]+);/gi, function (m, h) { return String.fromCharCode(parseInt(h, 16)); })
      .replace(/&#(\d+);/g, function (m, d) { return String.fromCharCode(+d); })
      .replace(/&amp;/g, '&');
  }

  function texts(xml) {
    var out = [], re = /<t\b[^>]*>([\s\S]*?)<\/t>/g, m;
    while ((m = re.exec(xml))) out.push(unxml(m[1]));
    return out.join('');
  }

  function colIndex(ref) {
    var letters = String(ref || '').replace(/[^A-Z]/gi, '').toUpperCase(), n = 0;
    for (var i = 0; i < letters.length; i++) n = n * 26 + (letters.charCodeAt(i) - 64);
    return n - 1;
  }

  function attr(attrs, name) {
    var m = new RegExp('\\b' + name + '="([^"]*)"').exec(attrs);
    return m ? m[1] : null;
  }

  function sheetRows(xml, shared) {
    var rows = [], rre = /<row\b([^>]*?)(?:\/>|>([\s\S]*?)<\/row>)/g, rm;
    while ((rm = rre.exec(xml))) {
      var cells = [], body = rm[2] || '', cre = /<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g, cm, next = 0;
      while ((cm = cre.exec(body))) {
        var a = cm[1], inner = cm[2] || '', t = attr(a, 't'), ref = attr(a, 'r');
        var at = ref ? colIndex(ref) : next;
        next = at + 1;
        var v = /<v>([\s\S]*?)<\/v>/.exec(inner), val = '';
        if (t === 's') val = v ? (shared[+v[1]] || '') : '';
        else if (t === 'inlineStr') val = texts(inner);
        else if (t === 'b') val = v && v[1] === '1' ? 'TRUE' : 'FALSE';
        else val = v ? unxml(v[1]) : '';
        while (cells.length < at) cells.push('');
        cells[at] = String(val).trim();
      }
      rows.push(cells);
    }
    return rows;
  }

  function readXlsx(buf) {
    var z;
    try { z = zipIndex(buf); } catch (e) { return Promise.reject(e); }
    var sheet = z.files['xl/worksheets/sheet1.xml'] ? 'xl/worksheets/sheet1.xml'
      : Object.keys(z.files).filter(function (n) { return /^xl\/worksheets\/[^/]+\.xml$/.test(n); }).sort()[0];
    if (!sheet) return Promise.reject(new Error('That workbook has no sheet in it.'));
    return Promise.all([zipText(z, 'xl/sharedStrings.xml'), zipText(z, sheet)]).then(function (parts) {
      var shared = [];
      var sre = /<si\b[^>]*>([\s\S]*?)<\/si>/g, m;
      while (parts[0] && (m = sre.exec(parts[0]))) shared.push(texts(m[1]));
      return sheetRows(parts[1] || '', shared);
    });
  }

  /* A File (or Blob) to rows of cells, whichever format it is. */
  function readFile(file) {
    var name = String((file && file.name) || '').toLowerCase();
    if (/\.xls$/.test(name)) {
      return Promise.reject(new Error('This is an old .xls file. Open it and save it as .xlsx or CSV, then upload that.'));
    }
    return file.arrayBuffer().then(function (buf) {
      var head = new Uint8Array(buf.slice(0, 4));
      if (head[0] === 0x50 && head[1] === 0x4b) return readXlsx(buf).then(function (rows) { return { rows: rows, kind: 'xlsx' }; });
      if (head[0] === 0xd0 && head[1] === 0xcf) {
        throw new Error('This is an old .xls file. Open it and save it as .xlsx or CSV, then upload that.');
      }
      return { rows: parseCSV(new TextDecoder().decode(buf)), kind: 'csv' };
    });
  }

  /* ── Finding the table ───────────────────────────────────────────────── */

  // Normalised: lowercase, letters and digits only. Exact or prefix match.
  var HINTS = {
    isin: ['isin', 'isincode', 'isinno', 'isinnumber'],
    symbol: ['symbol', 'tradingsymbol', 'ticker', 'nsesymbol', 'nsecode', 'instrument', 'scrip', 'scripcode',
             'stocksymbol', 'securitycode', 'tradesymbol'],
    name: ['stockname', 'companyname', 'company', 'securityname', 'security', 'scripname', 'stock',
           'instrumentname', 'name', 'description', 'particulars'],
    qty: ['quantity', 'qty', 'shares', 'holdingqty', 'holdingquantity', 'netqty', 'totalqty', 'totalquantity',
          'quantityavailable', 'availableqty', 'freeqty', 'balance', 'units', 'noofshares', 'currentqty'],
    avg: ['averagebuyprice', 'avgbuyprice', 'averageprice', 'avgprice', 'avgcost', 'averagecost', 'buyprice',
          'buyavg', 'costprice', 'purchaseprice', 'avgbuyrate', 'averagebuyrate', 'buyrate', 'avgrate',
          'averagerate', 'netavgprice', 'avgtradedprice', 'holdingavgprice', 'avg', 'price', 'rate'],
    close: ['closingprice', 'closeprice', 'close', 'ltp', 'lastprice', 'lasttradedprice', 'currentprice',
            'marketprice', 'cmp', 'currentmarketprice', 'previousclose', 'prevclose', 'closingrate', 'marketrate'],
    date: ['buydate', 'purchasedate', 'tradedate', 'transactiondate', 'dateofpurchase', 'date'],
    rec: ['recommendedprice', 'recommended', 'recoprice', 'reco', 'recprice', 'advisedprice', 'callprice']
  };
  var ORDER = ['isin', 'symbol', 'name', 'qty', 'avg', 'close', 'date', 'rec'];

  function key(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

  function kindOf(header) {
    var k = key(header);
    if (!k) return null;
    for (var i = 0; i < ORDER.length; i++) if (HINTS[ORDER[i]].indexOf(k) !== -1) return ORDER[i];
    for (var j = 0; j < ORDER.length; j++) {
      var hs = HINTS[ORDER[j]];
      for (var h = 0; h < hs.length; h++) if (hs[h].length >= 4 && k.indexOf(hs[h]) === 0) return ORDER[j];
    }
    return null;
  }

  function findHeader(rows) {
    var best = null;
    for (var i = 0; i < Math.min(40, rows.length); i++) {
      var map = {}, score = 0;
      (rows[i] || []).forEach(function (cell, c) {
        var k = kindOf(cell);
        if (k && map[k] === undefined) { map[k] = c; score++; }
      });
      if (map.qty !== undefined && (map.symbol !== undefined || map.name !== undefined || map.isin !== undefined) &&
          (!best || score > best.score)) {
        best = { index: i, map: map, score: score };
      }
    }
    return best;
  }

  function num(raw) {
    if (raw === null || raw === undefined) return null;
    var s = String(raw).replace(/[₹$,\s]/g, '');
    var neg = /^\(.*\)$/.test(s);
    s = s.replace(/[()]/g, '');
    if (s === '' || s === '-' || s === '—') return null;
    var n = Number(s);
    return isFinite(n) ? (neg ? -n : n) : null;
  }

  var MON = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12 };

  function isoDate(d, m, y) {
    y = +y; if (y < 100) y += 2000;
    m = isNaN(+m) ? MON[String(m).slice(0, 3).toLowerCase()] : +m;
    d = +d;
    if (!y || !m || !d || m > 12 || d > 31) return null;
    return y + '-' + ('0' + m).slice(-2) + '-' + ('0' + d).slice(-2);
  }

  function date(raw) {
    if (raw === null || raw === undefined || raw === '') return null;
    var s = String(raw).trim(), m;
    if ((m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s))) return m[1] + '-' + m[2] + '-' + m[3];
    if ((m = /^(\d{1,2})[-\/. ](\d{1,2}|[A-Za-z]{3,9})[-\/. ,]+(\d{2,4})$/.exec(s))) return isoDate(m[1], m[2], m[3]);
    var n = Number(s);
    if (isFinite(n) && n > 20000 && n < 80000) {          // an Excel serial day
      return new Date(Date.UTC(1899, 11, 30) + Math.round(n) * 86400000).toISOString().slice(0, 10);
    }
    return null;
  }

  var AS_OF = /\b(?:as\s+on|as\s+of|as\s+at|for|dated|on)\s*:?\s*(\d{1,2})[-\/. ](\d{1,2}|[A-Za-z]{3,9})[-\/. ,]+(\d{2,4})\b/i;
  var SUMMARY = /^(total|grand\s*total|net\s*total|sub\s*total|summary|overall|investment|invested\s*value|closing\s*value|unrealised\s*p&?l|opening\s*balance|closing\s*balance)$/i;
  var NAME_KEYS = ['name', 'clientname', 'accountname', 'holdername', 'investorname', 'customername', 'accountholder'];
  var CODE_KEYS = ['uniqueclientcode', 'clientcode', 'clientid', 'ucc', 'userid', 'accountid', 'boid', 'dpclientid'];

  /* Rows of cells into the statement: who it is for (kept on this page),
     the date it is as on, and one entry per holding. */
  function extract(rows, filename) {
    rows = (rows || []).filter(function (r) { return r && r.some(function (c) { return String(c || '').trim() !== ''; }); });
    var meta = { client: '', code: '', as_of: null };
    var h = findHeader(rows);
    var top = h ? rows.slice(0, h.index) : rows.slice(0, 10);
    top.forEach(function (r) {
      var k = key(r[0]), v = String(r[1] || '').trim();
      if (!meta.client && NAME_KEYS.indexOf(k) !== -1 && v) meta.client = v;
      if (!meta.code && CODE_KEYS.indexOf(k) !== -1 && v) meta.code = v;
      r.forEach(function (cell) {
        var m = !meta.as_of && AS_OF.exec(String(cell || ''));
        if (m) meta.as_of = isoDate(m[1], m[2], m[3]);
      });
    });
    if (!meta.as_of && filename) {
      var fm = /(\d{2})[-_.](\d{2})[-_.](\d{4})/.exec(filename) || /(\d{4})[-_.](\d{2})[-_.](\d{2})/.exec(filename);
      if (fm) meta.as_of = fm[1].length === 4 ? fm[1] + '-' + fm[2] + '-' + fm[3] : isoDate(fm[1], fm[2], fm[3]);
    }
    var map = h ? h.map : null, body = h ? rows.slice(h.index + 1) : rows;
    if (!map) {
      // No header: the columns a person typing a list would use.
      map = { symbol: 0, qty: 1, avg: 2, date: 3, rec: 4 };
    }
    var holdings = [], skipped = 0;
    body.forEach(function (r) {
      function at(k) { return map[k] === undefined ? '' : String(r[map[k]] === undefined ? '' : r[map[k]]).trim(); }
      var label = at('name') || at('symbol') || at('isin');
      var q = num(at('qty'));
      if (!label || SUMMARY.test(label) || q === null || q <= 0) { if (label) skipped++; return; }
      holdings.push({
        label: label, name: at('name'), symbol: cleanSymbol(at('symbol')), isin: at('isin').toUpperCase(),
        qty: q, avg: num(at('avg')), close: num(at('close')), rec: num(at('rec')), date: date(at('date'))
      });
    });
    return { meta: meta, holdings: holdings, skipped: skipped, header: !!h, columns: map };
  }

  /* ── Names into symbols ──────────────────────────────────────────────── */

  var NOISE = /\b(limited|ltd|private|pvt|company|co|corporation|corp|inc|plc|the)\b/g;

  function cleanSymbol(raw) {
    return String(raw || '').trim().toUpperCase().replace(/\.(NS|BO)$/i, '').replace(/^NSE:|^BSE:/, '')
      .replace(/-(EQ|BE|BZ|SM|ST)$/, '').replace(/[^A-Z0-9&\-]/g, '');
  }

  // A statement column too narrow for the whole name cuts "Limited" short:
  // "TAMILNADU PETROPRODUCTS L". The cut-off word is noise like the rest.
  function normName(s) {
    return String(s || '').toLowerCase()
      .replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ')
      .replace(NOISE, ' ').replace(/\s+/g, ' ').trim()
      .replace(/\s(l|li|lim|limi|limit|limite|lt|ltd)$/, '').trim();
  }

  function indexUniverse(rows) {
    var bySymbol = {}, byName = {}, list = [];
    (rows || []).forEach(function (r) {
      var s = String((r && (r.s || r.symbol)) || '').trim().toUpperCase();
      if (!s) return;
      bySymbol[s] = true;
      var n = normName(r.n || r.name);
      if (!n) return;
      (byName[n] = byName[n] || []).push(s);
      list.push({ n: n, s: s });
    });
    return { bySymbol: bySymbol, byName: byName, list: list, size: Object.keys(bySymbol).length };
  }

  function byName(raw, idx) {
    var k = normName(raw);
    if (!k) return { symbol: null, candidates: [] };
    var exact = idx.byName[k];
    if (exact && exact.length === 1) return { symbol: exact[0], candidates: [] };
    if (exact && exact.length > 1) return { symbol: null, candidates: exact.slice(0, 6) };
    var starts = idx.list.filter(function (r) { return r.n.indexOf(k + ' ') === 0 || k.indexOf(r.n + ' ') === 0; });
    if (starts.length === 1) return { symbol: starts[0].s, candidates: [] };
    if (starts.length > 1) return { symbol: null, candidates: starts.slice(0, 6).map(function (r) { return r.s; }) };
    // The last word cut short: "TATA CONSULTANCY SERV" is Tata Consultancy
    // Services. Every earlier word must match whole, the last as a prefix.
    var kt = k.split(' ');
    if (kt.length >= 2 && kt[kt.length - 1].length >= 3) {
      var cut = idx.list.filter(function (r) {
        var t = r.n.split(' ');
        if (t.length < kt.length) return false;
        for (var i = 0; i < kt.length - 1; i++) if (t[i] !== kt[i]) return false;
        return t[kt.length - 1].indexOf(kt[kt.length - 1]) === 0;
      });
      if (cut.length === 1) return { symbol: cut[0].s, candidates: [] };
      if (cut.length > 1) return { symbol: null, candidates: cut.slice(0, 6).map(function (r) { return r.s; }) };
    }
    var want = k.split(' '), scored = [];
    idx.list.forEach(function (r) {
      var have = r.n.split(' '), hit = 0;
      want.forEach(function (w) { if (have.indexOf(w) !== -1) hit++; });
      if (hit) {
        var sc = hit / Math.max(want.length, have.length);
        if (sc >= 0.5) scored.push({ s: r.s, sc: sc });
      }
    });
    scored.sort(function (a, b) { return b.sc - a.sc; });
    return { symbol: null, candidates: scored.slice(0, 5).map(function (r) { return r.s; }) };
  }

  /* Every holding gets a symbol, and says how it was found: by its ISIN (an
     exact match), by its ticker, or by its name. One that cannot be matched
     carries the closest few to choose from. */
  function resolve(holdings, idx, isinMap) {
    idx = idx || indexUniverse([]);
    isinMap = isinMap || {};
    return holdings.map(function (h) {
      var out = Object.assign({}, h, { how: null, candidates: [] });
      if (h.isin && isinMap[h.isin]) { out.symbol = isinMap[h.isin]; out.how = 'isin'; return out; }
      if (h.symbol && idx.bySymbol[h.symbol]) { out.how = 'symbol'; return out; }
      var n = byName(h.name || h.label, idx);
      if (n.symbol) { out.symbol = n.symbol; out.how = 'name'; return out; }
      if (h.symbol && !h.name && /^[A-Z0-9&\-]{1,20}$/.test(h.symbol) && !idx.size) {
        out.how = 'as written';                 // no list to check against: take the ticker as given
        return out;
      }
      out.candidates = n.candidates;
      if (h.symbol && !n.candidates.length && /^[A-Z0-9&\-]{1,20}$/.test(h.symbol)) out.candidates = [h.symbol];
      out.symbol = '';
      return out;
    });
  }

  /* Is this statement this client's? Loosely: most of the words of one name
     appear in the other. A warning, never a refusal — "R. B. Shukla" and
     "Rajankumar Baburam Shukla" are the same person. */
  function sameName(a, b) {
    var wa = normName(a).split(' ').filter(function (w) { return w.length > 1; });
    var wb = normName(b).split(' ').filter(function (w) { return w.length > 1; });
    if (!wa.length || !wb.length) return true;
    var hit = wa.filter(function (w) { return wb.indexOf(w) !== -1; }).length;
    return hit >= 1 && hit / Math.min(wa.length, wb.length) >= 0.5;
  }

  var api = { parseCSV: parseCSV, readXlsx: readXlsx, readFile: readFile, findHeader: findHeader, extract: extract,
              normName: normName, cleanSymbol: cleanSymbol, indexUniverse: indexUniverse, resolve: resolve,
              sameName: sameName, date: date, num: num };
  root.AltahaStatement = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);

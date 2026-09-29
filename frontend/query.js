/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — query.js

   The query screener: the reader types their own question of every stored
   company — "ROE > 15 AND Debt to equity < 0.5" — and gets back the
   companies whose filed figures meet it. Research → Query screener
   (#research/query).

   It is meant to be the friendly version of a screener's query box, so the
   reader never has to know the syntax to use it:

     · ready-made examples to start from, each just a query they can edit;
     · a three-box builder (field, comparison, value) that writes the line;
     · suggestions as they type, from every field name and alias;
     · every field listed with what it means, one click to insert;
     · an error that says what is wrong and offers the field they meant.

   The parsing and the figures live in backend/fundamentals_query.py; this
   file never evaluates anything. The query is kept in the address
   (#research/query/<query>) so a result can be bookmarked or shared.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';
  var PAGE = 50;
  var KEY = 'altaha.query.last';

  var meta = null, metaPending = null, built = false;
  var state = { q: '', sort: '', order: 'desc', results: [], data: null, busy: false };
  var ac = { items: [], active: 0, from: 0, to: 0, open: false };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function getJSON(path) {
    return fetch(API + path, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) {
          var err = new Error((body && body.detail) || ('HTTP ' + r.status));
          err.status = r.status;
          err.body = body;
          throw err;
        }
        return body;
      });
    });
  }
  function norm(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9%]/g, ''); }

  /* ── Formatting a figure by its unit ─────────────────────────────────── */

  function fmt(v, unit) {
    if (v == null || v === '') return '<span class="qs-na" title="Not available">—</span>';
    if (unit === 'text') return esc(v);
    var n = Number(v);
    if (!isFinite(n)) return '—';
    var abs = Math.abs(n);
    var dp = unit === 'cr' ? (abs >= 100 ? 0 : 1)
      : unit === 'x' ? (abs >= 100 ? 0 : 2)
      : unit === 'inr' ? (abs >= 1000 ? 0 : 2)
      : (abs >= 100 ? 0 : 1);
    var s = Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: dp,
                                                  minimumFractionDigits: 0 });
    var sign = n < 0 ? '-' : '';
    if (unit === 'pct') return sign + s + '%';
    if (unit === 'x') return sign + s + '×';
    if (unit === 'inr') return sign + '₹' + s;
    if (unit === 'cr') return sign + '₹' + s + ' cr';
    return sign + s;
  }
  var UNIT_WORD = { cr: '₹ crore', inr: '₹', pct: '%', x: 'times', num: 'number', text: 'text' };

  /* ── Address ─────────────────────────────────────────────────────────── */

  function hashParts() { return (location.hash || '').replace(/^#/, '').split('/'); }
  function onRoute() { var p = hashParts(); return p[1] === 'query' || p[0] === 'query'; }
  function queryFromHash() {
    var p = hashParts();
    var i = p[1] === 'query' ? 2 : (p[0] === 'query' ? 1 : -1);
    if (i < 0 || !p[i]) return '';
    try { return decodeURIComponent(p.slice(i).join('/')); } catch (e) { return ''; }
  }
  function writeHash(q) {
    var h = '#research/query' + (q ? '/' + encodeURIComponent(q) : '');
    if (location.hash !== h) {
      try { history.replaceState(null, '', h); } catch (e) {}
    }
  }
  function remember(q) { try { localStorage.setItem(KEY, q); } catch (e) {} }
  function recall() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }

  /* ── Saved screens ──────────────────────────────────────────────────────
     Named queries the reader keeps. Signed in they live on the account
     (/me/screens) and follow the reader to every device; signed out they are
     kept in this browser, and move to the account the first time the reader
     signs in here. One list either way — the reader never has to know which
     store it came from. */

  var SAVED_KEY = 'altaha.query.saved';
  var saved = [];

  function signedIn() { return !!(window.AltahaAuth && window.AltahaAuth.authed && window.AltahaAuth.authed()); }
  function localScreens() {
    try { var v = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); return Array.isArray(v) ? v : []; }
    catch (e) { return []; }
  }
  function writeLocal(list) { try { localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0, 25))); } catch (e) {} }
  function api(path, opts) {
    return window.AltahaAuth.fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Could not reach your account.');
        return d;
      });
    });
  }

  function loadSaved() {
    if (!signedIn()) { saved = localScreens(); paintSaved(); return Promise.resolve(saved); }
    // Screens kept in this browser before signing in go to the account once.
    var pending = localScreens();
    var upload = pending.reduce(function (p, sc) {
      return p.then(function () {
        return api('/me/screens', { method: 'PUT', body: JSON.stringify({ name: sc.name, query: sc.query }) })
          .catch(function () {});
      });
    }, Promise.resolve());
    return upload.then(function () {
      if (pending.length) writeLocal([]);
      return api('/me/screens');
    }).then(function (d) { saved = d.screens || []; paintSaved(); return saved; })
      .catch(function () { saved = localScreens(); paintSaved(); return saved; });
  }

  function paintSaved() {
    var box = $('qs-saved');
    if (!box) return;
    if (!saved.length) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<span class="qs-exlab">Your screens</span>' + saved.map(function (sc, i) {
      return '<span class="qs-schip"><button type="button" class="qs-chip" data-saved="' + i + '" title="' +
        esc(String(sc.query).replace(/\n/g, ' AND ')) + '">' + esc(sc.name) + '</button>' +
        '<button type="button" class="qs-sdel" data-delsaved="' + i + '" aria-label="Delete saved screen ' +
        esc(sc.name) + '">×</button></span>';
    }).join('') + (signedIn() ? '' : '<a class="qs-ssign" href="signin.html">Sign in to keep them on every device</a>');
  }

  function saveScreen(name, query) {
    name = String(name || '').replace(/\s+/g, ' ').trim();
    if (!name) return Promise.reject(new Error('Give the screen a name.'));
    if (!query) return Promise.reject(new Error('There is no query to save.'));
    if (signedIn()) {
      return api('/me/screens', { method: 'PUT', body: JSON.stringify({ name: name, query: query }) })
        .then(function (d) { saved = d.screens || []; paintSaved(); });
    }
    var list = localScreens().filter(function (sc) { return sc.name !== name; });
    if (list.length >= 25) return Promise.reject(new Error('You have 25 saved screens — delete one to save another.'));
    list.unshift({ name: name, query: query, updated_at: new Date().toISOString() });
    writeLocal(list);
    saved = list; paintSaved();
    return Promise.resolve();
  }

  function deleteSaved(i) {
    var sc = saved[i];
    if (!sc) return;
    if (signedIn() && sc.id != null) {
      api('/me/screens/' + encodeURIComponent(sc.id), { method: 'DELETE' })
        .then(function (d) { saved = d.screens || []; paintSaved(); })
        .catch(function () {});
      return;
    }
    var list = localScreens().filter(function (x) { return x.name !== sc.name; });
    writeLocal(list); saved = list; paintSaved();
  }

  window.addEventListener('altaha-auth', function () { if (built) loadSaved(); });

  /* ── The page ────────────────────────────────────────────────────────── */

  function skeleton(host) {
    host.innerHTML =
      '<header class="qs-head">' +
        '<p class="ln-kicker">Research · Query screener</p>' +
        '<h2>Ask every company your own question</h2>' +
        '<p>Write conditions on the figures each company has filed — returns, growth, ' +
        'margins, debt, cash flow, valuation and ownership — and see every company that ' +
        'meets them. Start from an example, build a line with the boxes, or just type.</p>' +
      '</header>' +
      '<div class="qs-saved" id="qs-saved" aria-label="Your saved screens" hidden></div>' +
      '<div class="qs-examples" id="qs-examples" aria-label="Example queries"></div>' +
      '<div class="qs-card">' +
        '<div class="qs-builder" role="group" aria-label="Add a condition">' +
          '<label class="qs-lab"><span>Field</span><select id="qs-bfield"></select></label>' +
          '<label class="qs-lab qs-lab-op"><span>Is</span><select id="qs-bop">' +
            '<option value=">">greater than</option><option value="<">less than</option>' +
            '<option value=">=">at least</option><option value="<=">at most</option>' +
            '<option value="=">equal to</option></select></label>' +
          '<label class="qs-lab qs-lab-val"><span>Value <i id="qs-bunit"></i></span>' +
            '<input id="qs-bval" type="text" inputmode="decimal" autocomplete="off" placeholder="15"></label>' +
          '<button type="button" class="qs-btn qs-btn-ghost" id="qs-badd">+ Add condition</button>' +
        '</div>' +
        '<div class="qs-editor">' +
          '<label for="qs-q" class="qs-edlab">Your query <span>one condition per line — ' +
            'lines are joined with AND</span></label>' +
          '<div class="qs-edwrap">' +
            '<textarea id="qs-q" rows="5" spellcheck="false" autocomplete="off" ' +
              'aria-autocomplete="list" aria-controls="qs-ac" ' +
              'placeholder="Market cap > 500&#10;ROE > 15&#10;Debt to equity < 0.5"></textarea>' +
            '<ul id="qs-ac" class="qs-ac" role="listbox" hidden></ul>' +
          '</div>' +
          '<p class="qs-hint">Use <code>AND</code>, <code>OR</code>, <code>NOT</code> and brackets; ' +
            'compare fields with each other or do sums (<code>Market cap / Sales &lt; 3</code>); ' +
            'match text in quotes (<code>Industry contains "bank"</code>). ' +
            '<kbd>Ctrl</kbd>+<kbd>Enter</kbd> runs it.</p>' +
          '<div id="qs-err" class="qs-err" role="alert" hidden></div>' +
          '<div class="qs-actions">' +
            '<button type="button" class="qs-btn qs-btn-go" id="qs-run">Run query</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-clear">Clear</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-copy" hidden>Copy link</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-save">Save screen</button>' +
          '</div>' +
          '<form class="qs-saveform" id="qs-saveform" hidden>' +
            '<label for="qs-savename">Name this screen</label>' +
            '<input id="qs-savename" type="text" maxlength="60" autocomplete="off" placeholder="e.g. Cheap compounders">' +
            '<button type="submit" class="qs-btn qs-btn-go" id="qs-savego">Save</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-savecancel">Cancel</button>' +
            '<p class="qs-savemsg" id="qs-savemsg" role="status"></p>' +
          '</form>' +
        '</div>' +
      '</div>' +
      '<div id="qs-out" class="qs-out" aria-live="polite"></div>' +
      '<details class="qs-ref" id="qs-ref"><summary>Every field you can use ' +
        '<span id="qs-refn"></span></summary>' +
        '<input id="qs-find" class="qs-find" type="search" placeholder="Find a field — e.g. debt, growth, promoter">' +
        '<div id="qs-fields"></div></details>' +
      '<p class="ln-notice qs-notice" role="note" id="qs-notice"></p>';
  }

  function fillHelpers() {
    var fields = meta.fields || [];
    $('qs-refn').textContent = '(' + fields.length + ')';
    $('qs-notice').textContent = meta.notice || '';

    $('qs-examples').innerHTML = '<span class="qs-exlab">Try</span>' +
      (meta.examples || []).map(function (e, i) {
        return '<button type="button" class="qs-chip" data-ex="' + i + '" title="' +
          esc(e.query.replace(/\n/g, ' AND ')) + '">' + esc(e.name) + '</button>';
      }).join('');

    var groups = {}, order = [];
    fields.forEach(function (f) {
      if (!groups[f.group]) { groups[f.group] = []; order.push(f.group); }
      groups[f.group].push(f);
    });
    $('qs-bfield').innerHTML = order.map(function (g) {
      return '<optgroup label="' + esc(g) + '">' + groups[g].map(function (f) {
        return '<option value="' + esc(f.id) + '"' + (f.id === 'roce' ? ' selected' : '') +
          '>' + esc(f.label) + '</option>';
      }).join('') + '</optgroup>';
    }).join('');
    syncBuilder();

    $('qs-fields').innerHTML = order.map(function (g) {
      return '<section class="qs-fgroup"><h4>' + esc(g) + '</h4><ul>' +
        groups[g].map(function (f) {
          return '<li data-find="' + esc(norm(f.label + ' ' + f.description + ' ' +
                                               (f.aliases || []).join(' '))) + '">' +
            '<button type="button" class="qs-fbtn" data-insert="' + esc(f.label) + '">' +
            esc(f.label) + '</button> <small>' + esc(UNIT_WORD[f.unit] || '') + '</small>' +
            '<p>' + esc(f.description) +
            ((f.aliases && f.aliases.length)
              ? ' <em>Also: ' + esc(f.aliases.slice(0, 3).join(', ')) + '</em>' : '') +
            '</p></li>';
        }).join('') + '</ul></section>';
    }).join('');
  }

  function fieldById(id) {
    var fs = (meta && meta.fields) || [];
    for (var i = 0; i < fs.length; i++) if (fs[i].id === id) return fs[i];
    return null;
  }

  function syncBuilder() {
    var f = fieldById($('qs-bfield').value);
    var text = f && f.unit === 'text';
    var op = $('qs-bop');
    Array.prototype.forEach.call(op.options, function (o) {
      o.disabled = text && o.value !== '=';
    });
    if (text) op.value = '=';
    $('qs-bunit').textContent = f ? (text ? '' : '(' + (UNIT_WORD[f.unit] || '') + ')') : '';
    $('qs-bval').setAttribute('inputmode', text ? 'text' : 'decimal');
    $('qs-bval').placeholder = text ? 'e.g. Pharmaceuticals' : (f && f.unit === 'x' ? '0.5' : '15');
  }

  /* ── Editing the query ───────────────────────────────────────────────── */

  function ta() { return $('qs-q'); }

  function insertAtCursor(text) {
    var t = ta(), s = t.selectionStart, e = t.selectionEnd, v = t.value;
    var before = v.slice(0, s), after = v.slice(e);
    var pad = before && !/[\s(]$/.test(before) ? ' ' : '';
    t.value = before + pad + text + ' ' + after.replace(/^ /, '');
    var at = (before + pad + text + ' ').length;
    t.focus();
    t.setSelectionRange(at, at);
  }

  function addLine(line) {
    var t = ta(), v = t.value.replace(/\s+$/, '');
    t.value = (v ? v + '\n' : '') + line;
    t.focus();
    t.setSelectionRange(t.value.length, t.value.length);
  }

  function builderAdd() {
    var f = fieldById($('qs-bfield').value);
    var val = $('qs-bval').value.trim();
    if (!f) return;
    if (!val) { $('qs-bval').focus(); return; }
    if (f.unit === 'text') val = '"' + val.replace(/"/g, '') + '"';
    else val = val.replace(/[^0-9.,\-]/g, '') || '0';
    addLine(f.label + ' ' + $('qs-bop').value + ' ' + val);
    $('qs-bval').value = '';
  }

  /* ── Suggestions while typing ────────────────────────────────────────── */

  var STOP = /^(and|or|not|contains)$/i;

  function currentWord() {
    // The run of name words ending at the cursor: after the last operator,
    // bracket, newline or keyword.
    var t = ta(), pos = t.selectionStart, v = t.value.slice(0, pos);
    var m = v.match(/([A-Za-z][A-Za-z0-9 %'.&_]*)$/);
    if (!m) return null;
    var words = m[1].split(' '), start = pos - m[1].length;
    // Drop leading keywords so "ROE > 15 AND sal" suggests from "sal".
    while (words.length && STOP.test(words[0])) {
      start += words[0].length + 1;
      words.shift();
    }
    var w = words.join(' ').replace(/^\s+/, '');
    start = pos - w.length;
    if (!w || STOP.test(w.trim())) return null;
    return { text: w, from: start, to: pos };
  }

  function rank(text) {
    var q = norm(text), out = [];
    if (!q) return out;
    (meta.fields || []).forEach(function (f) {
      var names = [f.label].concat(f.aliases || []), best = 0;
      names.forEach(function (n) {
        var k = norm(n);
        var s = k === q ? 100 : k.indexOf(q) === 0 ? 80 - k.length / 10
          : k.indexOf(q) > 0 ? 40 - k.length / 10 : 0;
        if (s > best) best = s;
      });
      if (best > 0 && norm(f.label) !== q) out.push({ f: f, s: best });
    });
    out.sort(function (a, b) { return b.s - a.s; });
    return out.slice(0, 7).map(function (x) { return x.f; });
  }

  function closeAc() {
    ac.open = false;
    $('qs-ac').hidden = true;
    ta().removeAttribute('aria-activedescendant');
  }

  function openAc() {
    var w = currentWord();
    if (!meta || !w || w.text.length < 2) { closeAc(); return; }
    ac.items = rank(w.text);
    if (!ac.items.length) { closeAc(); return; }
    ac.from = w.from; ac.to = w.to; ac.active = 0; ac.open = true;
    paintAc();
  }

  function paintAc() {
    var ul = $('qs-ac');
    ul.innerHTML = ac.items.map(function (f, i) {
      return '<li role="option" id="qs-ac-' + i + '" data-i="' + i + '"' +
        (i === ac.active ? ' aria-selected="true" class="on"' : '') + '><b>' + esc(f.label) +
        '</b><span>' + esc(f.description) + '</span></li>';
    }).join('');
    ul.hidden = false;
    ta().setAttribute('aria-activedescendant', 'qs-ac-' + ac.active);
  }

  function pickAc(i) {
    var f = ac.items[i];
    if (!f) return;
    var t = ta(), v = t.value;
    var tail = v.slice(ac.to).replace(/^ +/, '');
    var ins = f.label + ' ';
    t.value = v.slice(0, ac.from) + ins + tail;
    var at = ac.from + ins.length;
    t.setSelectionRange(at, at);
    t.focus();
    closeAc();
  }

  /* ── Running ─────────────────────────────────────────────────────────── */

  function showError(e, q) {
    var box = $('qs-err');
    var info = (e && e.body && e.body.error) || null;
    if (!info) {
      box.innerHTML = '<b>Could not run the query.</b> ' +
        esc((e && e.message) || 'The server did not answer.') + ' Try again in a moment.';
      box.hidden = false;
      return;
    }
    var html = '<b>' + esc(info.message) + '</b>';
    if (info.position != null && q) {
      var p = Math.max(0, Math.min(q.length, info.position));
      var ls = q.lastIndexOf('\n', p - 1) + 1, le = q.indexOf('\n', p);
      if (le < 0) le = q.length;
      var line = q.slice(ls, le), col = p - ls;
      html += '<pre class="qs-where">' + esc(line) + '\n' +
        esc(new Array(col + 1).join(' ')) + '^</pre>';
    }
    if (info.suggestions && info.suggestions.length) {
      html += '<div class="qs-sug">Replace with: ' + info.suggestions.map(function (s) {
        return '<button type="button" class="qs-chip" data-fix="' + esc(s) + '" data-pos="' +
          (info.position == null ? '' : info.position) + '">' + esc(s) + '</button>';
      }).join('') + '</div>';
    }
    box.innerHTML = html;
    box.hidden = false;
  }

  function applyFix(label, pos) {
    var t = ta(), v = t.value, p = parseInt(pos, 10);
    if (isNaN(p)) return;
    // The bad name runs from its position to the next operator or line end.
    var rest = v.slice(p), m = rest.match(/^[A-Za-z0-9 %'.&_]*?(?=\s*(>=|<=|!=|<>|==|[<>=+\-*\/()\n]|\s(and|or|contains)\b|$))/i);
    var len = m ? m[0].length : 0;
    t.value = v.slice(0, p) + label + v.slice(p + len);
    run(false);
  }

  function run(append) {
    var q = ta().value.trim();
    if (!q) { ta().focus(); return; }
    if (state.busy) return;
    closeAc();
    if (!append) { state.q = q; state.results = []; }
    state.busy = true;
    $('qs-err').hidden = true;
    var btn = $('qs-run');
    btn.disabled = true; btn.classList.add('is-busy');
    btn.textContent = append ? 'Run query' : 'Running…';
    if (!append) {
      var out = $('qs-out');
      if (!out.firstChild) out.innerHTML = '<p class="ln-small">Screening every company…</p>';
      else out.classList.add('is-stale');
    }
    var params = 'q=' + encodeURIComponent(state.q) + '&limit=' + PAGE +
      '&offset=' + (append ? state.results.length : 0) +
      (state.sort ? '&sort=' + encodeURIComponent(state.sort) + '&order=' + state.order : '');
    if (window.AltahaTrack && !append) window.AltahaTrack('query_run', { length: q.length });
    getJSON('/fundamentals/query?' + params).then(function (d) {
      if (d && d.available === false) {
        $('qs-out').innerHTML = '<p class="ln-small">' + esc(d.message || 'Not available yet.') + '</p>';
        return;
      }
      state.data = d;
      state.sort = d.sort; state.order = d.order;
      state.results = append ? state.results.concat(d.results) : d.results;
      writeHash(state.q);
      remember(state.q);
      paintResults();
    }).catch(function (e) {
      if (!append) $('qs-out').innerHTML = '';
      showError(e, state.q);
    }).then(function () {
      state.busy = false;
      btn.disabled = false; btn.classList.remove('is-busy'); btn.textContent = 'Run query';
      $('qs-out').classList.remove('is-stale');
    });
  }

  function paintResults() {
    var d = state.data, out = $('qs-out');
    var n = function (x) { return Number(x || 0).toLocaleString('en-IN'); };
    var head = '<div class="qs-sum"><p><b>' + n(d.count) + '</b> ' +
      (d.count === 1 ? 'company matches' : 'companies match') +
      ' <span>of ' + n(d.screened) + ' screened</span></p>' +
      (d.unknown ? '<p class="qs-unk" title="A company whose figure is missing is left out rather ' +
        'than counted as failing">' + n(d.unknown) + ' left out because a figure the query uses ' +
        'is not available for them</p>' : '') +
      (d.count ? '<button type="button" class="qs-btn qs-btn-ghost qs-csv" id="qs-csv">Download CSV</button>' : '') +
      '</div>';
    $('qs-copy').hidden = false;
    if (!d.count) {
      out.innerHTML = head + '<p class="ln-small">No company meets every condition. ' +
        'Try loosening a number, or join two lines with OR.</p>';
      return;
    }
    var cols = d.columns;
    var th = '<th scope="col" class="qs-co">Company</th>' + cols.map(function (c) {
      var on = c.id === state.sort;
      var arrow = on ? (state.order === 'asc' ? ' ▲' : ' ▼') : '';
      return '<th scope="col"' + (on ? ' aria-sort="' + (state.order === 'asc' ? 'ascending' : 'descending') + '"' : '') +
        '><button type="button" class="qs-sort" data-sort="' + esc(c.id) + '" title="' +
        esc(c.description) + '">' + esc(c.label) + arrow + '</button></th>';
    }).join('');
    var rows = state.results.map(function (r, i) {
      return '<tr><td class="qs-n">' + (i + 1) + '</td><th scope="row"><a href="stock.html?ticker=' +
        encodeURIComponent(r.symbol) + '"><b>' + esc(r.symbol) + '</b><span>' +
        esc(r.name || '') + '</span>' + (r.industry ? '<em>' + esc(r.industry) + '</em>' : '') +
        '</a></th>' + cols.map(function (c) {
          return '<td class="qs-num' + (c.unit === 'text' ? ' qs-txt' : '') + '">' + fmt(r[c.id], c.unit) + '</td>';
        }).join('') + '</tr>';
    }).join('');
    var more = state.results.length < d.count
      ? '<button type="button" class="qs-btn qs-btn-ghost qs-more" id="qs-more">Show ' +
        Math.min(PAGE, d.count - state.results.length) + ' more (' + n(state.results.length) +
        ' of ' + n(d.count) + ' shown)</button>' : '';
    out.innerHTML = head + '<div class="ln-tablewrap"><table class="ln-table qs-table">' +
      '<thead><tr><th scope="col" class="qs-n">#</th>' + th + '</tr></thead><tbody>' + rows +
      '</tbody></table></div>' + more +
      '<p class="ln-small">Figures are the latest filed, in ₹ crore where money; — means not ' +
      'available. Click a column to sort. ' + (d.computed_utc ? 'Computed ' +
        esc(new Date(d.computed_utc).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })) + '.' : '') + '</p>';
  }

  function sortBy(id) {
    if (state.sort === id) state.order = state.order === 'asc' ? 'desc' : 'asc';
    else { state.sort = id; state.order = 'desc'; }
    ta().value = state.q;
    run(false);
  }

  function downloadCsv() {
    var d = state.data;
    if (!d) return;
    var params = 'q=' + encodeURIComponent(state.q) + '&limit=500&offset=0' +
      '&sort=' + encodeURIComponent(state.sort) + '&order=' + state.order;
    getJSON('/fundamentals/query?' + params).then(function (all) {
      var cols = all.columns;
      var cell = function (v) {
        var s = v == null ? '' : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      var lines = [['Symbol', 'Name', 'Industry'].concat(cols.map(function (c) {
        return c.label + (c.unit === 'cr' ? ' (₹ cr)' : c.unit === 'pct' ? ' (%)' : '');
      })).map(cell).join(',')];
      all.results.forEach(function (r) {
        lines.push([r.symbol, r.name, r.industry].concat(cols.map(function (c) {
          return r[c.id];
        })).map(cell).join(','));
      });
      var blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'altaha-query.csv';
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    }).catch(function (e) { showError(e, state.q); });
  }

  /* ── Wiring ──────────────────────────────────────────────────────────── */

  function wire(host) {
    var t = ta();
    t.addEventListener('input', openAc);
    t.addEventListener('click', closeAc);
    t.addEventListener('blur', function () { setTimeout(closeAc, 150); });
    t.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(false); return; }
      if (!ac.open) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); ac.active = (ac.active + 1) % ac.items.length; paintAc(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); ac.active = (ac.active - 1 + ac.items.length) % ac.items.length; paintAc(); }
      else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickAc(ac.active); }
      else if (e.key === 'Escape') { e.preventDefault(); closeAc(); }
    });
    $('qs-ac').addEventListener('mousedown', function (e) {
      var li = e.target.closest('li[data-i]');
      if (li) { e.preventDefault(); pickAc(+li.getAttribute('data-i')); }
    });
    $('qs-bfield').addEventListener('change', syncBuilder);
    $('qs-badd').addEventListener('click', builderAdd);
    $('qs-bval').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); builderAdd(); }
    });
    $('qs-run').addEventListener('click', function () { state.sort = ''; run(false); });
    $('qs-clear').addEventListener('click', function () {
      t.value = ''; $('qs-out').innerHTML = ''; $('qs-err').hidden = true;
      $('qs-copy').hidden = true; state.data = null; writeHash(''); t.focus();
    });
    $('qs-copy').addEventListener('click', function () {
      var b = $('qs-copy');
      var done = function () { b.textContent = 'Link copied'; setTimeout(function () { b.textContent = 'Copy link'; }, 1600); };
      try { navigator.clipboard.writeText(location.href).then(done, done); } catch (e) { done(); }
    });
    $('qs-find').addEventListener('input', function () {
      var q = norm(this.value);
      Array.prototype.forEach.call($('qs-fields').querySelectorAll('li'), function (li) {
        li.hidden = !!q && li.getAttribute('data-find').indexOf(q) < 0;
      });
      Array.prototype.forEach.call($('qs-fields').querySelectorAll('.qs-fgroup'), function (g) {
        g.hidden = !g.querySelector('li:not([hidden])');
      });
    });
    host.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      if (b.hasAttribute('data-ex')) {
        var ex = meta.examples[+b.getAttribute('data-ex')];
        t.value = ex.query; state.sort = ''; run(false);
      } else if (b.hasAttribute('data-insert')) {
        insertAtCursor(b.getAttribute('data-insert'));
      } else if (b.hasAttribute('data-fix')) {
        applyFix(b.getAttribute('data-fix'), b.getAttribute('data-pos'));
      } else if (b.hasAttribute('data-sort')) {
        sortBy(b.getAttribute('data-sort'));
      } else if (b.id === 'qs-more') {
        run(true);
      } else if (b.id === 'qs-csv') {
        downloadCsv();
      } else if (b.hasAttribute('data-saved')) {
        var sc = saved[+b.getAttribute('data-saved')];
        if (sc) { t.value = sc.query; state.sort = ''; run(false); }
      } else if (b.hasAttribute('data-delsaved')) {
        deleteSaved(+b.getAttribute('data-delsaved'));
      }
    });
    $('qs-save').addEventListener('click', function () {
      var f = $('qs-saveform');
      $('qs-savemsg').textContent = '';
      if (!t.value.trim()) {
        f.hidden = false;
        $('qs-savemsg').textContent = 'Write or pick a query first, then save it.';
        return;
      }
      f.hidden = false;
      $('qs-savename').focus();
    });
    $('qs-savecancel').addEventListener('click', function () { $('qs-saveform').hidden = true; });
    $('qs-saveform').addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = $('qs-savemsg');
      msg.textContent = '';
      saveScreen($('qs-savename').value, t.value.trim()).then(function () {
        msg.textContent = 'Saved.';
        $('qs-savename').value = '';
        setTimeout(function () { $('qs-saveform').hidden = true; msg.textContent = ''; }, 900);
      }).catch(function (err) { msg.textContent = err.message || 'Could not save that screen.'; });
    });
  }

  function show() {
    var host = $('query-body');
    if (!host || !onRoute()) return;
    if (!built) {
      built = true;
      skeleton(host);
      wire(host);
      loadSaved();
    }
    var fromHash = queryFromHash();
    if (meta) { start(fromHash); return; }
    if (metaPending) return;
    metaPending = getJSON('/fundamentals/query/fields').then(function (d) {
      meta = d;
      if (!d.available) {
        $('qs-out').innerHTML = '<p class="ln-small">' + esc(d.message || 'The query screener is not available yet.') + '</p>';
        return;
      }
      fillHelpers();
      start(queryFromHash());
    }).catch(function () {
      metaPending = null;
      $('qs-out').innerHTML = '<p class="ln-small">The field list could not be loaded. ' +
        'Open this tab again to retry.</p>';
    });
  }

  function start(q) {
    var t = ta();
    if (q && q !== state.q) { t.value = q; state.sort = ''; run(false); return; }
    if (!t.value && !state.q) t.value = recall();
  }

  window.addEventListener('altaha:navigate', function (ev) {
    if (ev && ev.detail && ev.detail.tab === 'query') setTimeout(show, 0);
  });
  window.addEventListener('hashchange', function () { if (onRoute()) setTimeout(show, 0); });

  function boot() {
    var b = $('tab-query');
    if (b) b.addEventListener('click', function () { setTimeout(show, 0); });
    var v = $('view-query');
    if (v && v.style.display !== 'none') show();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.AltahaQuery = { show: show, run: function (q) { show(); ta().value = q; run(false); } };
})();

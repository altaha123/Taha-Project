/* Ownership research: disclosed investors, quarter changes and like-for-like peers. */
(function () {
  'use strict';
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };
  var finite = function (n) { return typeof n === 'number' && isFinite(n); };
  var pct = function (n) { return finite(n) ? n.toFixed(2) + '%' : 'Unavailable'; };
  var delta = function (n) { return finite(n) ? (n > 0 ? '+' : '') + n.toFixed(2) + ' pp' : 'Comparison unavailable'; };
  var kinds = ['Mutual fund', 'Insurance', 'Pension fund', 'Institution', 'Foreign institution', 'Foreign portfolio investor'];
  function source(url, text) {
    try { var u = new URL(url); if (u.protocol !== 'https:' || !/(^|\.)nseindia\.com$/.test(u.hostname)) return ''; }
    catch (_) { return ''; }
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(text || 'Exchange filing ↗') + '</a>';
  }
  function status(n) {
    if (n.status === 'no_longer_disclosed') return 'No longer disclosed';
    if (n.new_in_table) return 'Newly disclosed';
    if (!finite(n.change_qoq)) return 'Comparison unavailable';
    return Math.abs(n.change_qoq) < .005 ? 'Unchanged' : delta(n.change_qoq);
  }
  function trend(n) {
    var history = n.history || [], vals = history.filter(function (p) { return finite(p.pct); }).map(function (p) { return p.pct; });
    if (vals.length < 2) return '<div class="oi-chart-empty">More filings needed for a trend</div>';
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = hi - lo || 1;
    var open = false, path = '';
    history.forEach(function (p, i) {
      if (!finite(p.pct)) { open = false; return; }
      if (i > 0 && Date.parse(p.period) - Date.parse(history[i - 1].period) > 135 * 86400000) open = false;
      var x = 5 + i * 230 / Math.max(1, history.length - 1), y = 44 - (p.pct - lo) / span * 32;
      path += (open ? ' L' : ' M') + x.toFixed(1) + ',' + y.toFixed(1); open = true;
    });
    return '<svg class="oi-spark" viewBox="0 0 240 52" role="img" aria-label="Holding history; gaps mean not disclosed. Range ' + pct(lo) + ' to ' + pct(hi) + '"><path d="' + path + '"/></svg>' +
      '<div class="oi-meta">' + esc(history[0].period) + ' → ' + esc(history[history.length - 1].period) + ' · range ' + pct(lo) + '–' + pct(hi) + '</div>';
  }
  function investor(n, filing) {
    var initials = n.name.split(/\s+/).slice(0, 2).map(function (x) { return x[0]; }).join('');
    return '<article class="oi-investor"><div class="oi-investor-head"><span class="oi-avatar" aria-hidden="true">' + esc(initials) + '</span><div><span class="oi-eyebrow">' + esc(n.kind || 'Disclosed holder') + '</span><h4>' + esc(n.name) + '</h4></div></div>' +
      '<div class="oi-position"><strong>' + pct(n.pct) + '</strong><span class="oi-badge">' + esc(status(n)) + '</span></div>' +
      '<div class="oi-meta">Previous quarter: ' + pct(n.previous_pct) + '</div>' + trend(n) +
      '<details><summary>Holding history & source</summary><p class="oi-meta">First seen in available history: ' + esc(n.first_seen || 'Unavailable') + '. This is not the investment date.</p>' +
      '<ul class="oi-history">' + (n.history || []).map(function (p) { return '<li><span>' + esc(p.period) + '</span><b>' + (finite(p.pct) ? pct(p.pct) : 'Not disclosed') + '</b>' + source(p.source, 'Filing ↗') + '</li>'; }).join('') + '</ul>' + source(n.source || filing) + '</details></article>';
  }
  function insights(d) {
    var history = (d.history || []).filter(function (p) { return p.quarter_end !== false; });
    var findings = [], named = (d.names || {}).public || [];
    ['dii', 'fii'].forEach(function (key) {
      var run = 0;
      for (var i = history.length - 1; i > 0; i--) {
        var a = history[i], b = history[i - 1], gap = (Date.parse(a.period) - Date.parse(b.period)) / 86400000;
        if (!finite(a[key]) || !finite(b[key]) || a[key] <= b[key] || gap < 60 || gap > 135) break;
        run++;
      }
      if (run >= 2) findings.push({label:'Sustained change', text:(key === 'dii' ? 'Domestic' : 'Foreign') + ' institutional holding increased for ' + run + ' consecutive quarter comparisons, through ' + history[history.length - 1].period + '.'});
    });
    var movers = named.filter(function (n) { return finite(n.change_qoq) && Math.abs(n.change_qoq) >= .005; }).sort(function (a, b) { return Math.abs(b.change_qoq) - Math.abs(a.change_qoq); });
    if (movers.length) findings.push({label:'Largest disclosed holder change', text:movers[0].name + ': ' + delta(movers[0].change_qoq) + ' vs the previous quarter.'});
    var fresh = named.filter(function (n) { return n.new_in_table; }).length;
    if (fresh) findings.push({label:'New to the disclosed table', text:fresh + ' displayed holder' + (fresh === 1 ? '' : 's') + ' not named in the previous quarter. Crossing a disclosure threshold can explain this.'});
    if (!findings.length) findings.push({label:'Available evidence', text:'Read the disclosed holdings below. Comparable filings are needed before identifying a trend.'});
    return '<div class="oi-insights">' + findings.slice(0, 3).map(function (f) { return '<article><span class="oi-eyebrow">' + esc(f.label) + '</span><p>' + esc(f.text) + '</p></article>'; }).join('') + '</div>';
  }
  function movers(d) {
    var list = ((d.names || {}).public || []).filter(function (n) { return finite(n.change_qoq) && Math.abs(n.change_qoq) >= .005; }).sort(function (a, b) { return Math.abs(b.change_qoq) - Math.abs(a.change_qoq); }).slice(0, 8);
    var max = Math.max.apply(null, list.map(function (n) { return Math.abs(n.change_qoq); }).concat([.01]));
    var fresh = ((d.names || {}).public || []).filter(function (n) { return n.new_in_table; });
    var gone = (d.names || {}).no_longer_disclosed || [];
    return '<section class="oi-section"><div class="oi-section-head"><div><span class="oi-eyebrow">Quarterly changes</span><h3>Who increased or reduced?</h3></div><span class="oi-meta">Percentage points · disclosed public holders</span></div>' +
      (list.length ? '<div class="oi-movers">' + list.map(function (n) { return '<div class="oi-mover"><span>' + esc(n.name) + '</span><div class="oi-diverging" aria-hidden="true"><i class="' + (n.change_qoq < 0 ? 'oi-minus' : 'oi-plus') + '" style="width:' + (Math.abs(n.change_qoq) / max * 48) + '%"></i></div><b>' + delta(n.change_qoq) + '</b></div>'; }).join('') + '</div>' : '<p class="oi-meta">No measurable changes available between comparable quarter-end disclosures.</p>') +
      '<div class="oi-disclosures">' + (fresh.length ? '<p><b>Newly disclosed:</b> ' + fresh.map(function (n) { return esc(n.name); }).join(' · ') + '</p>' : '') +
      (gone.length ? '<p><b>No longer disclosed:</b> ' + gone.map(function (n) { return esc(n.name) + ' (previously ' + pct(n.previous_pct) + ')'; }).join(' · ') + '</p>' : '') + '</div>' +
      '<p class="oi-meta">Changes in ownership percentages do not prove buying or selling. Absence from a disclosed table does not prove a complete exit.</p></section>';
  }
  function ownMetrics(d) {
    var out = {};
    (d.split || []).forEach(function (s) { out[s.key] = s; });
    var f = out.fii || {}, dom = out.dii || {};
    out.institutions = {pct: finite(f.pct) && finite(dom.pct) ? f.pct + dom.pct : null,
      change_qoq: finite(f.change_qoq) && finite(dom.change_qoq) ? f.change_qoq + dom.change_qoq : null,
      derived: f.derived || dom.derived};
    return out;
  }
  function get(url) {
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 90000);
    return fetch(url, {signal:ctrl.signal}).then(function (r) { if (!r.ok) throw new Error('unavailable'); return r.json(); }).finally(function () { clearTimeout(timer); });
  }
  function mount(d, config) {
    var root = document.getElementById('own-intelligence'); if (!root) return;
    var publicNames = (d.names || {}).public || [], peers = [], metric = 'institutions', peerSector = '', showAll = false;
    var comparisonPeriod = d.basis_period || d.period;
    var own = {symbol:d.symbol || config.ticker, period:d.period, available:true, metrics:ownMetrics(d), source:d.latest_source};
    var company = config.name || config.ticker;
    root.innerHTML = '<div class="oi-toolbar"><div><span class="oi-eyebrow">Ownership intelligence</span><h3>The investors behind ' + esc(d.symbol || config.ticker) + '</h3></div><button type="button" class="oi-btn oi-primary" id="oi-share">Share ownership snapshot ↗</button></div>' + insights(d) +
      '<section class="oi-section"><div class="oi-section-head"><div><span class="oi-eyebrow">The disclosed register</span><h3>Who has invested?</h3></div><label class="oi-meta">Show <select id="oi-filter"><option value="institutions">Institutions</option><option value="all">All disclosed public holders</option></select></label></div><div class="oi-investors" id="oi-investors"></div><button type="button" class="oi-btn" id="oi-more-investors" hidden>Show all disclosed investors</button><p class="oi-meta">Named disclosures only; not every investor is named. ' +
      (d.names && d.names.coverage ? 'Showing up to ' + d.names.coverage.limit_per_group + ' of ' + d.names.coverage.public_total + ' disclosed public holders. ' : '') + 'Institutional categories can include several fund schemes under one name.</p></section>' + movers(d) +
      '<section class="oi-section"><div class="oi-section-head"><div><span class="oi-eyebrow">Put the numbers in context</span><h3>Compare with sector peers</h3></div><button type="button" class="oi-btn" id="oi-load-peers">Load peer comparison</button></div><p class="oi-meta" id="oi-peer-context">Matching quarter only: ' + esc(comparisonPeriod) + '. Peer filings load when requested.</p><div id="oi-peer-controls" hidden><label>Compare <select id="oi-metric"><option value="institutions">Total institutional holding</option><option value="fii">Foreign institutional holding</option><option value="dii">Domestic institutional holding</option><option value="promoter">Promoter holding</option></select></label><label>Add a sector peer <select id="oi-add-peer"><option value="">Choose a peer…</option></select></label><button type="button" class="oi-btn" id="oi-add">Add peer</button></div><div id="oi-peers" aria-live="polite"></div><p id="oi-peer-finding" class="oi-comparison-finding" aria-live="polite"></p><p class="oi-meta" id="oi-peer-status" role="status"></p><p class="oi-meta">Pledged promoter shares: unavailable from this reader. Higher institutional ownership is not a quality rating.</p></section>';
    function renderInvestors() {
      var mode = root.querySelector('#oi-filter').value;
      var list = publicNames.filter(function (n) { return mode === 'all' || n.institutional === true || kinds.indexOf(n.kind) >= 0; });
      root.querySelector('#oi-investors').innerHTML = list.length ? list.slice(0, showAll ? list.length : 6).map(function (n) { return investor(n, d.latest_source); }).join('') : '<p class="oi-meta">No named institutions available in this filing. Select all disclosed public holders to see other names.</p>';
      var more = root.querySelector('#oi-more-investors'); more.hidden = list.length <= 6; more.textContent = showAll ? 'Show fewer investors' : 'Show all ' + list.length + ' disclosed investors';
    }
    root.querySelector('#oi-more-investors').addEventListener('click', function () { showAll = !showAll; renderInvestors(); });
    root.querySelector('#oi-filter').addEventListener('change', renderInvestors); renderInvestors();
    function drawPeers() {
      var rows = [own].concat(peers);
      root.querySelector('#oi-peers').innerHTML = rows.map(function (r) {
        var m = (r.metrics || {})[metric] || {}, value = r.available ? m.pct : null;
        return '<div class="oi-peer-row' + (r === own ? ' oi-self' : '') + '"><div><b>' + esc(r.symbol) + (r === own ? ' · this company' : '') + '</b><span class="oi-meta">' + esc(r.period || comparisonPeriod) + (m.derived ? ' · derived' : '') + '</span></div><div class="oi-peer-track" aria-hidden="true"><i style="width:' + (finite(value) ? Math.max(0, Math.min(100, value)) : 0) + '%"></i></div><div><b>' + pct(value) + '</b><span class="oi-meta">' + (r.loading ? 'Reading filing…' : r.available ? delta(m.change_qoq) + ' QoQ' : esc(r.message || 'Unavailable')) + '</span></div><div>' + (r.source ? source(r.source, 'Filing ↗') : '') + (r !== own ? '<button class="oi-remove" type="button" data-remove="' + esc(r.symbol) + '" aria-label="Remove ' + esc(r.symbol) + '">×</button>' : '') + '</div></div>';
      }).join('');
      var values = peers.filter(function (p) { return p.available && p.period === comparisonPeriod; }).map(function (p) { return ((p.metrics || {})[metric] || {}).pct; }).filter(finite).sort(function (a,b) { return a-b; });
      var mine = ((own.metrics || {})[metric] || {}).pct, finding = '';
      if (own.available && finite(mine) && values.length >= 2) {
        var mid = Math.floor(values.length / 2), median = values.length % 2 ? values[mid] : (values[mid-1] + values[mid]) / 2;
        finding = own.symbol + ' holding: ' + Math.abs(mine - median).toFixed(2) + ' pp ' + (mine >= median ? 'above' : 'below') +
          ' the median of ' + values.length + ' loaded peers (' + pct(median) + ') for ' + comparisonPeriod + '. Selected sample, not the full sector.';
      }
      root.querySelector('#oi-peer-finding').textContent = finding;
    }
    root.querySelector('#oi-peers').addEventListener('click', function (e) {
      var b = e.target.closest('[data-remove]'); if (!b) return;
      peers = peers.filter(function (p) { return p.symbol !== b.dataset.remove; }); drawPeers();
    });
    root.querySelector('#oi-metric').addEventListener('change', function (e) { metric = e.target.value; drawPeers(); });
    var peerBusy = false;
    async function addPeers(symbols) {
      peerBusy = true;
      root.querySelector('#oi-add').disabled = true;
      // Sequential requests bound cold-cache load on the small backend.
      for (var i = 0; i < symbols.length; i++) {
        var sym = symbols[i];
        if (peers.some(function (p) { return p.symbol === sym; }) || peers.length >= 5) continue;
        var pending = {symbol:sym, period:comparisonPeriod, loading:true}; peers.push(pending); drawPeers();
        try { var result = await get(config.api + '/shareholding/compare?ticker=' + encodeURIComponent(sym) + '&period=' + encodeURIComponent(comparisonPeriod)); Object.assign(pending, result, {loading:false}); }
        catch (_) { Object.assign(pending, {loading:false, available:false, message:'Could not load; remove and add to retry.'}); }
        drawPeers();
      }
      peerBusy = false; root.querySelector('#oi-add').disabled = false;
      root.querySelector('#oi-peer-status').textContent = 'Up to five peers. Bars use the same 0–100% scale; changes are percentage points.';
    }
    root.querySelector('#oi-add').addEventListener('click', function () {
      if (peerBusy) return;
      var sym = root.querySelector('#oi-add-peer').value;
      if (peers.length >= 5) root.querySelector('#oi-peer-status').textContent = 'Remove a peer before adding another (maximum five).';
      else if (sym) addPeers([sym]);
    });
    root.querySelector('#oi-load-peers').addEventListener('click', async function (e) {
      var button = e.currentTarget; button.disabled = true; button.textContent = 'Finding sector peers…';
      try {
        var candidates = await get(config.api + '/shareholding/peers?ticker=' + encodeURIComponent(config.ticker));
        peerSector = candidates.sector || '';
        root.querySelector('#oi-peer-context').textContent = (candidates.sector || 'Unclassified sector') + ' · ' + candidates.classification_source + ' · quarter ' + comparisonPeriod + '. ' + (candidates.selection || 'Same-sector sample.');
        if (!(candidates.candidates || []).length) { button.textContent = 'Retry peer lookup'; button.disabled = false; root.querySelector('#oi-peer-status').textContent = 'No same-sector peers are available in the current classification.'; return; }
        if (d.period !== comparisonPeriod) own = await get(config.api + '/shareholding/compare?ticker=' + encodeURIComponent(config.ticker) + '&period=' + encodeURIComponent(comparisonPeriod));
        root.querySelector('#oi-peer-controls').hidden = false;
        root.querySelector('#oi-add-peer').innerHTML = '<option value="">Choose a peer…</option>' + candidates.candidates.map(function (s) { return '<option>' + esc(s) + '</option>'; }).join('');
        button.hidden = true; await addPeers(candidates.candidates.slice(0, 3));
      } catch (_) { button.disabled = false; button.textContent = 'Retry peer comparison'; root.querySelector('#oi-peer-status').textContent = 'Peer comparison could not load. Your ownership data is still available.'; }
    });
    root.querySelector('#oi-share').addEventListener('click', function () {
      if (window.OwnershipSnapshot) window.OwnershipSnapshot.open({symbol:d.symbol || config.ticker, company:company, period:d.period, source:d.latest_source,
        retrieved:d.retrieved_at, split:(d.split || []).map(function (s) { return Object.assign({}, s, {change_qoq:d.period === comparisonPeriod ? s.change_qoq : null}); }), names:publicNames.filter(function (n) { return n.institutional === true || kinds.indexOf(n.kind) >= 0; }).slice(0,3),
        finding:(root.querySelector('.oi-insights p') || {}).textContent || '',
        sector:peerSector, peerFinding:root.querySelector('#oi-peer-finding').textContent, peerMetric:metric, peerPeriod:comparisonPeriod, peers:[own].concat(peers.filter(function (p) { return p.available; })).slice(0,6)});
    });
  }
  window.OwnershipInsights = {mount:mount};
})();

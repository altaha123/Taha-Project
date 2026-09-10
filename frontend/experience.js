/* Progressive UI enhancements; no scoring changes or additional API polling. */
(function () {
  'use strict';
  const KEY = 'altaha-watchlist-v1';
  const normalise = value => String(value || '').trim().toUpperCase();
  const valid = value => /^[A-Z0-9][A-Z0-9.&^=_-]{0,29}$/.test(value);
  function clean(rows) {
    if (!Array.isArray(rows)) return [];
    return [...new Set(rows.filter(x => typeof x === 'string').map(normalise).filter(valid))].slice(0, 100);
  }
  function matches(row, query, min) {
    return (row.symbol + ' ' + row.name).toLowerCase().includes(query.trim().toLowerCase()) &&
      (!min || (row.score !== '' && Number.isFinite(Number(row.score)) && Number(row.score) >= min));
  }
  // Pure validation functions are also exercised by the dependency-free unit tests.
  if (typeof module !== 'undefined' && module.exports) { module.exports = { clean, matches }; return; }
  function node(tag, cls, text) {
    const n = document.createElement(tag); n.className = cls || '';
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function button(text, fn, cls) {
    const b = node('button', cls || 'ux-button', text); b.type = 'button';
    b.addEventListener('click', fn); return b;
  }
  function read() { try { return clean(JSON.parse(localStorage.getItem(KEY))); } catch (_) { return []; } }
  let saved = read(), toastTimer;
  const toast = node('div', 'ux-toast'); toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', 'polite'); document.body.append(toast);
  function announce(text) {
    toast.textContent = text; toast.classList.add('on'); clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('on'), 3200);
  }
  function dialog(title) {
    const d = node('dialog', 'ux-dialog');
    const head = node('div', 'ux-dialog-head');
    const h = node('h2', '', title); h.id = 'ux-title-' + document.querySelectorAll('.ux-dialog').length;
    d.setAttribute('aria-labelledby', h.id);
    head.append(h, button('Close', () => d.close())); d.append(head);
    document.body.append(d);
    d.addEventListener('click', e => { if (e.target === d) {
      const r = d.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
    } });
    d.addEventListener('close', () => document.body.classList.toggle('ux-modal', !!document.querySelector('dialog[open]')));
    return d;
  }
  function open(d) { if (!d.open) { d.showModal(); document.body.classList.add('ux-modal'); } }
  const watch = dialog('Your watchlist');
  watch.append(node('p', 'ux-note', 'Saved on this browser. Open a stock to see its latest analysis.'));
  const list = node('div', 'ux-saved-list'); watch.append(list);
  function renderSaved() {
    list.replaceChildren();
    if (!saved.length) {
      const img = node('img', 'ux-art'); img.src = 'research-illustration.webp';
      img.alt = ''; img.width = 600; img.height = 400; img.loading = 'lazy';
      list.append(img, node('h3', '', 'Keep your next research idea close'),
        node('p', 'ux-note', 'Tap Save on a stock or shortlist card to build your watchlist.'),
        button('Find a stock', () => { watch.close(); document.getElementById('sh-q')?.focus(); }));
    }
    saved.forEach(sym => {
      const row = node('div', 'ux-saved-row'); const a = node('a', '', sym);
      a.href = 'stock.html?ticker=' + encodeURIComponent(sym);
      const remove = button('Remove', () => {
        const index = saved.indexOf(sym);
        if (toggle(sym)) {
          const controls = list.querySelectorAll('button');
          (controls[Math.min(index, controls.length - 1)] || watch.querySelector('button')).focus();
        }
      }); remove.setAttribute('aria-label', 'Remove ' + sym + ' from watchlist');
      row.append(a, remove); list.append(row);
    });
  }
  function sync() {
    document.querySelectorAll('[data-save-stock]').forEach(b => {
      const on = saved.includes(b.dataset.saveStock);
      b.textContent = on ? '★ Saved' : '☆ Save'; b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-label', (on ? 'Remove ' : 'Save ') + b.dataset.saveStock + (on ? ' from' : ' to') + ' watchlist');
    }); renderSaved();
  }
  function toggle(sym) {
    sym = normalise(sym); if (!valid(sym)) return false;
    // Read again to avoid overwriting saves made in another tab.
    const current = read(), exists = current.includes(sym);
    if (!exists && current.length >= 100) { announce('Your watchlist holds 100 stocks. Remove one to add another.'); return false; }
    const next = exists ? current.filter(x => x !== sym) : current.concat(sym);
    try { localStorage.setItem(KEY, JSON.stringify(next)); }
    catch (_) { announce('Could not save. Browser storage may be unavailable or full.'); return false; }
    saved = next; sync(); announce(sym + (exists ? ' removed from watchlist' : ' added to watchlist'));
    if (typeof window !== 'undefined' && window.AltahaTrack) {
      window.AltahaTrack('watchlist_changed',
        { ticker: sym, action: exists ? 'removed' : 'added', size: next.length });
    }
    return true;
  }
  function saveButton(sym) {
    const b = button('☆ Save', e => { e.stopPropagation(); toggle(sym); });
    b.dataset.saveStock = normalise(sym); return b;
  }
  window.addEventListener('storage', e => { if (e.key === KEY || e.key === null) { saved = read(); sync(); } });
  function go(section) {
    if (window.AltahaNav) window.AltahaNav.go(section, null, true);
    else location.href = 'index.html#' + section;
  }
  const bar = node('nav', 'ux-bottom'); bar.setAttribute('aria-label', 'Quick navigation');
  const home = button('Home', () => go('screener'));
  const discover = button('Discover', () => go('ideas'));
  const savedButton = button('Watchlist', () => open(watch));
  const more = button('More', () => document.getElementById('sh-burger')?.click());
  more.setAttribute('aria-controls', 'sh-drawer');
  bar.append(home, discover, savedButton, more); document.body.append(bar);
  const desktopSave = button('Watchlist', () => open(watch), 'ux-button ux-desktop-save');
  document.querySelector('.sh-right')?.prepend(desktopSave);
  function active(section) {
    [home, discover].forEach((b, i) => {
      if (section === ['screener', 'ideas'][i]) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
  }
  active(location.pathname.endsWith('stock.html') ? '' : ((location.hash.slice(1).split('/')[0]) || 'screener'));
  window.addEventListener('altaha:navigate', e => active(e.detail.section));
  const burger = document.getElementById('sh-burger');
  if (burger) {
    const update = () => more.setAttribute('aria-expanded', burger.getAttribute('aria-expanded'));
    new MutationObserver(update).observe(burger, { attributes: true, attributeFilter: ['aria-expanded'] }); update();
  }
  const ticker = new URLSearchParams(location.search).get('ticker');
  if (ticker && valid(normalise(ticker))) document.querySelector('.stk-id')?.append(saveButton(ticker));

  // Filter only the rows already returned by the active shortlist/horizon.
  const rows = document.getElementById('idearows');
  if (rows) {
    const controls = node('div', 'ux-filterbar');
    const filters = dialog('Filter this shortlist');
    const queryLabel = node('label', 'ux-field', 'Company or symbol');
    const query = node('input'); query.type = 'search'; query.placeholder = 'Search this shortlist'; queryLabel.append(query);
    const scoreLabel = node('label', 'ux-field', 'Minimum conviction score');
    const score = node('select');
    [0, 50, 60, 70, 80, 90].forEach(v => { const opt = node('option', '', v ? v + '+' : 'Any score'); opt.value = v; score.append(opt); });
    scoreLabel.append(score);
    const count = node('p', 'ux-note'); count.setAttribute('role', 'status');
    const chips = node('div', 'ux-chips');
    const empty = node('div', 'ux-empty'); empty.hidden = true;
    empty.append(node('h3', '', 'No stocks match these filters'), node('p', 'ux-note', 'Try a lower score or clear your search.'), button('Clear filters', reset));
    const show = button('Show results', () => filters.close());
    const foot = node('div', 'ux-dialog-foot'); foot.append(button('Clear filters', reset), show);
    filters.append(queryLabel, scoreLabel, node('p', 'ux-note', 'Filters apply to the currently loaded shortlist. CSV export includes the full shortlist.'), count, foot);
    controls.append(button('Filters', () => open(filters)), chips);
    rows.before(controls); rows.after(empty);
    function reset() { query.value = ''; score.value = '0'; apply(); }
    function apply() {
      let visible = 0; const cards = rows.querySelectorAll('.idea');
      cards.forEach(card => {
        card.hidden = !matches({ symbol: card.dataset.t || '', name: card.dataset.name || '', score: card.dataset.score ?? '' }, query.value, Number(score.value));
        if (!card.hidden) visible++;
      });
      count.textContent = visible + ' of ' + cards.length + ' stocks';
      show.textContent = 'Show ' + visible + ' results'; empty.hidden = !cards.length || visible > 0;
      chips.replaceChildren();
      if (query.value.trim()) chips.append(button('Search: ' + query.value.trim() + ' ×', () => { query.value = ''; apply(); }));
      if (Number(score.value)) chips.append(button('Score: ' + score.value + '+ ×', () => { score.value = '0'; apply(); }));
    }
    function enhance() {
      rows.querySelectorAll('.idea').forEach(card => {
        if (!card.querySelector('[data-save-stock]') && valid(normalise(card.dataset.t)))
          card.querySelector('.idearow-actions')?.prepend(saveButton(card.dataset.t));
      });
      apply(); sync();
    }
    query.addEventListener('input', apply); score.addEventListener('change', apply);
    // Observe only list replacement, not the text/controls added by this module.
    new MutationObserver(enhance).observe(rows, { childList: true }); enhance();
  }

  // A compact first-visit guide below search; never blocks research.
  const host = document.getElementById('view-screener');
  let dismissed = false; try { dismissed = localStorage.getItem('altaha-guide-dismissed') === '1'; } catch (_) {}
  if (host && !dismissed) {
    const guide = node('aside', 'ux-guide');
    const img = node('img', 'ux-art'); img.src = 'research-illustration.webp'; img.alt = ''; img.width = 600; img.height = 400; img.loading = 'lazy';
    const content = node('div'); content.append(node('h2', '', 'A clearer way to research'));
    const steps = node('ol');
    ['Search a company to open its analysis.', 'Read the score, then expand the checks behind it.', 'Save stocks to revisit in your watchlist.'].forEach(t => steps.append(node('li', '', t)));
    content.append(steps, button('Got it', () => { guide.remove(); try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (_) {} }));
    guide.append(img, content); host.querySelector('.hint')?.after(guide);
  }
  const chart = document.getElementById('s-chart');
  if (chart) {
    const expand = button('Expand chart', () => {
      const on = chart.classList.toggle('ux-chart-expanded');
      expand.textContent = on ? 'Collapse chart' : 'Expand chart'; expand.setAttribute('aria-expanded', String(on));
    }); expand.setAttribute('aria-expanded', 'false'); chart.querySelector('h2')?.after(expand);
  }
  sync();
})();

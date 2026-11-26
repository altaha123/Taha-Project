/* Altaha — theme.js
   Light or dark, decided before the first paint, and the one place a script
   asks what a colour is.

   Loaded as a plain blocking script in <head>, ahead of every stylesheet: a
   theme chosen after the page has drawn is a flash of the wrong one.

     AltahaTheme.get()            'light' | 'dark'
     AltahaTheme.set('dark')      choose, remember, repaint
     AltahaTheme.toggle()
     AltahaTheme.onChange(fn)     fn(theme) after every change, however made
     AltahaTheme.color('--gain')  the token's value now, as hex or rgb()
     AltahaTheme.alpha('--border', .5)   the same colour as rgba()
     AltahaTheme.chart()          everything a chart needs, read from tokens

   The choice is the system's until the reader makes one; then it is theirs,
   kept in localStorage under 'altaha-theme'. Changing it fires the window
   event 'altaha:theme' (detail.theme), which is what charts redraw on. */
(function () {
  'use strict';
  var KEY = 'altaha-theme', root = document.documentElement, mq = null, timer = 0, cache = {}, probe = null;

  function saved() {
    try { var v = localStorage.getItem(KEY); return v === 'dark' || v === 'light' ? v : null; }
    catch (e) { return null; }
  }
  function system() {
    try { mq = mq || window.matchMedia('(prefers-color-scheme: dark)'); return mq.matches ? 'dark' : 'light'; }
    catch (e) { return 'light'; }
  }
  function get() { return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }

  /* Before first paint. No transition: a page that loads dark was never light. */
  root.setAttribute('data-theme', saved() || system());

  function apply(theme, remember) {
    theme = theme === 'dark' ? 'dark' : 'light';
    if (remember) { try { localStorage.setItem(KEY, theme); } catch (e) {} }
    if (theme === get()) return;
    root.classList.add('theme-switching');
    clearTimeout(timer);
    timer = setTimeout(function () { root.classList.remove('theme-switching'); }, 260);
    root.setAttribute('data-theme', theme);
  }
  function set(theme) { apply(theme, true); }
  function toggle() { set(get() === 'dark' ? 'light' : 'dark'); return get(); }

  /* One announcement, whoever changed the attribute. */
  var listeners = [];
  function announce() {
    cache = {};
    var t = get();
    try { window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } })); } catch (e) {}
    listeners.slice().forEach(function (fn) { try { fn(t); } catch (e) { setTimeout(function () { throw e; }); } });
  }
  try {
    new MutationObserver(announce).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  } catch (e) {}
  function onChange(fn) { if (typeof fn === 'function') listeners.push(fn); }

  /* The system changes its mind (sunset): follow, unless the reader chose. */
  try {
    mq = mq || window.matchMedia('(prefers-color-scheme: dark)');
    var follow = function (e) { if (!saved()) apply(e.matches ? 'dark' : 'light', false); };
    if (mq.addEventListener) mq.addEventListener('change', follow); else if (mq.addListener) mq.addListener(follow);
  } catch (e) {}
  /* Another tab changed it. */
  window.addEventListener('storage', function (e) {
    if (e.key === KEY && (e.newValue === 'dark' || e.newValue === 'light')) apply(e.newValue, false);
  });

  /* ── Colours for scripts ─────────────────────────────────────────────────
     Canvas and the chart libraries cannot read var(--x). They ask here. */
  function raw(name) {
    try { return getComputedStyle(root).getPropertyValue(name).trim(); } catch (e) { return ''; }
  }
  function parts(value) {
    var m, v = String(value || '').trim();
    if ((m = /^#([0-9a-f]{3,8})$/i.exec(v))) {
      var h = m[1];
      if (h.length < 6) h = h.replace(/./g, '$&$&');
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16),
              h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1];
    }
    if ((m = /^rgba?\(([^)]+)\)$/i.exec(v))) {
      var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    /* Anything else (a color-mix) is painted once and read back. */
    try {
      probe = probe || document.createElement('canvas').getContext('2d', { willReadFrequently: true });
      probe.canvas.width = probe.canvas.height = 1;
      probe.clearRect(0, 0, 1, 1); probe.fillStyle = v; probe.fillRect(0, 0, 1, 1);
      var d = probe.getImageData(0, 0, 1, 1).data;
      return [d[0], d[1], d[2], d[3] / 255];
    } catch (e) { return [0, 0, 0, 1]; }
  }
  function color(name) {
    var key = get() + name;
    if (!(key in cache)) cache[key] = raw(name);
    return cache[key];
  }
  function alpha(name, a) {
    var c = parts(name.charAt(0) === '-' ? color(name) : name);
    // theme-ok: this is where a token becomes an rgba() for canvas and the chart libraries
    return 'rgba(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ',' +   // theme-ok
           Math.round(c[3] * a * 1000) / 1000 + ')';
  }
  function font(name) { return raw(name) || 'sans-serif'; }

  /* Everything a chart needs. Lines are 1.5px, an area is its line at 15% and
     flat, gridlines are the border at half strength, axis labels are 11px. */
  function chart() {
    var series = [1, 2, 3, 4, 5, 6].map(function (i) { return color('--chart-' + i); });
    return {
      theme: get(),
      series: series,
      fills: series.map(function (c) { return alpha(c, 0.15); }),
      gain: color('--gain'), loss: color('--loss'),
      gainFill: alpha('--gain', 0.15), lossFill: alpha('--loss', 0.15),
      gainSoft: alpha('--gain', 0.45), lossSoft: alpha('--loss', 0.45),
      highlight: color('--highlight'), accent: color('--accent'), onAccent: color('--on-accent'),
      warning: color('--warning'), info: color('--info'),
      bg: color('--bg'), surface: color('--surface'), raised: color('--surface-raised'),
      border: color('--border'), borderStrong: color('--border-strong'),
      grid: alpha('--border', 0.5),
      text: color('--text-primary'), textSecondary: color('--text-secondary'), axis: color('--text-muted'),
      lineWidth: 1.5, fillOpacity: 0.15,
      axisSize: parseInt(raw('--fs-label'), 10) || 11, displaySize: parseInt(raw('--fs-display'), 10) || 40,
      fontSans: font('--font-sans'), fontDisplay: font('--font-display'), fontMono: font('--font-mono')
    };
  }

  window.AltahaTheme = {
    get: get, set: set, toggle: toggle, onChange: onChange,
    color: color, alpha: alpha, chart: chart, font: font
  };
})();

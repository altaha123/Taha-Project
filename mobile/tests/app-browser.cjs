/* The app's bundle, in a real browser, on a phone-sized screen with a notch.
 *
 * Everything src/bridge.js does fails silently when it breaks: a Share button
 * that opens nothing, an export that saves nothing, a link that shows the home
 * page instead of the one asked for. None of it throws. So each is done here
 * the way a reader would do it, and the call that reaches the phone is checked.
 *
 * Needs `npm run build` first. The phone is faked one layer down (harness.cjs);
 * the API is not called at all, so this runs with no network.
 *
 *     node tests/app-browser.cjs
 */
const { chromium } = require('playwright');
const { PAGES, serve, fakePhone } = require('./harness.cjs');

const CDN = /unpkg\.com|jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com|posthog\.com|sentry/;
const TOP = 47, BOTTOM = 34;          // an iPhone's notch and home indicator

let failed = 0, passed = 0;
function check(name, ok, detail) {
  if (ok) { passed++; console.log('  ok    ' + name); }
  else { failed++; console.log('  FAIL  ' + name + (detail !== undefined ? '\n          ' + JSON.stringify(detail) : '')); }
}

async function main() {
  if (!PAGES.length) throw new Error('mobile/www is empty: run `npm run build` first');
  const { server, origin } = await serve();
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  await context.addInitScript(fakePhone);

  const outside = [];                 // every request that left the bundle
  await context.route((url) => url.origin !== origin, (route) => {
    outside.push(route.request().url());
    return route.abort();
  });

  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e.stack || e.message)));
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: TOP, bottom: BOTTOM } });

  const open = async (path) => {
    await page.goto(origin + path, { waitUntil: 'load' });
    await page.waitForFunction(() => window.AltahaNative && document.readyState === 'complete');
  };
  const made = (plugin, method) => page.evaluate(([p, m]) => window.__native.made(p, m), [plugin, method]);
  const forget = () => page.evaluate(() => { window.__native.calls.length = 0; });
  const settle = () => page.waitForTimeout(150);

  /* ── every page of the bundle ─────────────────────────────────────────── */
  console.log('\nEvery page loads from the bundle');
  for (const name of PAGES) {
    outside.length = 0; errors.length = 0;
    await open('/' + name);
    await page.waitForTimeout(400);
    const state = await page.evaluate(() => ({
      native: document.documentElement.classList.contains('native-app'),
      android: document.documentElement.classList.contains('native-android'),
      api: window.API_BASE, site: window.SITE_URL,
      fit: (document.querySelector('meta[name=viewport]') || {}).content || '',
    }));
    check(name + ' knows it is in the app', state.native && state.android, state);
    check(name + ' is told where the API and the site are',
      state.api === 'https://taha-project.onrender.com' && state.site === 'https://altahascreener.in', state);
    check(name + ' covers the whole screen', /viewport-fit=cover/.test(state.fit), state.fit);
    const cdn = outside.filter((u) => CDN.test(u));
    check(name + ' asks no CDN and no tracker for anything', cdn.length === 0, cdn);
    const own = errors.filter((e) => /native-bridge/.test(e));
    check(name + ' raises nothing from the bridge', own.length === 0, own);
  }

  /* ── the home page is the real one ─────────────────────────────────────── */
  console.log('\nThe home page works inside the app');
  errors.length = 0;
  await open('/');
  await page.waitForSelector('.sh-chrome');
  const home = await page.evaluate(() => ({
    // index.html declares `const API_BASE` at the top of its own script. If
    // the bridge's window.API_BASE collided with it, that whole script (the
    // site) would be a SyntaxError and none of this would exist.
    script: typeof jget === 'function' || typeof $ === 'function',
    charts: typeof LightweightCharts === 'object' && typeof LightweightCharts.createChart === 'function',
    inter: document.fonts.check('16px Inter'),
    mono: document.fonts.check('16px "IBM Plex Mono"'),
    serif: document.fonts.check('16px "Instrument Serif"'),
    rupee: document.fonts.check('16px Inter', '₹'),
  }));
  check('the splash screen is taken down as soon as the page is ready',
    (await made('SplashScreen', 'hide')).length === 1);
  check('the page\'s own script ran (API_BASE did not collide)', home.script, home);
  check('no "already been declared" error', !errors.some((e) => /already been declared|redeclaration/i.test(e)), errors);
  check('the chart library came from the bundle', home.charts, home);
  check('the three fonts came from the bundle, with the rupee sign',
    home.inter && home.mono && home.serif && home.rupee, home);

  /* ── the notch ────────────────────────────────────────────────────────── */
  console.log('\nThe header and the bottom bar clear the notch and the gesture bar');
  const box = await page.evaluate(() => {
    const chrome = document.querySelector('.sh-chrome');
    const first = chrome.firstElementChild.getBoundingClientRect();
    const bottom = document.querySelector('.ux-bottom');
    return {
      chromeTop: chrome.getBoundingClientRect().top,
      firstRowTop: Math.round(first.top),
      chromeHeight: chrome.offsetHeight,
      bodyPad: parseFloat(getComputedStyle(document.body).paddingTop),
      bottomPad: bottom ? parseFloat(getComputedStyle(bottom).paddingBottom) : null,
    };
  });
  check('the header starts at the very top, its first row below the status bar',
    box.chromeTop === 0 && box.firstRowTop === TOP, box);
  check('the page starts where the header ends', Math.abs(box.bodyPad - box.chromeHeight) <= 2, box);
  check('the bottom bar keeps clear of the home indicator', box.bottomPad !== null && box.bottomPad >= BOTTOM, box);

  await open('/signin.html');
  const plain = await page.evaluate(() => ({
    border: parseFloat(getComputedStyle(document.body).borderTopWidth),
    google: getComputedStyle(document.getElementById('si-google')).display,
    or: getComputedStyle(document.getElementById('si-or')).display,
  }));
  check('a page with no header keeps clear of the status bar', plain.border === TOP, plain);
  check('the Google button, which cannot work in a web view, is not offered',
    plain.google === 'none' && plain.or === 'none', plain);

  /* ── links ────────────────────────────────────────────────────────────── */
  console.log('\nLinks land where they should');
  const tap = async (href, attrs) => {
    await page.evaluate(([h, extra]) => {
      const stale = document.getElementById('probe');
      if (stale) stale.remove();
      const a = document.createElement('a');
      a.href = h; a.textContent = 'x'; a.id = 'probe';
      a.style.cssText = 'position:fixed;top:60px;left:10px;z-index:2147483647;padding:20px;background:#fff';
      for (const k of Object.keys(extra || {})) a.setAttribute(k, extra[k]);
      document.body.appendChild(a);
    }, [href, attrs || {}]);
    await page.click('#probe');
  };

  await open('/');
  await tap('/methodology');
  await page.waitForURL(/\/methodology\.html$/);
  check('/methodology opens the methodology page, not the home page', true);

  await open('/');
  await tap('/stock-TCS');
  await page.waitForURL(/\/stock\.html\?ticker=TCS$/);
  check('/stock-TCS opens the stock page for TCS', true);

  await open('/');
  await tap('https://altahascreener.in/stock?ticker=INFY#score');
  await page.waitForURL(/\/stock\.html\?ticker=INFY#score$/);
  check('a link to the live site stays in the app', true);

  await open('/');
  await forget();
  await tap('https://www.nseindia.com/companies-listing/corporate-filings-announcements', { target: '_blank', rel: 'noopener' });
  await settle();
  let calls = await made('Browser', 'open');
  check('an outside link opens in a browser tab over the app',
    calls.length === 1 && /nseindia\.com/.test(calls[0].options.url) && new URL(page.url()).pathname === '/', calls);

  await forget();
  await tap('/stocks');
  await settle();
  calls = await made('Browser', 'open');
  check('a server-rendered page of the site opens from the site, not as a broken local page',
    calls.length === 1 && calls[0].options.url === 'https://altahascreener.in/stocks', calls);

  await forget();
  outside.length = 0;
  await page.evaluate(() => { window.open('https://wa.me/?text=hello', '_blank', 'noopener'); });
  await settle();
  check('a WhatsApp link is handed to the phone, not to a browser tab',
    outside.some((u) => /^https:\/\/wa\.me\//.test(u)) && (await made('Browser', 'open')).length === 0, outside);

  /* ── share ────────────────────────────────────────────────────────────── */
  console.log('\nShare opens the phone\'s share sheet');
  await open('/');
  await forget();
  const shared = await page.evaluate(async () => {
    const file = new File([new Blob(['PNGDATA'], { type: 'image/png' })], 'altaha-TCS.png', { type: 'image/png' });
    const can = navigator.canShare({ files: [file] });
    await navigator.share({ title: 'TCS on Altaha', text: 'Score 53', url: 'https://altahascreener.in/share/TCS', files: [file] });
    return can;
  });
  const wrote = await made('Filesystem', 'writeFile');
  const share = await made('Share', 'share');
  check('the site is told it can share a picture', shared === true);
  check('the picture is written to the cache first',
    wrote.length === 1 && wrote[0].options.path === 'shared/altaha-TCS.png' &&
    wrote[0].options.directory === 'CACHE' && wrote[0].options.data === Buffer.from('PNGDATA').toString('base64'), wrote);
  check('then shared with its text and link',
    share.length === 1 && share[0].options.files[0] === 'file:///data/cache/shared/altaha-TCS.png' &&
    share[0].options.text === 'Score 53' && share[0].options.url === 'https://altahascreener.in/share/TCS', share);

  await page.evaluate(() => { window.__native.results['Share.share'] = () => { throw new Error('Share canceled'); }; });
  const dismissed = await page.evaluate(() => navigator.share({ text: 'x' }).then(() => 'resolved', (e) => e.name));
  check('closing the sheet reads as AbortError, which the site ignores', dismissed === 'AbortError', dismissed);

  /* ── downloads ────────────────────────────────────────────────────────── */
  console.log('\nAn export is saved through the share sheet');
  await open('/');
  await forget();
  await page.evaluate(() => {
    // Exactly what portfolio.js and query.js do, including revoking at once.
    const blob = new Blob(['Symbol,Qty\nTCS,10\n'], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'altaha-portfolio-2026-11-20.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  });
  await page.waitForFunction(() => window.__native.made('Share', 'share').length === 1);
  const csv = await made('Filesystem', 'writeFile');
  check('a CSV made in the page reaches the phone whole, though its address was revoked',
    csv.length === 1 && csv[0].options.path === 'downloads/altaha-portfolio-2026-11-20.csv' &&
    Buffer.from(csv[0].options.data, 'base64').toString() === 'Symbol,Qty\nTCS,10\n', csv);
  const toast = await page.evaluate(() => {
    const t = document.getElementById('native-toast');
    return t ? t.className : '';
  });
  check('and nothing is reported as failed', !/\bon\b/.test(toast), toast);

  await forget();
  await tap('data:text/calendar;charset=utf-8,BEGIN%3AVCALENDAR', { download: 'money-check-in.ics' });
  await page.waitForFunction(() => window.__native.made('Share', 'share').length === 1);
  const ics = await made('Filesystem', 'writeFile');
  check('a download link that is tapped, not clicked by a script, is saved the same way',
    ics.length === 1 && ics[0].options.path === 'downloads/money-check-in.ics' &&
    Buffer.from(ics[0].options.data, 'base64').toString() === 'BEGIN:VCALENDAR' &&
    new URL(page.url()).pathname === '/', ics);

  /* ── print ────────────────────────────────────────────────────────────── */
  console.log('\nPrint opens the phone\'s print dialog');
  await forget();
  const after = await page.evaluate(() => new Promise((resolve) => {
    window.addEventListener('afterprint', () => resolve(true), { once: true });
    window.print();
    setTimeout(() => resolve(false), 2000);
  }));
  calls = await made('AltahaShell', 'print');
  check('window.print() reaches the phone', calls.length === 1 && !calls[0].options.html, calls);
  check('and the page is told when it is over', after === true);

  await forget();
  await page.evaluate(() => {
    // portfolio.js: a new window, a document written into it, then print.
    const w = window.open('', '_blank');
    w.document.write('<!doctype html><title>Portfolio review</title><h1>Report</h1>');
    w.document.close();
    w.focus(); w.print();
  });
  await settle();
  calls = await made('AltahaShell', 'print');
  check('a report written into a new window prints as that report',
    calls.length === 1 && /<h1>Report<\/h1>/.test(calls[0].options.html) && calls[0].options.name === 'Portfolio review', calls);

  /* ── the phone's own buttons ──────────────────────────────────────────── */
  console.log('\nBack, appearance, connection and links from outside');
  await open('/');
  await forget();
  await page.evaluate(() => window.__native.emit('App', 'backButton', { canGoBack: false }));
  await settle();
  check('Back on the first page puts the app away', (await made('App', 'minimizeApp')).length === 1);

  await page.evaluate(() => { location.hash = '#research'; });
  await page.waitForURL(/#research$/);
  await page.evaluate(() => window.__native.emit('App', 'backButton', { canGoBack: true }));
  await page.waitForURL((u) => !/#research$/.test(u.href));
  check('Back anywhere else goes back a page', true);

  await forget();
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await settle();
  const style = await made('SystemBars', 'setStyle');
  const bg = await made('AltahaShell', 'setBackground');
  check('a dark page asks for light status-bar icons', style.length === 1 && style[0].options.style === 'DARK', style);
  check('and a dark colour behind the page while the next one loads',
    bg.length === 1 && bg[0].options.dark === true && /^#[0-9A-F]{6}$/.test(bg[0].options.color) &&
    parseInt(bg[0].options.color.slice(1, 3), 16) < 64, bg);

  await page.evaluate(() => window.__native.emit('Network', 'networkStatusChange', { connected: false }));
  await settle();
  const off = await page.evaluate(() => document.getElementById('native-offline').className);
  await page.evaluate(() => window.__native.emit('Network', 'networkStatusChange', { connected: true }));
  await settle();
  const on = await page.evaluate(() => document.getElementById('native-offline').className);
  check('losing the connection says so, and getting it back takes the notice away', /\bon\b/.test(off) && !/\bon\b/.test(on), { off, on });

  await page.evaluate(() => window.__native.emit('App', 'appUrlOpen', { url: 'altaha://stock?ticker=RELIANCE' }));
  await page.waitForURL(/\/stock\.html\?ticker=RELIANCE$/);
  check('altaha://stock?ticker=RELIANCE opens that company', true);

  await page.waitForFunction(() => window.AltahaNative && window.__native.listeners['App:appUrlOpen']);
  await page.evaluate(() => window.__native.emit('App', 'appUrlOpen', { url: 'https://altahascreener.in/signin?token=abc123' }));
  await page.waitForURL(/\/signin\.html\?token=abc123$/);
  check('an emailed sign-in link opens the sign-in page with its token', true);

  await browser.close();
  server.close();
  console.log('\n' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });

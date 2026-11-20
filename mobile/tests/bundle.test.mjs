/* The bundle the apps ship, and where its links go. No browser.
 *
 *     npm run build && node tests/bundle.test.mjs
 *
 * Two kinds of mistake are caught here before they reach a phone:
 *
 *   · the site gains a link the app cannot follow. An address with no
 *     extension only resolves on the website because Vercel rewrites it;
 *     inside the app it silently shows the home page. Every such link in
 *     frontend/ is put through the router.
 *   · the site gains something the app must not load: a script from a CDN
 *     (a page that hangs with no signal), or a file that only makes sense
 *     on the website.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pageFor, routeFor } from '../src/routes.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WWW = path.resolve(HERE, '..', 'www');
const FRONTEND = path.resolve(HERE, '..', '..', 'frontend');

assert.ok(fs.existsSync(path.join(WWW, 'index.html')), 'mobile/www is empty: run `npm run build` first');

let n = 0;
function test(name, fn) { fn(); n++; console.log('  ok    ' + name); }

const vercel = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'vercel.json'), 'utf8'));
const pages = fs.readdirSync(WWW).filter((f) => /\.html$/.test(f)).sort();
const local = {}, remote = [];
for (const r of vercel.rewrites) {
  if (/^https?:/.test(r.destination)) remote.push(r.source);
  else local[r.source] = r.destination.replace(/^\//, '');
}
const cfg = { site: 'https://altahascreener.in', api: 'https://taha-project.onrender.com', routes: { local, remote }, pages };

/* The two addresses a page of the app can have. */
const ANDROID = 'https://localhost/index.html';
const IOS = 'capacitor://localhost/stock.html?ticker=TCS';

console.log('\nWhere links go');

test('files the app carries are left to the web view', () => {
  for (const base of [ANDROID, IOS]) {
    for (const href of ['stock.html?ticker=TCS', './', './#portfolio/planner', 'signin.html', '#score', 'pro.html'])
      assert.equal(routeFor(href, base, cfg), null, href);
  }
});

test('every page Vercel serves without ".html" opens the page itself', () => {
  for (const [source, page] of Object.entries(local)) {
    assert.ok(fs.existsSync(path.join(WWW, page)), page + ' is not in the bundle');
    for (const base of [ANDROID, IOS]) {
      assert.deepEqual(routeFor(source + '?a=1#b', base, cfg), { kind: 'local', href: '/' + page + '?a=1#b' }, source);
      assert.deepEqual(routeFor('https://altahascreener.in' + source, base, cfg), { kind: 'local', href: '/' + page }, source);
    }
  }
});

test('a company\'s public address opens the stock page for it', () => {
  assert.deepEqual(routeFor('/stock-TCS', ANDROID, cfg), { kind: 'local', href: '/stock.html?ticker=TCS' });
  assert.deepEqual(routeFor('/stock-M%26M', IOS, cfg), { kind: 'local', href: '/stock.html?ticker=M%26M' });
  assert.deepEqual(routeFor('/stock-BAJAJ-AUTO', ANDROID, cfg), { kind: 'local', href: '/stock.html?ticker=BAJAJ-AUTO' });
  // A symbol with a dot must not be mistaken for a file with an extension.
  assert.deepEqual(routeFor('/stock-TCS.NS', ANDROID, cfg), { kind: 'local', href: '/stock.html?ticker=TCS.NS' });
});

test('pages the API renders open from the site, never as a local page', () => {
  for (const r of vercel.rewrites.filter((x) => /^https?:/.test(x.destination))) {
    const example = r.source.replace(':path*', 'stock.png').replace(':symbol', 'TCS').replace(':slug', 'banks');
    if (/^\/stock-/.test(example)) continue;     // carried by the app, above
    const got = routeFor(example, ANDROID, cfg);
    assert.equal(got && got.kind, 'browser', example);
    assert.equal(got.url, 'https://altahascreener.in' + example);
  }
});

test('the home page of the live site is the app\'s home page', () => {
  assert.deepEqual(routeFor('https://altahascreener.in/?go=watchlists&wl=abc', ANDROID, cfg),
    { kind: 'local', href: '/index.html?go=watchlists&wl=abc' });
  assert.deepEqual(routeFor('https://www.altahascreener.in/#research/ideas', IOS, cfg),
    { kind: 'local', href: '/index.html#research/ideas' });
});

test('everything else goes outside: a browser tab, or the app that owns the link', () => {
  assert.equal(routeFor('https://www.nseindia.com/x.pdf', ANDROID, cfg).kind, 'browser');
  assert.equal(routeFor('https://taha-project.onrender.com/share/TCS', ANDROID, cfg).kind, 'browser');
  assert.equal(routeFor('https://wa.me/?text=hi', ANDROID, cfg).kind, 'system');
  assert.equal(routeFor('https://x.com/intent/tweet?text=hi', IOS, cfg).kind, 'system');
  assert.equal(routeFor('https://t.me/share/url?url=x', IOS, cfg).kind, 'system');
  // Not a look-alike: evilwa.me is not WhatsApp, and notaltahascreener.in is not the site.
  assert.equal(routeFor('https://evilwa.me/', ANDROID, cfg).kind, 'browser');
  assert.equal(routeFor('https://notaltahascreener.in/stock?ticker=TCS', ANDROID, cfg).kind, 'browser');
  for (const href of ['mailto:hello@altahascreener.in', 'tel:+911234567890', 'blob:https://localhost/1', 'data:text/csv,a'])
    assert.equal(routeFor(href, ANDROID, cfg), null, href);
});

test('links opened from outside the app', () => {
  assert.equal(pageFor('altaha://stock?ticker=TCS', cfg), '/stock.html?ticker=TCS');
  assert.equal(pageFor('altaha:///planner', cfg), '/planner.html');
  assert.equal(pageFor('altaha://', cfg), '/index.html');
  assert.equal(pageFor('https://altahascreener.in/signin?token=abc', cfg), '/signin.html?token=abc');
  assert.equal(pageFor('https://altahascreener.in/stock-INFY', cfg), '/stock.html?ticker=INFY');
  assert.equal(pageFor('https://altahascreener.in/share/TCS', cfg), '');      // shown in a browser tab instead
  assert.equal(pageFor('https://example.com/stock?ticker=TCS', cfg), '');     // not the site: ignored
  assert.equal(pageFor('javascript:alert(1)', cfg), '');
  assert.equal(pageFor('', cfg), '');
});

test('every link written in frontend/ that starts with "/" has somewhere to go', () => {
  const seen = new Set();
  for (const file of fs.readdirSync(FRONTEND).filter((f) => /\.(html|js)$/.test(f) && !/\.test\.js$/.test(f))) {
    const text = fs.readFileSync(path.join(FRONTEND, file), 'utf8');
    for (const m of text.matchAll(/href=\\?["'](\/[A-Za-z][^"'\\$<> ]*)/g)) seen.add(m[1]);
  }
  assert.ok(seen.size > 5, 'found no links to check: the pattern has rotted');
  for (const href of seen) {
    const got = routeFor(href, ANDROID, cfg);
    assert.ok(got && (got.kind === 'local' || got.kind === 'browser'), href + ' would show the home page');
    if (got.kind === 'local') assert.ok(fs.existsSync(path.join(WWW, got.href.slice(1).split(/[?#]/)[0])), href);
  }
});

console.log('\nWhat is in the bundle');

test('every page starts with the bridge and ends its head with native.css', () => {
  for (const page of pages) {
    const html = fs.readFileSync(path.join(WWW, page), 'utf8');
    const first = /<script\b[^>]*>/.exec(html);
    assert.equal(first && first[0], '<script src="native-bridge.js">', page + ': the bridge is not the first script');
    assert.match(html, /<link rel="stylesheet" href="native\.css">\s*<\/head>/, page);
    assert.match(html, /viewport-fit=cover/, page);
  }
});

test('nothing is loaded from a CDN', () => {
  for (const file of fs.readdirSync(WWW).filter((f) => /\.(html|js|css)$/.test(f))) {
    const text = fs.readFileSync(path.join(WWW, file), 'utf8');
    assert.doesNotMatch(text, /https:\/\/(unpkg\.com|cdn\.jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com)/, file);
  }
  assert.ok(fs.statSync(path.join(WWW, 'vendor', 'lightweight-charts.js')).size > 100000);
  const fonts = fs.readFileSync(path.join(WWW, 'vendor', 'fonts', 'fonts.css'), 'utf8');
  for (const family of ['Inter', 'IBM Plex Mono', 'Instrument Serif']) assert.ok(fonts.includes(`'${family}'`), family);
  for (const m of fonts.matchAll(/url\(([^)]+)\)/g)) assert.ok(fs.existsSync(path.join(WWW, 'vendor', 'fonts', m[1])), m[1]);
});

test('what belongs to the website stays on the website', () => {
  for (const name of ['tests', 'tools', 'vercel.json', 'robots.txt']) assert.ok(!fs.existsSync(path.join(WWW, name)), name);
  assert.equal(fs.readdirSync(WWW).filter((f) => /\.test\.js$/.test(f)).length, 0);
});

test('every page of the site is in the app', () => {
  const site = fs.readdirSync(FRONTEND).filter((f) => /\.html$/.test(f)).sort();
  assert.deepEqual(pages, site);
});

test('the bundle is small enough to ship inside an app', () => {
  const total = fs.readdirSync(WWW, { recursive: true })
    .map((f) => path.join(WWW, f)).filter((f) => fs.statSync(f).isFile())
    .reduce((sum, f) => sum + fs.statSync(f).size, 0);
  assert.ok(total < 15 * 1048576, (total / 1048576).toFixed(1) + ' MB');
});

console.log('\n' + n + ' passed');

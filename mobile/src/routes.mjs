/* Where a link goes inside the app.
 *
 * Pure functions, no browser and no Capacitor, so tests/bundle.test.mjs can
 * put every address the site publishes through them.
 *
 * A link ends in one of four places:
 *
 *   null      a file the app carries (stock.html, ./#portfolio): the web view
 *             just loads it
 *   local     an address that stands for a page the app carries, which only
 *             resolves on the website because Vercel rewrites it:
 *             /methodology, /stock-TCS, https://altahascreener.in/stock?ticker=TCS
 *   browser   a page outside the app: a filing, a news story, or one of the
 *             site's own server-rendered pages (/stocks, /share/RELIANCE).
 *             Opens in a browser tab over the app.
 *   system    a link another app should answer: WhatsApp, Telegram, X
 */

const SYSTEM_HOSTS = /(^|\.)(wa\.me|whatsapp\.com|t\.me|telegram\.me|x\.com|twitter\.com|linkedin\.com|facebook\.com)$/i;

function onSite(u, cfg) {
  const host = new URL(cfg.site).hostname;
  return u.hostname === host || u.hostname === 'www.' + host;
}

/* The page of the app that a path on the site stands for, or ''. */
function sitePage(u, cfg) {
  const p = u.pathname.replace(/\/+$/, '') || '/';
  const tail = u.search + u.hash;
  if (p === '/' || p === '/index.html') return 'index.html' + tail;

  // /stock-TCS is the page a search engine is sent; here it is stock.html.
  const m = /^\/stock-([^/]+)$/.exec(p);
  if (m) {
    const q = new URLSearchParams(u.search);
    let symbol = m[1];
    try { symbol = decodeURIComponent(symbol); } catch (e) {}
    q.set('ticker', symbol);
    return 'stock.html?' + q.toString() + u.hash;
  }

  if (Object.prototype.hasOwnProperty.call(cfg.routes.local, p)) return cfg.routes.local[p] + tail;
  if (cfg.pages.indexOf(p.slice(1)) > -1) return p.slice(1) + tail;
  return '';
}

/* A path the website hands to the API to render: /share/TCS, /og/stock.png,
   /sitemap.xml. vercel.json writes these as "/share/:path*", so everything
   before the first colon is the part that has to match. */
function isRemote(p, cfg) {
  return (cfg.routes.remote || []).some((source) => {
    const i = source.indexOf(':');
    return i < 0 ? p === source : p.indexOf(source.slice(0, i)) === 0;
  });
}

export function routeFor(href, base, cfg) {
  let u, here;
  try { u = new URL(href, base); here = new URL(base); } catch (e) { return null; }
  if (!/^(https?|capacitor):$/.test(u.protocol)) return null;      // mailto:, tel:, blob:, data:

  if (u.protocol === here.protocol && u.host === here.host) {
    const p = u.pathname;
    const isStock = /^\/stock-[^/]+\/?$/.test(p);
    if (!isStock && !isRemote(p, cfg) && (p === '/' || /\.[a-z0-9]+$/i.test(p))) return null;
    const page = isStock || !isRemote(p, cfg) ? sitePage(u, cfg) : '';
    return page ? { kind: 'local', href: '/' + page }
                : { kind: 'browser', url: cfg.site + p + u.search + u.hash };
  }

  if (onSite(u, cfg)) {
    const page = sitePage(u, cfg);
    return page ? { kind: 'local', href: '/' + page } : { kind: 'browser', url: u.href };
  }

  return { kind: SYSTEM_HOSTS.test(u.hostname) ? 'system' : 'browser', url: u.href };
}

/* A link opened from outside the app: https://altahascreener.in/… once the
   domain is verified for the app, or altaha://… always. Returns the page to
   show, or '' to leave the app where it is. */
export function pageFor(url, cfg) {
  if (!url) return '';
  let s = String(url);
  const custom = /^altaha:\/\/\/?(.*)$/i.exec(s);
  if (custom) s = cfg.site + '/' + custom[1];
  let u;
  try { u = new URL(s); } catch (e) { return ''; }
  if (!/^https?:$/.test(u.protocol) || !onSite(u, cfg)) return '';
  const page = sitePage(u, cfg);
  return page ? '/' + page : '';
}

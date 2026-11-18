/* Keep ".html" out of the address bar.
 *
 * Every page loads this first, before anything paints. It only rewrites the
 * address shown (history.replaceState): no reload, no hashchange, and the
 * query string and #hash are kept, so ?ticker=, ?token= and the tab the hash
 * names all still work.
 *
 *   /index.html#research/ideas   ->  /#research/ideas      on any web server
 *   /stock.html?ticker=TCS       ->  /stock?ticker=TCS     only where vercel.json is live
 *
 * The homepage is safe everywhere: every server answers / with index.html.
 * /stock is not: it exists only because vercel.json rewrites it to
 * stock.html, so on the test servers or a local copy a reload of /stock would
 * 404. Hence the host check for every page but the homepage.
 *
 * Why rewrites and not Vercel's cleanUrls: cleanUrls answers /stock.html with
 * a redirect, and Vercel's own static server (serve-handler) drops the query
 * string on that redirect. /stock.html?ticker=TCS landed on an empty /stock,
 * and an emailed /signin.html?token=... lost its token. Nothing here goes
 * over the network, so there is nothing to drop.
 */
(function (l, h) {
  if (!h || !h.replaceState || !/^https?:$/.test(l.protocol)) return;
  var p = l.pathname, clean = null;
  if (/\/index\.html$/.test(p)) clean = p.replace(/index\.html$/, '');
  else if (/\.html$/.test(p) && /(^|\.)altahascreener\.in$|\.vercel\.app$/.test(l.hostname)) clean = p.replace(/\.html$/, '');
  if (clean === null) return;
  try { h.replaceState(h.state, '', clean + l.search + l.hash); } catch (e) {}
})(location, window.history);

/* The company a page is about.
 *
 * A company has two addresses: /stock?ticker=TCS, the static page, and
 * /stock-TCS, the same page sent by the API with the company's figures
 * already in it, which is the one a search engine is given
 * (backend/company_pages.py). Four scripts ask which company this is, and
 * each used to read ?ticker= for itself; on /stock-TCS all four would have
 * found nothing and drawn an empty page. They ask here instead. The query
 * string wins, so a test or an old link can still name the company outright.
 */
window.AltahaPageTicker = function () {
  var t = '';
  try { t = new URLSearchParams(location.search).get('ticker') || ''; } catch (e) {}
  if (!t) {
    var m = /\/stock-([^\/]+)\/?$/.exec(location.pathname);
    if (m) { try { t = decodeURIComponent(m[1]); } catch (e) { t = m[1]; } }
  }
  return t.trim();
};

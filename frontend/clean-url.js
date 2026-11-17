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

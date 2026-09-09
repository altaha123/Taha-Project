/* Reveal new cards and evidence bars without rewriting financial values.
   Content stays visible if observation is unavailable; no background timer. */
(function () {
  "use strict";
  if (window.__ALTAHA_MOTION__) return;
  window.__ALTAHA_MOTION__ = 1;
  var media = window.matchMedia('(prefers-reduced-motion: reduce)');
  var seen = new WeakSet();
  function watch(root) {
    root.querySelectorAll('.idea, .tk, .statcell, .alertcard, .mktctx, .fitem, .vcard, .lrow').forEach(function (el) {
      if (seen.has(el)) return;
      seen.add(el);
      if (!media.matches && el.animate) el.animate([
        { opacity: .65, transform: 'translateY(6px)' },
        { opacity: 1, transform: 'translateY(0)' }
      ], { duration: 180, easing: 'ease-out' });
    });
  }
  function start() {
    watch(document);
    new MutationObserver(function (records) {
      records.forEach(function (r) { r.addedNodes.forEach(function (n) {
        if (n.nodeType === 1) watch(n.parentElement || n);
      }); });
    }).observe(document.body, { childList: true, subtree: true });
    media.addEventListener('change', function () {
      if (media.matches && document.getAnimations) document.getAnimations().forEach(function (a) { a.cancel(); });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

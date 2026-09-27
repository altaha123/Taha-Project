/* Homepage visuals and motion. Financial labels always show the received
   value; only the corresponding graphic interpolates. No animation library,
   request loop, synthetic price history or external image dependency. */
(function () {
  'use strict';
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const previous = new Map(), watched = new WeakSet(), active = new Set();
  let observer;
  // Motion stays on; an obsolete saved pause setting must not disable it.
  const allowed = () => !media.matches && !document.hidden;

  function run(node, frames, options) {
    if (!allowed() || !node.animate) return;
    const animation = node.animate(frames, options);
    active.add(animation);
    animation.finished.catch(() => {}).finally(() => active.delete(animation));
  }
  function cancel() { active.forEach(a => a.cancel()); active.clear(); }
  function applyPreference() {
    document.documentElement.dataset.motion = media.matches ? 'off' : 'on';
    if (!allowed()) cancel();
  }

  function reveal(node) {
    if (node.matches('[data-motion-key]')) {
      const value = Number(node.dataset.motionValue), key = node.dataset.motionKey;
      if (!Number.isFinite(value) || value < 0 || value > 100) return;
      const from = previous.get(key) ?? 0;
      previous.set(key, value);
      if (previous.size > 160) previous.delete(previous.keys().next().value);
      if (value > 0 && value !== from) {
        // Final width exists before JS runs, so a blocked script never hides data.
        // A new node can still animate from the prior snapshot's proportion.
        run(node, [{transform:'scaleX(' + from / value + ')'}, {transform:'scaleX(1)'}],
          {duration:720, easing:'cubic-bezier(.16,1,.3,1)'});
      }
    } else {
      run(node, [{opacity:.45, transform:'translateY(12px)'}, {opacity:1, transform:'none'}],
        {duration:440, easing:'cubic-bezier(.16,1,.3,1)'});
      node.querySelectorAll('.hm-draw').forEach(path => run(path,
        [{strokeDashoffset:1}, {strokeDashoffset:0}], {duration:1000, easing:'ease-out'}));
    }
  }
  function watch(root) {
    const nodes = [...root.querySelectorAll('[data-motion-key], .hm-route')];
    if (root.matches?.('[data-motion-key], .hm-route')) nodes.unshift(root);
    nodes.forEach(node => {
      if (watched.has(node)) return;
      watched.add(node);
      if (observer) observer.observe(node); else reveal(node);
    });
  }
  function start() {
    const host = document.getElementById('view-screener');
    if (!host) return;
    const header = document.querySelector('header.wrap');
    if (header) {
      header.classList.add('hm-masthead');
      if ('IntersectionObserver' in window) new IntersectionObserver(entries => {
        header.classList.toggle('hm-art-visible', entries[0].isIntersecting);
      }).observe(header);
      else header.classList.add('hm-art-visible');
    }
    applyPreference();
    if ('IntersectionObserver' in window) observer = new IntersectionObserver(entries => {
      entries.forEach(entry => { if(entry.isIntersecting) {observer.unobserve(entry.target); reveal(entry.target);} });
    }, {threshold:.1});
    watch(host);
    new MutationObserver(records => records.forEach(record => {
      record.removedNodes.forEach(node => {
        if (node.nodeType !== 1 || !observer) return;
        observer.unobserve(node); node.querySelectorAll('[data-motion-key], .hm-route').forEach(el => observer.unobserve(el));
      });
      record.addedNodes.forEach(node => { if(node.nodeType===1) watch(node); });
    })).observe(host, {childList:true, subtree:true});
    media.addEventListener('change', applyPreference);
    document.addEventListener('visibilitychange', () => {
      document.documentElement.classList.toggle('hm-tab-hidden', document.hidden);
      if (document.hidden) cancel();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();


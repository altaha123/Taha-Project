/* Homepage visuals and motion. Financial labels always show the received
   value; only the corresponding graphic interpolates. No animation library,
   request loop, synthetic price history or external image dependency. */
(function () {
  'use strict';
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  const previous = new Map(), watched = new WeakSet(), active = new Set();
  let enabled = true, button, observer;
  try { enabled = localStorage.getItem('altaha-motion') !== 'off'; } catch (_) {}
  const allowed = () => enabled && !media.matches && !document.hidden;

  function run(node, frames, options) {
    if (!allowed() || !node.animate) return;
    const animation = node.animate(frames, options);
    active.add(animation);
    animation.finished.catch(() => {}).finally(() => active.delete(animation));
  }
  function cancel() { active.forEach(a => a.cancel()); active.clear(); }
  function applyPreference() {
    document.documentElement.dataset.motion = enabled && !media.matches ? 'on' : 'off';
    if (!allowed()) cancel();
    if (button) {
      button.setAttribute('aria-pressed', String(enabled && !media.matches));
      button.textContent = media.matches ? 'Motion off · system' : enabled ? 'Motion on' : 'Motion off';
      button.disabled = media.matches;
    }
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
  const art = {
    research: '<rect x="26" y="14" width="118" height="100" rx="9"/><path d="M44 35h45M44 44h26"/>' +
      '<path class="hm-draw" pathLength="1" d="M44 88l17-18 18 8 20-30"/><circle cx="124" cy="83" r="25"/><path d="m142 101 20 20"/>',
    sectors: '<path d="M28 102h138"/><rect class="hm-illustrated-bar" x="40" y="65" width="22" height="37" rx="3"/>' +
      '<rect class="hm-illustrated-bar" x="77" y="44" width="22" height="58" rx="3"/><rect class="hm-illustrated-bar" x="114" y="23" width="22" height="79" rx="3"/>' +
      '<path class="hm-draw" pathLength="1" d="M40 43 77 25 108 32 143 13"/>',
    portfolio: '<circle cx="88" cy="65" r="43"/><path class="hm-draw" pathLength="1" d="M88 22v43l37 22M88 65 55 94"/>' +
      '<rect x="118" y="80" width="45" height="36" rx="7"/><path d="m129 98 7 7 15-17"/>'
  };
  function route(href, label, description, icon, section) {
    return '<a class="hm-route" href="' + href + '"' + (section ? ' data-home-destination="' + section + '"' : '') + '>' +
      '<svg viewBox="0 0 190 135" aria-hidden="true" focusable="false">' + art[icon] + '</svg>' +
      '<div><h3>' + label + '<span aria-hidden="true"> ↗</span></h3><p>' + description + '</p></div></a>';
  }
  function start() {
    const host = document.getElementById('view-screener');
    if (!host) return;
    const tools = document.createElement('nav');
    tools.className = 'hm-tools'; tools.setAttribute('aria-label', 'Research tools');
    tools.innerHTML = route('#tk', 'Research a stock', 'Understand the score. Inspect the evidence.', 'research', 'search') +
      route('#sb-board', 'Explore sectors', 'See the leaders and the breadth behind each move.', 'sectors', 'sectors') +
      route('index.html?go=portfolio', 'Portfolio Intelligence', 'See how your holdings work together.', 'portfolio', 'portfolio');
    host.appendChild(tools);
    tools.addEventListener('click', e => {
      const a = e.target.closest('[data-home-destination]'); if (!a) return;
      const dest = a.dataset.homeDestination;
      if (dest === 'portfolio' && window.AltahaNav) {
        e.preventDefault(); window.AltahaNav.go('portfolio', 'portfolio', true);
      } else if (dest !== 'portfolio') {
        const target = document.getElementById(dest === 'search' ? 'tk' : 'sb-board');
        if (!target) return;
        e.preventDefault(); target.scrollIntoView({behavior:allowed()?'smooth':'auto', block:'center'});
        if (dest === 'search') target.focus({preventScroll:true});
        else target.querySelector('button')?.focus({preventScroll:true});
      }
    });
    const header = document.querySelector('header.wrap');
    if (header) {
      header.classList.add('hm-masthead');
      button = document.createElement('button'); button.className = 'hm-motion'; button.type = 'button';
      button.title = 'Turn decorative motion and animated market bars on or off';
      button.addEventListener('click', () => {
        enabled = !enabled;
        try { localStorage.setItem('altaha-motion', enabled?'on':'off'); } catch (_) {}
        applyPreference();
      });
      header.appendChild(button);
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

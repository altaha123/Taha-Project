/* Decorative planets represent equal portions of scan progress, not sectors. */
(function () {
  'use strict';
  var pending = { status: 'ready' };
  function mount() {
    var host = document.getElementById('scan-universe');
    if (!host || host.firstChild) return host;
    host.className = 'scan-universe';
    host.innerHTML = '<div class="su-scene" aria-hidden="true"><div class="su-orbit su-orbit-a"></div><div class="su-orbit su-orbit-b"></div><div class="su-orbit su-orbit-c"></div><div class="su-sweep"></div><div class="su-sun"><span>A</span></div>' +
      Array.from({ length: 6 }, function (_, i) { return '<div class="su-planet su-planet-' + i + '"><i></i><span>' + String(i + 1).padStart(2, '0') + '</span></div>'; }).join('') +
      '<span class="su-caption">THE NSE UNIVERSE</span></div><div class="su-copy"><span class="su-eyebrow">DISCOVER / UNIVERSE SCAN</span><h3>Explore a universe<br>of possibilities.</h3><p class="su-status" role="status" aria-live="polite"></p><progress class="su-progress" max="100" value="0" aria-label="Universe scan progress"></progress><p class="su-detail"></p><span class="su-footnote">Planets visualise scan progress. Rankings come from the stock engine.</span></div>';
    return host;
  }
  function update(s) {
    pending = s || pending;
    var host = mount();
    if (!host) return;
    s = pending;
    var running = s.status === 'running', complete = s.status === 'done' && !s.stopped_early;
    var total = Math.max(0, Number(s.total) || 0), done = Math.max(0, Number(s.done) || 0);
    var pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
    host.dataset.state = s.status;
    var results = document.getElementById('scan-results');
    if (results) results.hidden = ['starting', 'running', 'reconnecting'].includes(s.status);
    var title = 'Your next discovery starts here.';
    var detail = 'Choose a horizon below, then start your universe scan.';
    if (s.status === 'starting') { title = 'Connecting to the universe…'; detail = 'Waiting for the engine to confirm your scan.'; }
    if (running) { title = 'Scanning the stock universe…'; detail = total ? done.toLocaleString('en-IN') + ' / ' + total.toLocaleString('en-IN') + ' stocks checked · ' + (Number(s.scored) || 0).toLocaleString('en-IN') + ' scored' : 'Preparing the stock universe. Progress will appear as the engine reports it.'; }
    if (complete) { title = 'Scan complete. Explore your stocks below.'; detail = 'Your ranked shortlist appears below for the selected horizon.'; pct = 100; }
    if (s.stopped_early) { title = 'Scan paused before completion.'; detail = 'Available partial results are shown below. See the scan note for details.'; }
    if (s.status === 'cached') { title = 'Your saved universe is ready.'; detail = 'Loading saved rankings. Refresh the scan below to request a new run.'; }
    if (s.status === 'idle') { title = 'Ready for another discovery.'; detail = s.scanned_at ? 'The scan stopped. Available saved results are shown below.' : 'Start a scan below to build your stock shortlist.'; }
    if (s.status === 'reconnecting') { title = 'Reconnecting to the engine…'; detail = 'Progress is unconfirmed. Waiting for a fresh status update.'; }
    if (s.status === 'error') { title = 'The scan needs your attention.'; detail = 'Read the message below and retry when the engine is available.'; }
    host.querySelector('.su-status').textContent = title;
    host.querySelector('.su-detail').textContent = detail;
    var progress = host.querySelector('progress');
    progress.hidden = !(running || complete || s.status === 'starting');
    if (s.status === 'starting' || (running && !total)) progress.removeAttribute('value');
    else progress.value = pct;
    host.querySelectorAll('.su-planet').forEach(function (planet, i) {
      planet.classList.toggle('is-scanned', (running || complete) && pct >= (i + 1) * 100 / 6);
      planet.classList.toggle('is-scanning', running && pct >= i * 100 / 6 && pct < (i + 1) * 100 / 6);
    });
  }
  window.AltahaUniverse = { update: update };
  document.addEventListener('DOMContentLoaded', function () { update(pending); });
})();

/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Money effects

   WHY THIS EXISTS
   A number that fades in is a form field. A number that rupees arrive into is
   money. This is the small physics layer that carries that difference: gold
   ₹ coins that arc, spin, land and settle, and a sheen that runs across a
   figure the moment it changes.

   IT IS DECORATION, AND IT KNOWS IT
   Every effect here is spawned into a layer that sits above the card and
   takes no clicks, carries `aria-hidden`, and removes itself when it lands.
   Nothing in the page depends on a coin existing. Switch the whole file off —
   reduced motion does exactly that — and every figure, control and reading is
   still there and still correct. That is the test the effects have to pass
   before they are allowed to be fun.

   THE COUNT MEANS SOMETHING
   Coins are not a fixed confetti burst. The number spawned follows the
   ORDER OF MAGNITUDE of the sum, so ₹50,000 gets a few and ₹5 crore gets a
   shower. Sliding from a lakh to a crore should feel like more money, because
   it is, and a person reads that in the spray before they read the digits.

   BUDGET
   Particles are capped and every one removes itself on landing, so a reader
   who drags the slider back and forth for a minute does not accumulate a
   thousand absolutely-positioned spans.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var doc = root.document;
  var MAX_LIVE = 44;                 // absolute ceiling on coins on screen
  var live = 0;

  function still() {
    try {
      return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return true; }
  }

  /* Coins per change, from the size of the sum. Log-scaled: each ten-fold
     step adds roughly three coins, so the spray tracks magnitude rather than
     running out at a lakh or flooding at a crore. */
  function countFor(amount) {
    var v = Number(amount);
    if (!isFinite(v) || v <= 0) return 0;
    return Math.max(3, Math.min(18, Math.round(3 + Math.log(v) / Math.LN10 * 1.7)));
  }

  function layer(host) {
    if (!host) return null;
    var found = host.querySelector(':scope > .mfx-layer');
    if (found) return found;
    var node = doc.createElement('div');
    node.className = 'mfx-layer';
    node.setAttribute('aria-hidden', 'true');
    host.appendChild(node);
    return node;
  }

  function coin(glyph) {
    var node = doc.createElement('span');
    node.className = 'mfx-coin';
    node.textContent = glyph || '₹';
    return node;
  }

  function place(node, box, x, y) {
    node.style.left = (x - box.left) + 'px';
    node.style.top = (y - box.top) + 'px';
  }

  function run(node, host, frames, options) {
    live++;
    host.appendChild(node);
    var player;
    try { player = node.animate(frames, options); }
    catch (e) { node.remove(); live--; return; }
    var done = function () { node.remove(); live--; };
    player.addEventListener ? player.addEventListener('finish', done) : (player.onfinish = done);
    player.oncancel = done;
    // A belt-and-braces sweep: a tab backgrounded mid-flight never fires
    // `finish`, and a coin that never lands is a leak.
    root.setTimeout(function () { if (node.isConnected) done(); },
                    (options.duration || 800) + (options.delay || 0) + 400);
  }

  /* ── Fountain ────────────────────────────────────────────────────────────
     Coins thrown up and out from a point, each on its own arc, spin and
     landing. Used when a figure grows: the money arrives. */
  function fountain(host, origin, options) {
    if (still() || !host || !doc) return 0;
    var box = host.getBoundingClientRect();
    var opts = options || {};
    var total = Math.min(opts.count == null ? 8 : opts.count, MAX_LIVE - live);
    if (total <= 0) return 0;
    var rise = opts.rise == null ? 120 : opts.rise;

    for (var i = 0; i < total; i++) {
      var node = coin(opts.glyph);
      place(node, box, origin.x, origin.y);
      var spread = (Math.random() - 0.5) * (opts.spread == null ? 190 : opts.spread);
      var up = rise * (0.62 + Math.random() * 0.75);
      var spin = (Math.random() > .5 ? 1 : -1) * (180 + Math.random() * 360);
      var size = 0.68 + Math.random() * 0.5;
      run(node, host, [
        { transform: 'translate(-50%,-50%) scale(' + (size * .35) + ') rotate(0deg)', opacity: 0 },
        { transform: 'translate(calc(-50% + ' + (spread * .45) + 'px), calc(-50% - ' + up + 'px)) ' +
                     'scale(' + size + ') rotate(' + (spin * .5) + 'deg)', opacity: 1, offset: .38 },
        { transform: 'translate(calc(-50% + ' + spread + 'px), calc(-50% + ' + (up * .55) + 'px)) ' +
                     'scale(' + (size * .8) + ') rotate(' + spin + 'deg)', opacity: 0 }
      ], {
        duration: 760 + Math.random() * 520,
        delay: i * 34,
        easing: 'cubic-bezier(.25,.5,.35,1)',
        fill: 'backwards'
      });
    }
    return total;
  }

  /* ── Drain ───────────────────────────────────────────────────────────────
     The opposite gesture for a figure that shrinks: coins fall away rather
     than arriving. Fewer, heavier, no spin — money leaving is not festive. */
  function drain(host, origin, options) {
    if (still() || !host || !doc) return 0;
    var box = host.getBoundingClientRect();
    var opts = options || {};
    var total = Math.min(opts.count == null ? 4 : opts.count, MAX_LIVE - live);
    if (total <= 0) return 0;

    for (var i = 0; i < total; i++) {
      var node = coin(opts.glyph);
      place(node, box, origin.x, origin.y);
      var drift = (Math.random() - 0.5) * 90;
      run(node, host, [
        { transform: 'translate(-50%,-50%) scale(.9)', opacity: .95 },
        { transform: 'translate(calc(-50% + ' + drift + 'px), calc(-50% + 150px)) scale(.55)', opacity: 0 }
      ], { duration: 520 + Math.random() * 260, delay: i * 45, easing: 'cubic-bezier(.4,0,.9,.5)',
           fill: 'backwards' });
    }
    return total;
  }

  /* ── Transfer ────────────────────────────────────────────────────────────
     Coins flying from one point into several targets. This is the gesture
     that carries the meaning at the end of the flow: the sum does not just
     appear as three cards, it is DIVIDED between them, and a reader watches
     it go. The share of coins each target receives is its share of the
     money. */
  function transfer(host, origin, targets, options) {
    if (still() || !host || !doc || !targets || !targets.length) return 0;
    var box = host.getBoundingClientRect();
    var opts = options || {};
    var budget = Math.min(opts.count == null ? 18 : opts.count, MAX_LIVE - live);
    if (budget <= 0) return 0;

    var weights = targets.map(function (t) { return Math.max(0, Number(t.share) || 0); });
    var sum = weights.reduce(function (a, b) { return a + b; }, 0) || targets.length;
    var sent = 0;

    targets.forEach(function (target, index) {
      var share = Math.max(1, Math.round(budget * (weights[index] || 1) / sum));
      for (var i = 0; i < share && sent < budget; i++, sent++) {
        var node = coin(opts.glyph);
        place(node, box, origin.x, origin.y);
        var dx = target.x - origin.x + (Math.random() - .5) * 46;
        var dy = target.y - origin.y + (Math.random() - .5) * 26;
        var lift = 40 + Math.random() * 70;
        var spin = (Math.random() > .5 ? 1 : -1) * (160 + Math.random() * 260);
        run(node, host, [
          { transform: 'translate(-50%,-50%) scale(.4)', opacity: 0 },
          { transform: 'translate(calc(-50% + ' + (dx * .45) + 'px), calc(-50% + ' + (dy * .4 - lift) + 'px)) ' +
                       'scale(1) rotate(' + (spin * .6) + 'deg)', opacity: 1, offset: .42 },
          { transform: 'translate(calc(-50% + ' + dx + 'px), calc(-50% + ' + dy + 'px)) ' +
                       'scale(.5) rotate(' + spin + 'deg)', opacity: 0 }
        ], { duration: 820 + Math.random() * 300,
             delay: (opts.delay || 0) + index * 90 + i * 52,
             easing: 'cubic-bezier(.3,.2,.3,1)', fill: 'backwards' });
      }
    });
    return sent;
  }

  /* ── Sheen ───────────────────────────────────────────────────────────────
     A light running across a figure the instant it changes. Cheap, and it is
     what makes a changed number look struck rather than swapped. */
  function sheen(node) {
    if (still() || !node) return;
    node.classList.remove('mfx-sheen');
    void node.offsetWidth;                       // restart the keyframes
    node.classList.add('mfx-sheen');
    root.setTimeout(function () { node.classList.remove('mfx-sheen'); }, 900);
  }

  /* The centre of an element, in viewport coordinates. */
  function centre(node) {
    if (!node || !node.getBoundingClientRect) return { x: 0, y: 0 };
    var r = node.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  /* Where the slider handle actually is, so coins come off the thumb rather
     than off the middle of the track. */
  function thumb(input) {
    if (!input || !input.getBoundingClientRect) return { x: 0, y: 0 };
    var r = input.getBoundingClientRect();
    var min = Number(input.min) || 0, max = Number(input.max) || 100;
    var value = Number(input.value) || 0;
    var t = max > min ? (value - min) / (max - min) : 0;
    var pad = 13;                                // half the thumb, so it stays on the track
    return { x: r.left + pad + (r.width - pad * 2) * t, y: r.top + r.height / 2 };
  }

  var api = { fountain: fountain, drain: drain, transfer: transfer, sheen: sheen,
              layer: layer, centre: centre, thumb: thumb, countFor: countFor,
              still: still, MAX_LIVE: MAX_LIVE,
              liveCount: function () { return live; } };

  root.AltahaMoneyFx = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);

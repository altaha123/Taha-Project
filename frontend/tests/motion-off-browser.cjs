/* Nothing on the opening screen is invisible, under any motion setting.
 *
 * This exists because of a bug that shipped. premium.css reveals the
 * masthead's children with `.hero-in > * { animation: heroIn ... both }`,
 * and home-motion.css stops motion with
 *
 *     html[data-motion="off"] .hm-masthead * { animation-play-state:paused }
 *
 * Pausing a loop is right. Pausing a `both`-filled reveal holds it at its
 * `from` state, which is opacity:0 — so with motion off the entire hero,
 * and before it the entire masthead, rendered as blank paper. The Motion
 * toggle sits in the same header, so it disappeared too and the setting
 * could not be undone from the page it had emptied.
 *
 * Nothing threw, nothing logged, and every element reported the right
 * computed opacity: the zero was on an ancestor. So this walks the header,
 * multiplies opacity down the tree the way the compositor does, and fails
 * on any element that has text and cannot be seen.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8'
      : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

// The three states a reader can actually be in. The middle one is the bug:
// the site's own toggle, remembered from a previous visit.
const SETTINGS = [
  { name: 'motion on',      stored: null,  reduced: 'no-preference' },
  { name: 'motion off',     stored: 'off', reduced: 'no-preference' },
  { name: 'reduced motion', stored: null,  reduced: 'reduce' },
  // The case the stylesheet cannot name. Both blank screens that shipped
  // came from a pause rule written somewhere else, so this stops guessing
  // which rule and pauses EVERYTHING, then checks the page is still
  // readable. home-hero.js's hh-played timer is what has to save it.
  { name: 'everything paused', stored: null, reduced: 'no-preference', paused: true }
];

(async () => {
  await new Promise(r => server.listen(8767, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  for (const setting of SETTINGS) {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({
        viewport: { width, height: 900 }, hasTouch: true, reducedMotion: setting.reduced
      });
      await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
      if (setting.stored) {
        await context.addInitScript(v => localStorage.setItem('altaha-motion', v), setting.stored);
      }
      if (setting.paused) {
        await context.addInitScript(() => {
          const kill = () => {
            const style = document.createElement('style');
            // No class, no id: the weakest selector there is, so this only
            // passes if the backstop stops the animation rather than
            // out-specifying the pause.
            style.textContent = '*,*::before,*::after{animation-play-state:paused !important}';
            document.head.appendChild(style);
          };
          if (document.head) kill();
          else document.addEventListener('DOMContentLoaded', kill);
        });
      }
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e.stack)));
      // No network: a cold free instance is the normal first visit, and the
      // hero must not depend on the engine answering.
      await context.route('**/*', r =>
        r.request().url().includes('127.0.0.1') ? r.continue() : r.abort());
      await page.goto('http://127.0.0.1:8767/', { waitUntil: 'domcontentloaded' });
      await page.locator('.hh-head').waitFor();
      // Past the hh-played timer, which is the last thing that can rescue a
      // reveal somebody else has frozen.
      await page.waitForTimeout(4200);

      const hidden = await page.evaluate(() => {
        const out = new Set();
        document.querySelectorAll('header.wrap, header.wrap *').forEach(node => {
          if (node.id === 'skin-art' || node.closest('#skin-art')) return;
          if (node.closest('[aria-hidden="true"]')) return;      // decoration
          const style = getComputedStyle(node);
          if (style.display === 'none' || style.visibility === 'hidden') return;
          const text = (node.textContent || '').trim();
          if (!text) return;
          let opacity = 1, walk = node;
          while (walk && walk !== document.documentElement) {
            opacity *= parseFloat(getComputedStyle(walk).opacity);
            walk = walk.parentElement;
          }
          if (opacity < 0.05) out.add(`${node.tagName}.${node.className} — "${text.slice(0, 40)}"`);
        });
        return [...out];
      });
      assert.deepEqual(hidden, [], `${setting.name} @ ${width}px: masthead content is invisible`);

      // The promise itself, the way in, and the control for this very
      // setting all have to be on the screen whatever the setting is.
      for (const sel of ['.hh-head', '.hh-sub', '.hh-cta .hh-btn', '.hm-motion']) {
        assert.ok(await page.locator(sel).first().isVisible(), `${setting.name} @ ${width}px: ${sel} not visible`);
      }
      // Deliberately NOT the exact wording. This test asks whether the
      // opening screen can be SEEN under each motion setting; pinning the
      // headline's copy here meant a marketing edit registered as a motion
      // regression, which is what happened when the hero was reworded. What
      // matters is that the headline has words in it and they are on screen.
      const headline = (await page.locator('.hh-head').innerText()).trim();
      assert.ok(headline.length > 8,
        `${setting.name} @ ${width}px: the headline is empty — "${headline}"`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `${setting.name} @ ${width}px: horizontal overflow`);

      await context.close();
    }
  }

  const relevant = errors.filter(e => /home-hero\.js|home-motion\.js|home\.js/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close(); server.close();
  console.log('Opening screen is visible under motion on, motion off and reduced motion');
})().catch(e => { console.error(e); server.close(); process.exit(1); });

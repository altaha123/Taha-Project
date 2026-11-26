/* Run with Playwright and lightweight-charts@4.1.3 on NODE_PATH:
     node frontend/tests/charts-browser.cjs

   The Charts tab, driven the way a reader drives it. Every failure a chart
   can have is silent: a tool that never commits its shape, a pane that
   hides the drawings above it, a share link that lands on the wrong page,
   a phone tap that pans instead of selecting. So each is done here, on the
   real charting library, with deterministic candles.

   - every drawing tool in every flyout is picked and placed
   - indicators open in panes, chart types and timeframes switch
   - drawings survive a pane being added (the plot used to measure 0 wide)
   - replay steps one bar; full screen, the object tree, the context menu
   - drawings saved by the earlier workspace load; undo, redo, colour, drag,
     alert, copy, paste, clone, delete, eraser; compare a symbol
   - a shared chart link (?q=SYM&go=charts&range=1W) stays on the chart
   - a phone: tap to draw, tap to select, no sideways scroll
   and no page errors anywhere. */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const out = path.resolve(root, '..', 'test-results', 'charts');
fs.mkdirSync(out, { recursive: true });
/* The package's exports map hides dist/, so find the package and read the
   standalone build beside it. */
const LWC = fs.readFileSync(path.join(path.dirname(require.resolve('lightweight-charts/package.json')), 'dist', 'lightweight-charts.standalone.production.js'), 'utf8');
const TYPES = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png', '.ico': 'image/x-icon', '.webp': 'image/webp' };

/* Weekday daily candles ending in Nov 2026, or bars of `step` seconds. */
function candles(n, step, seed) {
  let s = seed || 7;
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const out2 = []; let px = 1300, t = Date.UTC(2026, 10, 20) / 1000;
  while (out2.length < n) {
    const d = new Date(t * 1000).getUTCDay();
    if (step >= 86400 && (d === 0 || d === 6)) { t -= 86400; continue; }
    const o = px, c = Math.max(50, o * (1 + (rnd() - 0.49) * 0.03)), h = Math.max(o, c) * (1 + rnd() * 0.008), l = Math.min(o, c) * (1 - rnd() * 0.008);
    out2.push([t, +o.toFixed(2), +h.toFixed(2), +l.toFixed(2), +c.toFixed(2), null, null, null, null, Math.round(2e6 + rnd() * 9e6)]);
    px = c; t -= step >= 86400 ? 86400 : step;
  }
  return out2.reverse();
}
const STEP = { '1W': 604800 };

const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(root, url === '/' ? '/index.html' : url);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', TYPES[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});

async function open(browser, url, opts) {
  const context = await browser.newContext(Object.assign({ viewport: { width: 1440, height: 900 } }, opts || {}));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === 'localhost') return route.continue();
    if (/lightweight-charts/.test(u.href)) return route.fulfill({ contentType: 'text/javascript', body: LWC });
    if (u.pathname === '/chart') {
      const r = u.searchParams.get('range') || '1D', tk = u.searchParams.get('ticker') || 'X';
      if (/^(1m|5m|15m|1H|4H)$/.test(r)) return route.fulfill({ status: 503, json: { detail: 'Intraday charts need the Dhan data feed. Longer timeframes are available without it.' } });
      const c = candles(r === '1W' ? 250 : 600, STEP[r] || 86400, tk.length * 13 + 7), last = c[c.length - 1][4];
      return route.fulfill({ json: { ticker: tk, range: r, live: false, candles: c, last, prev_close: last * 1.006,
        levels: { supports: [{ level: last * 0.95, strength: 80, touches: 5 }], resistances: [{ level: last * 1.06, strength: 75, touches: 4 }] } } });
    }
    if (u.pathname === '/universe') return route.fulfill({ json: { rows: [{ s: 'RELIANCE', n: 'Reliance Industries' }, { s: 'TCS', n: 'Tata Consultancy Services' }, { s: 'INFY', n: 'Infosys' }], count: 3 } });
    if (u.pathname.indexOf('/stream') === 0) return route.abort();
    if (/fonts\.g|googleapis|gstatic/.test(u.hostname)) return route.abort();
    return route.fulfill({ json: { available: false, rows: [], items: [], patterns: [] } });
  });
  await page.goto(url);
  return { context, page, errors };
}
const state = page => page.evaluate(() => window.AltahaCharts.state());
/* Loaded means the candles are on screen, not just that the timeframe was
   chosen: the loading veil is down. */
const ready = (page, sym) => page.waitForFunction(s => window.AltahaCharts && AltahaCharts.state().bars > 0 &&
  (!s || AltahaCharts.state().sym === s) && !document.getElementById('cw-msg').classList.contains('on'), sym || null, { timeout: 20000 });
/* A timeframe, chosen the way a reader chooses it: from the row when the
   workspace is wide, from the folded row's menu when it is not. */
async function pickTf(page, k) {
  const b = page.locator(`#cw-tfs button[data-r="${k}"]`);
  if (await b.isVisible()) await b.click();
  else {
    await page.click('#cw-tfs button.on');
    await page.locator('.cw-pop-tf .cw-pop-i').filter({ hasText: new RegExp('^' + k + '$') }).click();
  }
}
const LABELS = { trend: 'Trend line', ray: 'Ray', xline: 'Extended line', infoline: 'Info line', arrowline: 'Arrow', angle: 'Trend angle', hline: 'Horizontal line', hray: 'Horizontal ray', vline: 'Vertical line', cross: 'Cross line', chan: 'Parallel channel', regchan: 'Regression trend', pitchfork: 'Pitchfork', fib: 'Fib retracement', fibext: 'Trend-based Fib extension', fibtime: 'Fib time zones', fibfan: 'Fib speed fan', gannfan: 'Gann fan', gannbox: 'Gann box', xabcd: 'XABCD pattern', abcd: 'ABCD pattern', trianglep: 'Triangle pattern', elliott5: 'Elliott impulse wave', elliott3: 'Elliott correction', hs: 'Head and shoulders', pos: 'Long position', short: 'Short position', ruler: 'Date and price range', prange: 'Price range', drange: 'Date range', avwap: 'Anchored VWAP', vprofile: 'Fixed range volume profile', rect: 'Rectangle', ellipse: 'Ellipse', triangle: 'Triangle', path: 'Path', brush: 'Brush', hilite: 'Highlighter', text: 'Text', callout: 'Callout', pricelabel: 'Price label', arrowup: 'Arrow mark up', arrowdown: 'Arrow mark down', flag: 'Flag' };
const POINTS = { trend: 2, ray: 2, xline: 2, infoline: 2, arrowline: 2, angle: 2, hline: 1, hray: 1, vline: 1, cross: 1, chan: 3, regchan: 2, pitchfork: 3, fib: 2, fibext: 3, fibtime: 2, fibfan: 2, gannfan: 2, gannbox: 2, xabcd: 5, abcd: 4, trianglep: 4, elliott5: 6, elliott3: 4, hs: 7, pos: 2, short: 2, ruler: 2, prange: 2, drange: 2, avwap: 1, vprofile: 2, rect: 2, ellipse: 2, triangle: 3, path: 3, text: 1, callout: 2, pricelabel: 1, arrowup: 1, arrowdown: 1, flag: 1 };

(async () => {
  await new Promise(r => server.listen(0, r));
  const base = 'http://localhost:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    /* ── Desktop: every tool, panes, types, replay, full screen ── */
    {
      const { context, page, errors } = await open(browser, base + '/#research/charts');
      await ready(page);
      const tools = await page.evaluate(() => AltahaCharts.tools());
      assert.deepEqual(tools.slice().sort(), Object.keys(LABELS).sort(), 'every tool is tested');
      let box = await page.locator('#cw-price').boundingBox();
      const P = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
      const groups = await page.$$eval('#cw-rail .cw-grp', els => els.map(e => e.dataset.g));
      let placed = 0;
      for (const t of tools) {
        let picked = false;
        for (const g of groups) {
          await page.click(`#cw-rail .cw-grp[data-g="${g}"] .cw-more`);
          const labels = await page.$$eval('.cw-fly .cw-pop-i span', e => e.map(x => x.textContent));
          const i = labels.indexOf(LABELS[t]);
          if (i >= 0) { await page.locator('.cw-fly .cw-pop-i').nth(i).click(); picked = true; break; }
          await page.keyboard.press('Escape');
        }
        assert.ok(picked, t + ' is in a flyout');
        assert.equal((await state(page)).tool, t);
        const ys = [0.6, 0.3, 0.5, 0.25, 0.55, 0.2, 0.45];
        if (t === 'brush' || t === 'hilite') {
          const a = P(0.3, 0.5); await page.mouse.move(a.x, a.y); await page.mouse.down();
          for (let i = 1; i < 10; i++) { const b = P(0.3 + i * 0.02, 0.5 - Math.sin(i) * 0.05); await page.mouse.move(b.x, b.y); }
          await page.mouse.up();
        } else {
          for (let i = 0; i < POINTS[t]; i++) { const p = P(0.25 + i * 0.08, ys[i % ys.length]); await page.mouse.click(p.x, p.y); }
          if (t === 'path') await page.keyboard.press('Enter');
          if (t === 'text' || t === 'callout') { await page.keyboard.type('Breakout'); await page.keyboard.press('Enter'); }
        }
        placed++;
        assert.equal((await state(page)).drawings, placed, t + ' commits its drawing');
      }
      const drawn = await page.evaluate(() => AltahaCharts.drawings());
      assert.equal(drawn.find(d => d.type === 'text').text, 'Breakout', 'text typed in place, no prompt()');
      await page.locator('#cw').screenshot({ path: path.join(out, 'every-tool.png') });

      /* Panes. Drawings must still be painted once the price chart's own
         time axis is hidden. */
      await page.keyboard.press('Escape');
      await page.keyboard.press('/');
      for (const q of ['Relative strength index', 'MACD', 'Bollinger Bands', 'Ichimoku cloud', 'Supertrend']) {
        await page.fill('.cw-ind-q', q); await page.keyboard.press('Enter');
      }
      await page.locator('.cw-modal .cw-x').click();
      let s = await state(page);
      assert.equal(s.panes, 2, 'RSI and MACD in panes of their own');
      const painted = await page.evaluate(() => {
        const c = document.getElementById('cw-cv'), x = c.getContext('2d');
        const d = x.getImageData(0, 0, Math.floor(c.width * 0.8), c.height).data;
        let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++;
        return n;
      });
      assert.ok(painted > 5000, 'drawings still painted over the price chart with panes below: ' + painted);
      await page.locator('#cw').screenshot({ path: path.join(out, 'panes.png') });

      for (const ty of ['Hollow candles', 'Heikin Ashi', 'Bars', 'Line', 'Step line', 'Area', 'Baseline', 'Candles']) {
        await page.click('#cw-type'); await page.locator('.cw-pop-i', { hasText: ty }).first().click();
      }
      for (const tf of ['1W', '1M', '1D']) {
        await pickTf(page, tf);
        await page.waitForFunction(tf => AltahaCharts.state().tf === tf && AltahaCharts.state().bars > 0, tf);
      }
      assert.equal((await state(page)).type, 'candles');
      /* An intraday frame without the live feed says so and offers daily. */
      await pickTf(page, '5m');
      await page.locator('#cw-msg [data-fallback]').click();
      await page.waitForFunction(() => AltahaCharts.state().tf === '1D');

      box = await page.locator('#cw-price').boundingBox();
      await page.click('[data-a="replay"]');
      const rp = P(0.5, 0.5); await page.mouse.click(rp.x, rp.y);
      s = await state(page); assert.ok(s.replay, 'replay starts at the tapped bar');
      await page.click('[data-rp="step"]');
      assert.equal((await state(page)).bars, s.bars + 1, 'step adds one bar');
      await page.click('[data-rp="exit"]');
      assert.equal((await state(page)).replay, false);

      await page.click('[data-a="side"]');
      assert.equal(await page.locator('#cw-side .cw-ob').count(), placed + 7, 'object tree lists every drawing and indicator');
      box = await page.locator('#cw-price').boundingBox();
      const cm = P(0.6, 0.1); await page.mouse.click(cm.x, cm.y, { button: 'right' });
      assert.ok(await page.locator('.cw-ctx').isVisible(), 'context menu');
      await page.keyboard.press('Escape');
      await page.click('#cw-full');
      await page.waitForFunction(() => AltahaCharts.state().full);
      await page.screenshot({ path: path.join(out, 'full-screen.png') });
      assert.deepEqual(errors, [], 'desktop: no page errors');
      await context.close();
    }

    /* ── A trend line on a short monthly chart with a pane, the way it was
       reported not to work: the first click lands on the legend, and the
       clicks wobble as a touchpad's do. ── */
    {
      const { context, page, errors } = await open(browser, base + '/#research/charts');
      await ready(page);
      await pickTf(page, '1M');
      await ready(page);
      await page.keyboard.press('/');
      await page.fill('.cw-ind-q', 'Chaikin money flow'); await page.keyboard.press('Enter');
      await page.locator('.cw-modal .cw-x').click();
      await page.click('#cw-rail .cw-grp[data-g="lines"] .cw-t');
      const row = await page.locator('#cw-legend .cw-lg-row[data-u]').first().boundingBox();
      const a = { x: row.x + row.width - 8, y: row.y + row.height / 2 };
      await page.mouse.move(a.x, a.y); await page.mouse.down(); await page.mouse.move(a.x + 5, a.y + 4); await page.mouse.up();
      const marked = await page.evaluate(() => {
        const c = document.getElementById('cw-cv'), r = c.getBoundingClientRect();
        return { n: AltahaCharts.state().drawings };
      });
      assert.equal(marked.n, 0, 'a wobbly first click does not end the line');
      const box = await page.locator('#cw-price').boundingBox();
      for (let i = 1; i <= 6; i++) await page.mouse.move(a.x + i * 40, a.y + i * 30);
      await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.6); await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.7 + 4, box.y + box.height * 0.6 - 3); await page.mouse.up();
      assert.equal((await state(page)).drawings, 1, 'the line is drawn, starting on the legend');
      assert.equal((await state(page)).studies.length, 3, 'no indicator was removed by a click meant for the chart');
      assert.deepEqual(errors, [], 'short monthly chart: no page errors');
      await context.close();
    }

    /* ── Never a blank chart: the watchdog stays quiet on a healthy chart,
       and a chart whose library element is torn out is rebuilt, drawings
       kept. ── */
    {
      const { context, page, errors } = await open(browser, base + '/#research/charts');
      await ready(page);
      await page.keyboard.press('Alt+KeyH');
      const box = await page.locator('#cw-price').boundingBox();
      await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.4);
      await page.waitForTimeout(3600);
      assert.equal(await page.evaluate(() => AltahaCharts.health()), null, 'a healthy chart reads healthy');
      assert.equal(await page.isVisible('.cw-toast.on'), false, 'and nothing was redrawn behind the reader');
      await page.evaluate(() => { const t = document.querySelector('#cw-price table'); t.closest('div').remove(); });
      await page.waitForFunction(() => AltahaCharts.health() === null && document.querySelector('#cw-price table'), null, { timeout: 8000 });
      assert.equal((await state(page)).drawings, 1, 'drawings survive the rebuild');
      assert.match(await page.locator('.cw-toast').innerText(), /redrawn/);
      assert.deepEqual(errors, [], 'watchdog: no page errors');
      await context.close();
    }

    /* ── A share link, old drawings, and editing ── */
    {
      const { context, page, errors } = await open(browser, base + '/?q=TCS&go=charts&range=1W', {});
      await page.evaluate(() => {
        const t = Date.UTC(2026, 9, 1) / 1000;
        localStorage.setItem('altaha.charts.v1.INFY', JSON.stringify([
          { id: 'a', type: 'trend', pts: [{ t, p: 1200 }, { t: t + 86400 * 30, p: 1300 }], color: '#B08D2E', width: 2 },
          { id: 'b', type: 'fib', pts: [{ t, p: 1200 }, { t: t + 86400 * 30, p: 1300 }] },
          { id: 'c', type: 'pos', pts: [{ t, p: 1250 }, { t: t + 86400 * 20, p: 1220 }, { t: t + 86400 * 20, p: 1310 }] },
          { id: 'd', type: 'brush', pts: [{ t, p: 1200 }, { t: t + 86400, p: 1210 }, { t: t + 172800, p: 1205 }] }]));
      });
      await ready(page, 'TCS');
      await page.waitForTimeout(3000);
      assert.ok(/[?&]go=charts/.test(page.url()), 'a shared chart link stays on the chart, not the stock page: ' + page.url());
      let s = await state(page);
      assert.equal(s.tf, '1W', 'the link chose the timeframe');
      assert.equal(await page.evaluate(() => window.AltahaChartTap.ready()), true, 'the patterns overlay has the chart');
      assert.equal(await page.evaluate(() => document.querySelector('#cw-tfs button.on').dataset.api), '1W');

      await page.fill('#cw-in', 'inf');
      await page.locator('#cw-sug .cw-pop-i', { hasText: 'INFY' }).dispatchEvent('pointerdown');
      await ready(page, 'INFY');
      assert.equal((await state(page)).drawings, 4, 'drawings saved by the earlier workspace load');
      await pickTf(page, '1D');
      await page.waitForFunction(() => AltahaCharts.state().tf === '1D');
      await ready(page, 'INFY');
      await page.waitForTimeout(200);

      const box = await page.locator('#cw-price').boundingBox();
      const x = box.x + box.width * 0.4, y = box.y + box.height * 0.3;
      await page.keyboard.press('Alt+KeyH');
      await page.mouse.click(box.x + box.width * 0.5, y);
      assert.equal((await state(page)).drawings, 5);
      await page.keyboard.press('Control+z'); assert.equal((await state(page)).drawings, 4, 'undo');
      await page.keyboard.press('Control+y'); assert.equal((await state(page)).drawings, 5, 'redo');
      await page.mouse.click(x, y);
      assert.ok(await page.isVisible('#cw-insp.on'), 'a click selects the line');
      await page.click('#cw-insp [data-x="color"]'); await page.locator('.cw-pop-colors .cw-sw').nth(9).click();
      /* A swatch is a theme token, not a hex: the drawing keeps the token's
         name, so it is the right colour in both themes (charts-workspace.js). */
      assert.equal(await page.evaluate(() => AltahaCharts.drawings().slice(-1)[0].color), '--info', 'recoloured');
      const before = await page.evaluate(() => AltahaCharts.drawings().slice(-1)[0].pts[0].p);
      await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x, y + 20); await page.mouse.move(x, y + 40); await page.mouse.up();
      assert.ok(await page.evaluate(() => AltahaCharts.drawings().slice(-1)[0].pts[0].p) < before, 'dragged lower');
      await page.click('#cw-insp [data-x="alert"]');
      assert.equal(await page.evaluate(() => AltahaCharts.drawings().slice(-1)[0].alert), true, 'alert on');
      await page.keyboard.press('Control+c'); await page.keyboard.press('Control+v');
      assert.equal((await state(page)).drawings, 6, 'paste');
      await page.keyboard.press('Control+d'); assert.equal((await state(page)).drawings, 7, 'clone');
      await page.keyboard.press('Delete'); assert.equal((await state(page)).drawings, 6, 'delete');
      await page.click('#cw-rail [data-t="erase"]');
      await page.mouse.click(x, y + 40);
      assert.equal((await state(page)).drawings, 5, 'the eraser removes what it is tapped on');
      await page.keyboard.press('Escape');

      await page.click('[data-a="cmp"]'); await page.keyboard.type('TCS'); await page.keyboard.press('Enter');
      await page.waitForFunction(() => AltahaCharts.state().compares.length === 1);
      assert.ok(await page.locator('.cw-foot [data-scale="pct"].on').count(), 'percent scale while comparing');
      await page.locator('#cw').screenshot({ path: path.join(out, 'compare.png') });
      assert.deepEqual(errors, [], 'editing: no page errors');
      await context.close();
    }

    /* ── A phone ── */
    {
      const { context, page, errors } = await open(browser, base + '/#research/charts', { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
      await ready(page);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no sideways scroll on a phone');
      const box = await page.locator('#cw-price').boundingBox();
      const P = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
      await page.locator('#cw-rail .cw-grp[data-g="lines"] .cw-t').tap();
      const a = P(0.2, 0.4), b = P(0.6, 0.6);
      await page.touchscreen.tap(a.x, a.y); await page.touchscreen.tap(b.x, b.y);
      assert.equal((await state(page)).drawings, 1, 'two taps draw a trend line');
      const e = P(0.85, 0.15); await page.touchscreen.tap(e.x, e.y);
      assert.equal(await page.isVisible('#cw-insp.on'), false, 'a tap on empty chart deselects');
      const m = P(0.4, 0.5); await page.touchscreen.tap(m.x, m.y);
      assert.equal(await page.isVisible('#cw-insp.on'), true, 'a tap on the line selects it, with no hover to help');
      await page.locator('#cw-full').tap();
      await page.waitForFunction(() => AltahaCharts.state().full);
      await page.screenshot({ path: path.join(out, 'phone-full-screen.png') });
      assert.deepEqual(errors, [], 'phone: no page errors');
      await context.close();
    }
    console.log('charts: ' + Object.keys(LABELS).length + ' drawing tools placed; panes, types, replay, full screen, editing, share link and phone hold');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });

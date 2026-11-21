/* The pictures a store listing needs, taken from the app itself.
 *
 *     npm run build && node scripts/store-screenshots.cjs
 *
 * Writes into mobile/store/:
 *   icon-512.png            the Play Store's own copy of the icon
 *   feature-graphic.png     the 1024x500 banner at the top of a Play listing
 *   phone-1..5.png          1080x2160 screenshots. Play refuses a screenshot
 *                           more than twice as tall as it is wide, which is
 *                           every modern phone's own screenshot.
 *
 * The pages are the bundle the apps ship (mobile/www) with the phone faked
 * (tests/harness.cjs), and the figures on them are whatever the live API
 * says at the moment this runs, so run it on a trading day for a full page.
 * Look at every picture before uploading it: a store listing is an
 * advertisement, and what it shows the app doing, the app is promising to do.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { serve, fakePhone } = require('../tests/harness.cjs');

const OUT = path.resolve(__dirname, '..', 'store');
const ASSETS = path.resolve(__dirname, '..', 'assets');

const SHOTS = [
  { name: 'phone-1', url: '/', wait: '.sh-chrome', hide: true },
  { name: 'phone-2', url: '/stock.html?ticker=TCS', wait: '.stk-stage, .sh-chrome' },
  { name: 'phone-3', url: '/#research/query', wait: '.sh-chrome' },
  { name: 'phone-4', url: '/#discover/screener', wait: '.sh-chrome' },
  { name: 'phone-5', url: '/#portfolio', wait: '.sh-chrome' },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const { server, origin } = await serve();
  const browser = await chromium.launch();

  // 400 x 800 at 2.7 is 1080 x 2160: exactly two to one.
  const phone = await browser.newContext({
    viewport: { width: 400, height: 800 }, deviceScaleFactor: 2.7, isMobile: true, hasTouch: true,
    colorScheme: 'light',
  });
  await phone.addInitScript(fakePhone);
  // The "new here" strip is for a first visit, not for a shop window.
  await phone.addInitScript(() => { try { localStorage.setItem('altaha-start-hidden-v1', '1'); } catch (e) {} });
  const page = await phone.newPage();
  const cdp = await phone.newCDPSession(page);
  await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: 0, bottom: 0 } });
  for (const shot of SHOTS) {
    await page.goto(origin + shot.url, { waitUntil: 'load' });
    await page.waitForSelector(shot.wait, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(9000);                 // the API, and the page settling
    await page.screenshot({ path: path.join(OUT, shot.name + '.png') });
    console.log('  ' + shot.name + '.png  ' + shot.url);
  }
  await phone.close();

  // The banner: the mark, the name, and one line that is true.
  const icon = fs.readFileSync(path.join(ASSETS, 'icon-only.png')).toString('base64');
  const fonts = origin + '/vendor/fonts/fonts.css';     // from the server: a blank page may not read files
  const banner = await browser.newContext({ viewport: { width: 1024, height: 500 }, deviceScaleFactor: 1 });
  const b = await banner.newPage();
  await b.goto(origin + '/app-build.json');             // so the fonts are the page's own, not another site's
  await b.setContent(`<!doctype html><link rel="stylesheet" href="${fonts}">
    <style>
      body{margin:0;width:1024px;height:500px;background:#FBFAF7;color:#16130E;display:flex;align-items:center;
           font-family:Inter,system-ui,sans-serif;overflow:hidden}
      img{width:300px;height:300px;margin:0 28px 0 64px;flex:none}
      h1{font:400 76px/1 'Instrument Serif',Georgia,serif;margin:0 0 18px;letter-spacing:-.5px}
      h1 i{color:#8A6D1E}
      p{font-size:27px;line-height:1.35;margin:0;color:#4A443A;max-width:560px}
      .rule{position:absolute;left:0;right:0;bottom:0;height:10px;background:linear-gradient(90deg,#8A6D1E,#D9BC6A,#B08D2E)}
    </style>
    <img src="data:image/png;base64,${icon}" alt="">
    <div><h1>Altaha <i>Screener</i></h1><p>A 0 to 100 score for any Indian stock, with every calculation shown.</p></div>
    <div class="rule"></div>`);
  await b.evaluate(() => Promise.all([document.fonts.load("76px 'Instrument Serif'"),
    document.fonts.load("italic 76px 'Instrument Serif'"), document.fonts.load('27px Inter')]));
  if (!(await b.evaluate(() => document.fonts.check("76px 'Instrument Serif'")))) {
    throw new Error('the banner would be drawn in a fallback font');
  }
  await b.waitForTimeout(300);
  await b.screenshot({ path: path.join(OUT, 'feature-graphic.png') });
  console.log('  feature-graphic.png');

  // The icon, square and full to the edge: Play rounds the corners itself.
  const sq = await browser.newContext({ viewport: { width: 512, height: 512 }, deviceScaleFactor: 1 });
  const s = await sq.newPage();
  await s.setContent(`<body style="margin:0"><img src="data:image/png;base64,${icon}" style="width:512px;height:512px;display:block">`);
  await s.screenshot({ path: path.join(OUT, 'icon-512.png') });
  console.log('  icon-512.png');

  await browser.close();
  server.close();
})().catch((e) => { console.error(e); process.exit(1); });

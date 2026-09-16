/* Sign-in UI with mocked delivery; never sends real emails. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 850 } });
      let deliveryFails = true, verifications = 0;
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.hostname === 'altaha.test') {
          const file = path.join(__dirname, '..', path.basename(url.pathname));
          if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
          return route.fulfill({ body: fs.readFileSync(file), contentType:
            file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
        }
        if (url.pathname === '/auth/me') return route.fulfill({ status: 401, json: { detail: 'Expired' } });
        if (url.pathname === '/auth/request-link') return route.fulfill({
          status: deliveryFails ? 503 : 200,
          json: deliveryFails ? { detail: 'Email is unavailable' } : { sent: true } });
        if (url.pathname === '/auth/verify') {
          verifications++;
          return route.fulfill({ json: { token: 'new-session', user: { email: 'reader@example.com' } } });
        }
        return route.abort();
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(() => localStorage.setItem('altaha-session-v1', 'expired'));
      await page.goto('https://altaha.test/signin.html');
      await page.waitForFunction(() => !document.getElementById('si-go').disabled);
      assert.match(await page.locator('h1').innerText(), /^Sign in$/);
      await page.locator('#si-email').fill('reader@example.com');
      await page.locator('#si-go').click();
      await page.getByText('Email is unavailable', { exact: true }).waitFor();
      assert.equal(await page.locator('#si-go').isEnabled(), true);
      deliveryFails = false;
      await page.locator('#si-go').click();
      await page.getByRole('heading', { name: 'Check your inbox' }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.goto('https://altaha.test/signin.html?token=one-time');
      await page.locator('#si-confirm').waitFor();
      assert.equal(verifications, 0);
      assert.equal(new URL(page.url()).search, '');
      await page.locator('#si-confirm').click();
      await page.getByRole('heading', { name: 'You are signed in', exact: true }).waitFor();
      assert.equal(verifications, 1);
      assert.equal(await page.evaluate(() => localStorage.getItem('altaha-session-v1')), 'new-session');
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log('Sign-in browser checks passed at mobile and desktop widths.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });

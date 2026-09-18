/* Sign-in UI with mocked delivery; never sends real emails. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    for (const width of [320, 390, 768, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 850 } });
      let deliveryFails = true, verifications = 0, codeTries = 0;
      const GOOD_CODE = '472913';
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
        // Not configured here, so the page must not offer a Google button it
        // cannot make work.
        if (url.pathname === '/auth/config')
          return route.fulfill({ json: { google_client_id: '', email: true } });
        if (url.pathname === '/auth/verify-code') {
          codeTries++;
          const body = JSON.parse(route.request().postData() || '{}');
          if (body.code !== GOOD_CODE)
            return route.fulfill({ status: 400, json: { detail: 'That code is not right. 4 tries left.' } });
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
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false,
        'sign-in must fit the viewport');
      const emailBox = await page.locator('#si-email').boundingBox();
      const buttonBox = await page.locator('#si-go').boundingBox();
      assert.ok(Math.abs(emailBox.width - buttonBox.width) < 1, 'form controls must align');
      assert.ok(buttonBox.height >= 48, 'primary action must be touch sized');
      await page.locator('#si-email').fill('reader@example.com');
      await page.locator('#si-go').click();
      await page.getByText('Email is unavailable', { exact: true }).waitFor();
      assert.equal(await page.locator('#si-go').isEnabled(), true);
      assert.equal(await page.locator('#si-google').isVisible(), false,
        'a Google button was offered on a deploy with no client id');
      deliveryFails = false;
      await page.locator('#si-go').click();

      // The code is typed on the page already open. That is the whole point of
      // it: a link is opened by whichever browser the mail app hands it to, so
      // on a phone the session lands somewhere the reader is not.
      await page.getByRole('heading', { name: 'Check your email' }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

      // Pasted from a notification it arrives spaced; that is not the reader's
      // problem to strip.
      await page.locator('#si-code').fill('4 7 2-9 1 3');
      assert.equal(await page.locator('#si-code').inputValue(), GOOD_CODE);

      // A wrong code says so and leaves them on the page to try again.
      await page.locator('#si-code').fill('000000');
      await page.locator('#si-codego').click();
      await page.getByText(/not right/).waitFor();
      assert.equal(await page.locator('#si-codego').isEnabled(), true);
      assert.equal(await page.locator('#si-code').inputValue(), '', 'a wrong code was left to be edited');

      await page.locator('#si-code').fill(GOOD_CODE);
      await page.locator('#si-codego').click();
      await page.getByRole('heading', { name: 'You are signed in', exact: true }).waitFor();
      assert.equal(codeTries, 2);
      assert.equal(await page.evaluate(() => localStorage.getItem('altaha-session-v1')), 'new-session');

      // Back to a clean slate for the link half of the test.
      await page.evaluate(() => localStorage.removeItem('altaha-session-v1'));
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
    console.log('Sign-in: code typed in place and link both work, at mobile and desktop widths.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });

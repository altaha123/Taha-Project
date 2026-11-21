/* Deleting an account, as a person does it. The API is mocked: nothing real
 * is deleted.
 *
 * Both app stores send a reviewer to this page, and it does something that
 * cannot be undone, so it has to be right in both directions. It must not
 * delete on a stray tap, a half-typed address or a failed request that looked
 * like a success; and when it does delete, it must say so, sign the browser
 * out, and not leave the old watchlist behind to be copied into the next
 * account that signs in here.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const EMAIL = 'reader@example.com';

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    for (const width of [320, 390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 850 } });
      const state = { signedIn: true, fail: null, deletes: [] };
      await context.route('**/*', async (route) => {
        const req = route.request(), url = new URL(req.url());
        if (url.hostname === 'altaha.test') {
          const file = path.join(__dirname, '..', path.basename(url.pathname));
          if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
          return route.fulfill({ body: fs.readFileSync(file), contentType:
            file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
        }
        if (url.pathname === '/auth/me') {
          return state.signedIn ? route.fulfill({ json: { id: 7, email: EMAIL } })
                                : route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
        }
        if (url.pathname === '/me/delete' && req.method() === 'POST') {
          const body = JSON.parse(req.postData() || '{}');
          state.deletes.push({ body, auth: req.headers().authorization || '' });
          if (state.fail === 'server') return route.fulfill({ status: 500, json: {} });
          if (state.fail === 'network') return route.abort();
          if (String(body.confirm || '').trim().toLowerCase() !== EMAIL) {
            return route.fulfill({ status: 400, json: { detail: 'Type your email address exactly as it is shown to confirm.' } });
          }
          state.signedIn = false;
          return route.fulfill({ json: { ok: true, deleted: true } });
        }
        return route.abort();
      });

      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const seed = () => page.addInitScript(() => {
        if (sessionStorage.getItem('seeded')) return;
        sessionStorage.setItem('seeded', '1');
        localStorage.setItem('altaha-session-v1', 'live-session');
        localStorage.setItem('altaha-watchlist-v1', '["TCS","INFY"]');
        localStorage.setItem('altaha-portfolio-draft-v1', '[{"symbol":"TCS","qty":10}]');
        localStorage.setItem('altaha-theme', 'dark');
      });

      /* ── signed out: nothing to press but Sign in ───────────────────── */
      state.signedIn = false;
      await page.goto('https://altaha.test/delete-account.html');
      await page.locator('#da-signin').waitFor();
      assert.equal(await page.locator('#da-go').count(), 0, 'a delete button was shown to somebody not signed in');
      assert.equal(await page.locator('#da-signin').getAttribute('href'), 'signin.html?next=delete-account.html',
        'signing in must bring the reader back here');
      assert.match(await page.locator('main').innerText(), /hello@altahascreener\.in/, 'no way to ask by email');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false,
        'the page must fit a ' + width + 'px screen');

      /* ── signed in ──────────────────────────────────────────────────── */
      state.signedIn = true;
      await seed();
      await page.goto('https://altaha.test/delete-account.html');
      await page.locator('#da-go').waitFor();
      assert.equal(await page.locator('#da-email').innerText(), EMAIL);
      assert.equal(await page.locator('#da-go').isDisabled(), true, 'the button was live before anything was typed');
      const box = await page.locator('#da-go').boundingBox();
      assert.ok(box.height >= 48, 'the button must be touch sized');

      // Half an address, then somebody else's: still nothing to press.
      await page.locator('#da-confirm').fill('reader@example');
      assert.equal(await page.locator('#da-go').isDisabled(), true);
      await page.locator('#da-confirm').fill('someone@example.com');
      assert.equal(await page.locator('#da-go').isDisabled(), true);
      await page.locator('#da-confirm').press('Enter');
      assert.equal(state.deletes.length, 0, 'Enter on a wrong address reached the server');

      // The server falls over. Nothing is claimed, nothing is signed out, nothing local is cleared.
      await page.locator('#da-confirm').fill(' Reader@Example.com ');
      assert.equal(await page.locator('#da-go').isEnabled(), true, 'a capital letter or a space must not block it');
      for (const fail of ['server', 'network']) {
        state.fail = fail;
        await page.locator('#da-go').click();
        await page.waitForFunction(() => /nothing was removed/i.test(document.getElementById('da-note').textContent));
        assert.equal(await page.locator('#da-done').count(), 0, 'a failed deletion was reported as done');
        assert.equal(await page.locator('#da-go').isEnabled(), true, 'the reader could not try again');
        assert.equal(await page.evaluate(() => localStorage.getItem('altaha-session-v1')), 'live-session',
          'a failed deletion signed the reader out');
        assert.equal(await page.evaluate(() => localStorage.getItem('altaha-watchlist-v1')), '["TCS","INFY"]',
          'a failed deletion cleared the device');
      }

      // It works.
      state.fail = null;
      const before = state.deletes.length;
      await page.locator('#da-go').click();
      await page.locator('#da-done').waitFor();
      const sent = state.deletes[state.deletes.length - 1];
      assert.equal(state.deletes.length, before + 1, 'the request was sent more than once');
      assert.equal(sent.auth, 'Bearer live-session', 'the request did not say who was asking');
      assert.equal(String(sent.body.confirm).trim().toLowerCase(), EMAIL);
      assert.match(await page.locator('#da-panel').innerText(), /has been deleted/);
      const left = await page.evaluate(() => ({
        session: localStorage.getItem('altaha-session-v1'),
        watchlist: localStorage.getItem('altaha-watchlist-v1'),
        draft: localStorage.getItem('altaha-portfolio-draft-v1'),
        theme: localStorage.getItem('altaha-theme'),
      }));
      assert.equal(left.session, null, 'still signed in after deleting the account');
      assert.equal(left.watchlist, null, 'the old watchlist is still on the device');
      assert.equal(left.draft, null, 'the old portfolio draft is still on the device');
      assert.equal(left.theme, 'dark', 'appearance is not about the account and must be kept');

      // Coming back: there is no account, so there is nothing to delete.
      await page.goto('https://altaha.test/delete-account.html');
      await page.locator('#da-signin').waitFor();

      /* ── the reader who wants to keep what is on the device ─────────── */
      state.signedIn = true;
      await page.evaluate(() => {
        sessionStorage.setItem('seeded', '1');     // the page cleared it; do not seed again
        localStorage.setItem('altaha-session-v1', 'live-session');
        localStorage.setItem('altaha-watchlist-v1', '["ITC"]');
      });
      await page.goto('https://altaha.test/delete-account.html');
      await page.locator('#da-go').waitFor();
      await page.locator('#da-device').uncheck();
      await page.locator('#da-confirm').fill(EMAIL);
      await page.locator('#da-go').click();
      await page.locator('#da-done').waitFor();
      assert.equal(await page.evaluate(() => localStorage.getItem('altaha-watchlist-v1')), '["ITC"]',
        'the device was cleared though the reader asked for it not to be');
      assert.equal(await page.evaluate(() => localStorage.getItem('altaha-session-v1')), null);

      /* ── the privacy policy says where this page is ─────────────────── */
      await page.goto('https://altaha.test/privacy.html');
      assert.match(await page.locator('h1').innerText(), /^Privacy policy$/);
      assert.equal(await page.locator('main a[href="delete-account.html"]').count(), 1,
        'the privacy policy does not link to the page that deletes an account');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false,
        'the privacy policy must fit a ' + width + 'px screen');

      assert.deepEqual(errors, [], 'the pages raised errors');
      await context.close();
    }
    console.log('Delete account: nothing on a wrong address or a failed request; on success the account, the session and the device are cleared.');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });

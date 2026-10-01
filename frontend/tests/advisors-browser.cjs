/* Advisors in a real Chromium: the directory, a profile, starting a chat, the
   chat itself from both sides, applying, and the ways in. No live calls.

   What this is actually guarding:
     · A READER CAN FIND SOMEBODY: the directory renders, filters, and arrives
       pre-filtered from the portfolio plan (?kind=ria&topic=portfolio).
     · STARTING A CHAT SENDS WHAT THE READER CHOSE: the topic, the name they
       want shown, the question, and whether to share their portfolio — and
       the share box is offered only by an investment adviser.
     · THE CHAT IS LIVE: a reply arrives by polling, without a reload, and the
       reader's message is marked Seen when the other side has read it.
     · A REFUSED MESSAGE IS EXPLAINED, NOT LOST: the sentence that tripped the
       check is shown and the draft stays in the box.
     · WHAT STRANGERS TYPE IS TEXT: a message carrying markup is shown as
       characters and never runs.
     · THE ADVISER SEES WHAT WAS SHARED and nothing that was not.
     · AN EDUCATOR CANNOT PICK PORTFOLIO REVIEW, and the application sends
       what the form says.
     · SIGNING IN COMES BACK HERE (?next=), and never to another site.
     · IT IS REACHABLE: the header on a wide screen, the Portfolio menu, the
       phone drawer; and no sideways scroll on a phone. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/advisors');
fs.mkdirSync(output, { recursive: true });

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(root, p === '/' ? '/index.html' : p);
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

const KINDS = [
  { id: 'ria', label: 'SEBI-registered Investment Adviser', short: 'SEBI RIA', registered: true },
  { id: 'ra', label: 'SEBI-registered Research Analyst', short: 'SEBI RA', registered: true },
  { id: 'educator', label: 'Educator · not SEBI-registered', short: 'Educator', registered: false }
];
const ALL = ['ria', 'ra', 'educator'];
const TOPICS = [
  { id: 'portfolio', label: 'Portfolio review', kinds: ['ria'] },
  { id: 'stocks', label: 'Stocks & research', kinds: ALL },
  { id: 'retirement', label: 'Retirement & goals', kinds: ['ria', 'educator'] },
  { id: 'learning', label: 'Learning the markets', kinds: ALL }
];
const t = id => ({ id, label: TOPICS.find(x => x.id === id).label });
const ASHA = {
  slug: 'asha-rao', display_name: 'Asha Rao', headline: 'Fee-only adviser for salaried families',
  kind: 'ria', kind_label: KINDS[0].label, kind_short: 'SEBI RIA', registered: true, sebi_reg: 'INA000012345',
  register_url: 'https://www.sebi.gov.in/', topics: [t('portfolio'), t('retirement')], languages: ['English', 'Hindi'],
  experience_years: 15, featured: false, accepting: true, online: true, can_see_portfolio: true,
  answered: 12, reply_minutes: 95, bio: 'Fifteen years of helping households plan.', links: ['https://example.com/asha']
};
const MEERA = Object.assign({}, ASHA, {
  slug: 'meera-iyer', display_name: 'Meera Iyer', headline: 'Author and long-time value investor', kind: 'educator',
  kind_label: KINDS[2].label, kind_short: 'Educator', registered: false, sebi_reg: null, register_url: null,
  topics: [t('learning'), t('stocks')], can_see_portfolio: false, online: false
});
const NOW = new Date().toISOString();

function fresh() {
  return {
    user: null, starts: [], sends: [], shares: [], puts: [], profile: null,
    thread: [{ id: 1, sender: 'seeker', body: 'Should I trim ITC?', created_at: NOW }],
    read: 0, share: true,
    inbox: [{ id: 1, sender: 'seeker', body: '<img src=x onerror="window.__pwned=1">Hello', created_at: NOW }]
  };
}

function chatView(state, id, after) {
  if (id === 41) {
    return { id: 41, role: 'seeker', topic: 'portfolio', topic_label: 'Portfolio review', status: 'open',
      closed_by: null, blocked: false, share_portfolio: state.share, read_only: false,
      messages: state.thread.filter(m => m.id > after), their_read_id: state.read, created_at: NOW,
      expert: ASHA, seeker_name: 'Ravi' };
  }
  return { id: 42, role: 'expert', topic: 'portfolio', topic_label: 'Portfolio review', status: 'open',
    closed_by: null, blocked: false, share_portfolio: true, read_only: false,
    messages: state.inbox.filter(m => m.id > after), their_read_id: 0, created_at: NOW, expert: ASHA,
    seeker_name: 'Ravi <b>',
    shared: { holdings: [{ symbol: 'TCS', qty: 10, avg_price: 3500 }, { symbol: 'ITC', qty: 300, avg_price: 410 }],
              risk_profile: { band: 'Moderate', score: 55, capacity: 60, tolerance: 50, assessed_at: NOW } } };
}

async function wire(context, state) {
  await context.addInitScript(() => { window.ADV_POLL_SCALE = 0.05; });
  await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url()), m = req.method();
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') {
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    const p = u.pathname, body = () => JSON.parse(req.postData() || '{}');
    const authed = !!state.user && /Bearer /.test(req.headers()['authorization'] || '');
    const need = () => route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
    if (p === '/auth/me') return state.user ? route.fulfill({ json: state.user }) : need();
    if (p === '/auth/config') return route.fulfill({ json: { google_client_id: '', email: true } });
    if (p === '/auth/request-link') return route.fulfill({ json: { sent: true } });
    if (p === '/auth/verify-code') {
      state.user = { email: 'ravi@example.com' };
      return route.fulfill({ json: { token: 'tok-new', user: { email: 'ravi@example.com' } } });
    }
    if (p === '/advisors') {
      return route.fulfill({ json: { experts: [ASHA, MEERA], kinds: KINDS, topics: TOPICS,
        disclaimer: 'Altaha lists these people. Educators are not registered. Never pay anyone you meet here.' } });
    }
    const prof = p.match(/^\/advisors\/profile\/([a-z-]+)(\/chat)?$/);
    if (prof && !prof[2]) {
      const e = [ASHA, MEERA].find(x => x.slug === prof[1]);
      return e ? route.fulfill({ json: { expert: e, disclaimer: 'Altaha lists these people.' } })
               : route.fulfill({ status: 404, json: { detail: 'That adviser is not listed.' } });
    }
    if (prof && prof[2]) {
      if (!authed) return need();
      state.starts.push({ slug: prof[1], body: body() });
      return route.fulfill({ json: Object.assign(chatView(state, 41, 0), { existing: false }) });
    }
    if (p === '/advisors/me') {
      if (!authed) return need();
      return route.fulfill({ json: { email: state.user.email, expert: state.profile, unread: 1, holdings: 3,
        risk_profile: { band: 'Moderate', assessed_at: NOW } } });
    }
    if (p === '/advisors/me/profile' && m === 'PUT') {
      const b = body(); state.puts.push(b);
      state.profile = Object.assign({}, MEERA, { id: 9, status: 'pending', review_note: null,
        display_name: b.display_name, kind: b.kind, topics: b.topics.map(t), languages: b.languages });
      return route.fulfill({ json: { expert: state.profile } });
    }
    if (p === '/advisors/chats') {
      if (!authed) return need();
      return route.fulfill({ json: { unread: 1, expert: null, as_expert: null, as_seeker: state.starts.length === 0 ? [] : [
        { id: 41, topic: 'portfolio', topic_label: 'Portfolio review', status: 'open', last_message_at: NOW,
          preview: 'Should I trim ITC?', preview_from: 'seeker', unread: 1, with: 'Asha Rao',
          expert_slug: 'asha-rao', expert_kind: 'ria', online: true }] } });
    }
    const chat = p.match(/^\/advisors\/chats\/(\d+)(\/\w+)?$/);
    if (chat) {
      if (!authed) return need();
      const id = +chat[1], action = chat[2];
      if (!action) return route.fulfill({ json: chatView(state, id, +(u.searchParams.get('after') || 0)) });
      if (action === '/messages') {
        const b = body(); state.sends.push(b.body);
        if (/WhatsApp/.test(b.body)) {
          return route.fulfill({ status: 422, json: { detail: {
            message: 'This message contains a phone number, so it was not sent.', sentence: '' } } });
        }
        if (/^Buy/.test(b.body)) {
          return route.fulfill({ status: 422, json: { detail: {
            message: 'You are listed as an educator, so a buy or sell call cannot be sent.', sentence: b.body } } });
        }
        const list = id === 41 ? state.thread : state.inbox;
        const msg = { id: list[list.length - 1].id + 1, sender: id === 41 ? 'seeker' : 'expert', body: b.body, created_at: NOW };
        list.push(msg);
        return route.fulfill({ json: { message: msg } });
      }
      if (action === '/share') {
        const b = body(); state.shares.push(b.share); state.share = b.share;
        return route.fulfill({ json: chatView(state, id, 0) });
      }
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
}

async function noSideways(page, label) {
  const o = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(o <= 1, label + ': sideways scroll of ' + o + 'px');
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];
  const watch = page => page.on('pageerror', e => errors.push(String(e.stack || e)));

  // ── The directory, signed out ──────────────────────────────────────────
  {
    const state = fresh();
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await wire(context, state);
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/advisors.html?kind=ria&topic=portfolio', { waitUntil: 'load' });
    await page.locator('.adv-card').first().waitFor();
    assert.equal(await page.locator('.adv-card').count(), 1, 'arrives filtered to advisers who review portfolios');
    assert.match(await page.locator('.adv-card').innerText(), /INA000012345/);
    await page.locator('.adv-chip', { hasText: 'Everyone' }).click();
    await page.locator('#adv-topic').selectOption('');
    assert.equal(await page.locator('.adv-card').count(), 2);
    await page.locator('.adv-chip', { hasText: 'Educators' }).click();
    assert.deepEqual(await page.locator('.adv-card h3').allInnerTexts(), ['Meera Iyer']);
    await page.locator('.adv-chip', { hasText: 'Everyone' }).click();
    await page.locator('#adv-q').fill('asha');
    assert.deepEqual(await page.locator('.adv-card h3').allInnerTexts(), ['Asha Rao']);
    assert.match(await page.locator('.adv-note').innerText(), /Never pay anyone/);
    await page.screenshot({ path: path.join(output, 'directory.png'), fullPage: true });

    // A profile, signed out: the way in is sign-in, and it comes back here.
    await page.locator('.adv-card', { hasText: 'Asha Rao' }).click();
    await page.locator('.adv-start .adv-btn').waitFor();
    assert.match(await page.locator('.adv-regnote').innerText(), /not|INA000012345/);
    const href = await page.locator('.adv-start .adv-btn').getAttribute('href');
    assert.equal(decodeURIComponent(href), 'signin.html?next=advisors.html#a/asha-rao');
    await context.close();
  }

  // ── Starting a chat, and the chat itself, as the reader ────────────────
  {
    const state = fresh(); state.user = { id: 7, email: 'ravi@example.com' };
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-123'));
    await wire(context, state);
    const page = await context.newPage(); watch(page);

    // An educator offers no portfolio sharing.
    await page.goto(base + '/advisors.html#a/meera-iyer', { waitUntil: 'load' });
    await page.locator('#adv-start-form').waitFor();
    assert.equal(await page.locator('#adv-share').count(), 0, 'no portfolio for an educator');
    assert.match(await page.locator('.adv-regnote').innerText(), /not SEBI-registered/);

    await page.goto(base + '/advisors.html#a/asha-rao');
    await page.locator('#adv-share').waitFor();
    assert.match(await page.locator('.adv-check').innerText(), /3 holdings saved to your account and your risk profile \(Moderate\)/);
    await page.locator('#adv-s-go').click();
    assert.match(await page.locator('#adv-s-msg-out').innerText(), /Write your question first/);
    assert.equal(state.starts.length, 0, 'nothing sent without a question');
    await page.locator('#adv-s-topic').selectOption('portfolio');
    await page.locator('#adv-s-name').fill('Ravi');
    await page.locator('#adv-s-msg').fill('Should I trim ITC?');
    await page.locator('#adv-share').check();
    await page.locator('#adv-s-go').click();
    await page.waitForURL(/#chat\/41$/);
    assert.deepEqual(state.starts[0], { slug: 'asha-rao', body: {
      topic: 'portfolio', message: 'Should I trim ITC?', name: 'Ravi', share_portfolio: true } });
    await page.locator('.adv-bubble.is-mine').waitFor();
    assert.match(await page.locator('#adv-banner').innerText(), /SEBI-registered investment adviser/);

    // A reply arrives by polling; the reader's message is then marked Seen.
    state.thread.push({ id: 2, sender: 'expert', body: 'Trim it to about 15%.', created_at: NOW });
    state.read = 1;
    await page.locator('.adv-bubble:not(.is-mine)', { hasText: 'Trim it' }).waitFor({ timeout: 5000 });
    await page.locator('.adv-bubble.is-mine .adv-seen').waitFor({ timeout: 5000 });
    assert.equal(await page.locator('.adv-bubble').count(), 2, 'each message once, however many polls');

    // Sending; and a refused message keeps its draft and says why.
    await page.locator('#adv-input').fill('Thank you!');
    await page.locator('#adv-input').press('Enter');
    await page.locator('.adv-bubble.is-mine', { hasText: 'Thank you!' }).waitFor();
    assert.equal(await page.locator('#adv-input').inputValue(), '');
    await page.locator('#adv-input').fill('WhatsApp me on 98765 43210');
    await page.locator('#adv-send').click();
    await page.locator('#adv-refused:not([hidden])').waitFor();
    assert.match(await page.locator('#adv-refused').innerText(), /phone number/);
    assert.equal(await page.locator('#adv-input').inputValue(), 'WhatsApp me on 98765 43210', 'the draft survives');
    await page.waitForTimeout(400);
    assert.equal(await page.locator('.adv-bubble', { hasText: 'Thank you!' }).count(), 1, 'a poll does not duplicate a sent message');

    // The reader can withdraw their portfolio at any time.
    await page.locator('#adv-share-live').uncheck();
    await page.waitForFunction(() => /^Let Asha/.test(document.querySelector('#adv-sharebar').innerText.trim()));
    assert.deepEqual(state.shares, [false]);
    await page.screenshot({ path: path.join(output, 'chat-reader.png'), fullPage: true });

    // Back on the profile, the open chat is continued rather than duplicated.
    await page.goto(base + '/advisors.html#a/asha-rao');
    await page.locator('.adv-start a[href="#chat/41"]', { hasText: 'Continue the chat' }).waitFor();
    assert.equal(await page.locator('#adv-start-form').count(), 0);

    // The list of chats.
    await page.goto(base + '/advisors.html#chats');
    await page.locator('.adv-row').waitFor();
    assert.match(await page.locator('.adv-row').innerText(), /Asha Rao[\s\S]*Portfolio review[\s\S]*You: Should I trim ITC\?/);
    assert.equal(await page.locator('#adv-unread').innerText(), '1');

    // The same chat on a phone.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/advisors.html#chat/41');
    await page.locator('.adv-bubble').first().waitFor();
    await noSideways(page, 'chat at 390px');
    await page.goto(base + '/advisors.html');
    await page.locator('.adv-card').first().waitFor();
    await noSideways(page, 'directory at 390px');
    await page.screenshot({ path: path.join(output, 'directory-phone.png'), fullPage: true });
    await context.close();
  }

  // ── The adviser's side: what was shared, and markup stays text ─────────
  {
    const state = fresh(); state.user = { id: 3, email: 'asha@example.com' };
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-asha'));
    await wire(context, state);
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/advisors.html#chat/42', { waitUntil: 'load' });
    await page.locator('#adv-side h2').waitFor();
    assert.match(await page.locator('#adv-side').innerText(), /Moderate[\s\S]*TCS[\s\S]*ITC/);
    assert.match(await page.locator('#adv-banner').innerText(), /obligations as a registered investment adviser/);
    const shown = await page.locator('.adv-bubble').first().innerText();
    assert.match(shown, /<img src=x onerror=/, 'markup a stranger typed is shown as text');
    assert.equal(await page.evaluate(() => window.__pwned), undefined, 'and never runs');
    assert.match(await page.locator('.adv-chatwho h1').innerText(), /Ravi <b>/);
    await page.locator('#adv-input').fill('Buy it below 1500.');
    await page.locator('#adv-send').click();
    await page.locator('#adv-refused blockquote').waitFor();
    assert.equal(await page.locator('#adv-refused blockquote').innerText(), 'Buy it below 1500.');
    await page.screenshot({ path: path.join(output, 'chat-adviser.png'), fullPage: true });
    await context.close();
  }

  // ── Applying: an educator cannot take portfolio reviews ────────────────
  {
    const state = fresh(); state.user = { id: 5, email: 'meera@example.com' };
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-meera'));
    await wire(context, state);
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/advisors.html#join', { waitUntil: 'load' });
    await page.locator('#adv-join').waitFor();
    assert.equal(await page.locator('#adv-j-regfield').isVisible(), true, 'investment adviser is the default');
    await page.locator('label', { hasText: 'Portfolio review' }).click();
    await page.locator('label.adv-kindopt', { hasText: 'Educator' }).click();
    assert.equal(await page.locator('#adv-j-regfield').isVisible(), false, 'no registration box for an educator');
    assert.equal(await page.locator('input[value="portfolio"]').isDisabled(), true);
    assert.equal(await page.locator('input[value="portfolio"]').isChecked(), false, 'and it is unticked');
    await page.locator('#adv-j-name').fill('Meera Iyer');
    await page.locator('#adv-j-head').fill('Author and long-time value investor');
    await page.locator('#adv-j-bio').fill('Twenty years of reading annual reports, and teaching how.');
    await page.locator('label', { hasText: 'Learning the markets' }).click();
    await page.locator('#adv-j-lang').fill('English, Tamil');
    await page.locator('#adv-j-link0').fill('https://example.com/meera');
    await page.locator('#adv-join-go').click();
    await page.locator('.adv-status.is-pending').waitFor();
    assert.deepEqual(state.puts[0], { kind: 'educator', sebi_reg: '', display_name: 'Meera Iyer',
      headline: 'Author and long-time value investor', bio: 'Twenty years of reading annual reports, and teaching how.',
      topics: ['learning'], languages: ['English', 'Tamil'], experience_years: '', links: ['https://example.com/meera'] });
    assert.match(await page.locator('.adv-status').innerText(), /Being checked/);
    await context.close();
  }

  // ── Signing in comes back here, and never to another site ──────────────
  for (const [next, lands] of [['advisors.html#a/asha-rao', /\/advisors\.html#a\/asha-rao$/],
                               ['https://evil.example/', /\/index\.html#portfolio$/]]) {
    const state = fresh();
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await wire(context, state);
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/signin.html?next=' + encodeURIComponent(next), { waitUntil: 'load' });
    await page.locator('#si-email').fill('ravi@example.com');
    await page.locator('#si-go').click();
    await page.locator('#si-code').fill('123456');
    await page.locator('#si-codego').click();
    await page.waitForURL(lands, { timeout: 8000 });
    await context.close();
  }

  // ── The ways in: header on wide screens, the menu, the phone drawer ────
  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 800 } });
    await wire(context, fresh());
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/', { waitUntil: 'load' });
    await page.locator('#sh-adv').waitFor();
    assert.equal(await page.locator('#sh-adv').getAttribute('href'), 'advisors.html');
    await noSideways(page, 'header at 1440px');
    await page.locator('.sh-top[data-sec="portfolio"]').hover();
    await page.locator('.sh-mega.open a.sh-item[href="advisors.html"]').click();
    await page.waitForURL(/\/advisors\.html$/);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(base + '/');
    await page.locator('#sh-burger').waitFor({ state: 'attached' });
    assert.equal(await page.locator('#sh-adv').isVisible(), false, 'no room in the header row at 1280px');
    await noSideways(page, 'header at 1280px');
    await context.close();
  }
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });
    await wire(context, fresh());
    const page = await context.newPage(); watch(page);
    await page.goto(base + '/', { waitUntil: 'load' });
    await page.locator('#sh-burger').click();
    const link = page.locator('#sh-drawer a.sh-item[href="advisors.html"]');
    await link.scrollIntoViewIfNeeded();
    await link.click();
    await page.waitForURL(/\/advisors\.html$/);
    await context.close();
  }

  const relevant = errors.filter(e => /(advisors|shell|signin)\b/.test(e) && !/Failed to load resource/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close();
  server.close();
  console.log('advisors browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });

# The forum, the weekly brief and Pro pricing

Three things added in Nov 2026, and where each one sits on the site.

## Where they fit

| What | Address | Where a reader finds it |
|---|---|---|
| **Forum** | `forum.html` (also `/forum`) | Ideas menu, under *Talk it over*; the Ideas door page; the footer; search ("forum", "discuss", "ask") |
| **Stock discussions** | `forum.html#stock/TCS` | The **Discussion** section on every stock page (the ninth tab) |
| **Weekly brief** | `weekly.html` (also `/weekly`), `?w=2026-W47` for one issue | Footer, under Altaha; the daily brief; the forum's side panel; the Pro page; search; the Saturday email |
| **Pro plans and pricing** | `pro.html` (also `/pro` and `/pricing`) | The Me menu (header and phone), the footer ("Pro plans & pricing"), search ("pricing", "plans"), the portfolio story |

**Why the forum is behind Ideas.** The doors answer questions people arrive
with. "What are other investors looking at, and why?" is a way of answering
*What should I look at?*, so the forum sits there, stacked under *Find stocks*
so the menu stays three columns deep. It is a page of its own, like the
adviser chats, because every discussion needs an address that can be shared
and that the sign-in page can return to. It was not made a fourth door: the
three doors are the site's whole map and a fourth would put a community on the
same level as the market itself.

**Why the stock discussion forum is not a second forum.** It is the same
forum read one company at a time. Every "Stocks" thread carries the company's
symbol; the stock page lists that company's threads; a thread started from a
stock page is also on the front page. One set of rules, one moderation queue.

**Why the weekly brief is a page and not a door.** It is something to read
once a week, like the daily policy brief beside it in the footer, and it is
mostly read from the email.

## The forum

`backend/forum.py` (rules), `backend/forum_routes.py` (HTTP),
`frontend/forum.html`, `forum.js`, `forum.css`; the stock page's section is
`loadTalk` in `frontend/stock.js`.

- **Reading needs nothing; writing needs an account and a forum name.** The
  email is never shown. A name is 3–24 characters, unique however it is spaced
  or cased, and cannot look like an email, a phone number, Altaha or a
  regulator.
- **Seven categories**: Stocks (with a symbol), Market & economy, Investing &
  trading, Mutual funds & ETFs, Tax & personal finance, Beginners, Using Altaha.
  A stock thread can only be opened for a company the server knows
  (`main._known_company`), so the stock pages only ever list real companies.
- **House rules, checked before a post is saved.** Each refusal returns the
  sentence that tripped it (HTTP 422 with `sentence` and `rule`):
  - *contact* — phone numbers, UPI addresses, emails, WhatsApp and Telegram
    links (the adviser chats' own check: that is how investment scams begin);
  - *promise* — "guaranteed returns", "sure shot", "double your money". Narrower
    than the adviser chats' check, so "credit guarantee scheme" and the
    "risk-free rate" pass;
  - *tip* — a price to buy or sell at, a target, a stop-loss level, including
    "Buy HDFC Bank at 1650". Publishing a tip is a SEBI research analyst's
    licence. Reasons and opinions are welcome; "I bought at 450 in 2021", a
    question, and a negated sentence ("I would not buy at 450") pass;
  - *links* — more than three in a post.
- **Reports.** Any member reports a post once. Three distinct reports hide it
  until the owner looks; a hidden opening post takes its thread with it.
- **The owner** (`GET /admin/forum`, `POST /admin/forum/moderate`, admin key,
  closed when `ADMIN_KEY` is unset): hide, restore, lock, unlock, pin, unpin,
  ban, unban, dismiss reports. Nothing is ever deleted: a removed or hidden
  post keeps its row for review.
- **Limits**: 5 new discussions a day, 4 posts a minute and 80 a day per member;
  5,000 characters a post.
- **Members' words are text.** Escaped, split into paragraphs, http(s) links
  marked `nofollow ugc noopener`. `frontend/tests/forum-browser.cjs` puts markup
  and a `javascript:` address through it.

Not yet: email when somebody replies to your discussion; editing a post
(remove and post again); a page per discussion that a search engine can read.

## The weekly brief

`backend/weekly_brief.py`, `GET /weekly`, `GET /weekly/issues`,
`POST /jobs/weekly-brief`, `POST /admin/weekly/topics`; `frontend/weekly.html`;
`.github/workflows/weekly-brief.yml`.

One issue per ISO week, Monday to Sunday in IST. It leads with **the week in
brief**, three or four sentences written by fixed rules from the figures below
them, then:

- **This week's topics** — anything the owner chooses to write about, on any
  subject. Added on the page itself (`weekly.html` shows an editor when the
  browser holds the admin key; `?edit=1` asks for it) or through
  `POST /admin/weekly/topics` `{"action":"add","week"?,"title","body","symbols"?}`.
  A blank line starts a paragraph; lines starting with "- " become a list.
  Topics are held to the forum's rules on tips and promises, because the brief
  is the site's own voice. Readers can suggest one through the forum.
- **The market** — each index against the close of the week before, and Nifty
  session by session.
- **Money flow** — FII and DII net buying per session and for the week, from
  the provisional figures the server recorded. A session it never saw says
  "not recorded" and is not counted as zero.
- **New rules that matter** — the week's circulars from the daily brief whose
  effect is positive, negative or mixed, most important first.
- **On the forum** — the busiest discussions and most-discussed stocks.

The current week is a draft, rebuilt at most every fifteen minutes. On Saturday
at 09:10 IST the workflow publishes the week that just traded and mails it to
everyone who takes the daily digest, once per person per week (`send_log`, kind
`weekly`). A published issue keeps its figures; its topics are read live.

## Pro: ₹5,000 a quarter or ₹15,000 a year

`frontend/pro.html` is the pricing page: Free, Pro Quarterly (₹5,000, about
₹1,667 a month) and Pro Yearly (₹15,000, about ₹1,250 a month, the price of
three quarters), a Free-and-Pro table, the features, and questions. The yearly
plan is chosen to start with.

It is still the founding list described in [`ACCOUNTS.md`](ACCOUNTS.md): an
address and a plan are saved, nothing is charged, and the page says so. The
new prices were given new plan ids, `quarterly` and `yearly`, so the waitlist
never adds a yes at ₹15,000 to a yes at the old ₹1,999 (`annual`) or ₹249
(`monthly`); `GET /admin/pro-waitlist` counts each separately and lists the
prices.

The forum is free, and stays free: it is listed under Free on the page.

Before charging: a payment provider (Razorpay or similar) and its webhook, a
subscriptions table, the decision on GST, and the legal advice the README
already calls for on the portfolio calls.

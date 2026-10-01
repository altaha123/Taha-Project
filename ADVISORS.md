# Advisors — talk to a person

`advisors.html`. A reader finds a SEBI-registered investment adviser, a
registered research analyst or a well-known market educator, reads who they
are, and chats with them — about their portfolio, a stock, a fund, retirement,
a career in finance, anything. Advisers and educators register themselves; the
owner checks them before anyone is listed.

Code: `backend/advisors.py` (every rule and every statement),
`backend/advisor_routes.py` (HTTP only), `frontend/advisors.js`,
`frontend/advisors.css`. Tests: `backend/tests/test_advisors.py`,
`frontend/tests/advisors-browser.cjs`.

## What it looks like from outside

**A reader**
1. Opens Advisors — the header on a wide screen, **Portfolio → Ask a person**
   in the menu, the phone drawer, or the line under the portfolio action plan,
   which arrives filtered to investment advisers who take portfolio reviews.
2. Filters by who (registered / adviser / analyst / educator), by topic, or by
   name, and opens a profile: registration number with a link to SEBI's own
   register, experience, languages, how quickly they usually reply.
3. Signs in (if not already — sign-in returns them to this profile via
   `signin.html?next=`), picks a topic, chooses the name the other side sees,
   writes a question, and — with an investment adviser only — ticks **Share my
   portfolio** to show the holdings and latest risk profile saved to their
   account. They can stop sharing at any time from inside the chat.
4. Chats. Replies arrive without reloading; their own messages show **Seen**
   once read. If they are away, one email tells them there is a reply.

**An adviser or educator**
1. **For advisers** → signs in → applies: category, SEBI number (INA… or
   INH…), name, one-line headline, about, topics, languages, experience,
   up to three public links.
2. Sees **Being checked** until the owner approves; then **Listed**, with a
   **Taking new chats** switch and an inbox (**People asking me**).
3. Gets one email when a new chat or message arrives while they are away.

**The owner**
1. Opens `advisors.html#admin`, pastes `ADMIN_KEY` (kept for that tab only).
2. For each registered applicant, opens SEBI's register from the card, searches
   the number, and checks the name matches. Approve, reject (with a note the
   applicant sees), suspend, or feature.
3. Reads reported chats — with the conversation — in the same place.

## Switching it on

Nothing new to configure. It uses what is already there:

| Setting | Used for |
|---|---|
| `DATA_DIR` (the Render disk) | The tables live in the accounts database, so the daily R2 backup already covers them |
| `EMAIL_PROVIDER` + key, `EMAIL_FROM` | "You have a message" emails. Unset, they are printed to the log and chats still work |
| `ADMIN_KEY` | The review queue. **Closed when unset** — it shows applicants' email addresses and other people's chats |
| `SITE_URL` | The link in the notification email |

Then list the first few advisers yourself: send them `advisors.html#join`, and
approve them from `#admin`. An empty directory says so and invites applicants.

## The three kinds, and what each may do

| | Investment adviser (`ria`) | Research analyst (`ra`) | Educator (`educator`) |
|---|---|---|---|
| Registration | `INA` + 9 digits, checked | `INH` + 9 digits, checked | none — and may not claim one |
| Topics | all, including **Portfolio review** | all except portfolio review, retirement, tax | all except portfolio review |
| Can be shown a reader's portfolio | yes, if the reader shares it | no | no |
| Buy/sell calls, targets, stop-losses | yes — under their registration | yes | **not sent** |

Why: advice on a person's own money is the investment adviser's licence;
views on securities are the research analyst's; somebody unregistered may
teach but not recommend. The categories are SEBI's, not ours.

## What may be said

Every message is checked before it is stored. A refused message is not
stored, the sender is told why — with the exact sentence when one tripped the
check — and the draft stays in the box to rephrase.

- **Contact details, both sides:** phone numbers, UPI addresses, email
  addresses, WhatsApp and Telegram links. Moving a conversation somewhere
  nobody can see it is how the investment scams that end in a fake trading
  app begin; a reader asked for their number cannot be talked into sending it.
- **Promises of returns, every adviser:** "guaranteed", "assured returns",
  "risk-free", "double your money". Negated sentences pass ("nothing is
  guaranteed").
- **Calls, educators only:** buy, sell, accumulate, target price, stop-loss,
  entry/exit levels, book profits, recommend. A question is never a call
  ("should you buy it?" passes), nor is "buy-and-hold", "buyback" or "sell-off".

The sentence-at-a-time rule with negation is the one `score_explain.py`
applies to the AI explanation; `advisors.call_sentence` uses its own term list
because a human conversation needs fewer false positives than an AI summary.

## Design decisions worth knowing

**Polling, not WebSockets.** One worker, eight threads, 512 MB. A socket or a
long poll holds a thread while a chat is open; eight open chats would starve
every other page. A poll is one indexed SQLite read — every 4 s while a
conversation is moving, 10 s after a quiet minute, 20 s after five, none while
the tab is hidden. "Seen" timestamps are written at most once a minute per
chat, so an open chat is not a write every few seconds.

**The reader's email is never shown.** The adviser sees the name the reader
typed, or "Altaha reader". Emails reach both sides through the server.

**The message is not in the email.** These are conversations about money;
inboxes are forwarded, synced and read over shoulders, and the provider is a
third party. The email says who wrote and links to the chat. One email per
unread stretch: none while the recipient has the chat open (seen in the last
three minutes), one when they are away, and no more until they have read it.

**Nothing said can be deleted.** A registered adviser must be able to produce
the record of what was advised to whom and when, and a report has to be
judged on what actually happened. There is no delete route; a test pins that.

**No star ratings.** SEBI's advertisement code for registered advisers does
not allow testimonials. Profiles show facts instead: registration,
experience, conversations answered, median time to first reply.

**One open chat per reader per adviser.** Writing again continues it, like any
messaging app. Either side can close a chat; only the adviser can block. A
reader can start five new chats a day; anyone can send twelve messages a
minute; messages are 2,000 characters at most.

**A registration change goes back for review.** Editing the wording of a live
profile keeps it live; changing the category or the number takes it off the
list until it is checked again — the number is the one thing on the page a
reader relies on Altaha for.

**Same database as accounts.** Every row belongs to an account, the backup
already copies that file, and a notification needs a join to `users`. The
statements are in `advisors.py`, so a move to Postgres is two files.

## The API

| Route | |
|---|---|
| `GET /advisors?kind=&topic=&q=` | the directory (public) |
| `GET /advisors/profile/{slug}` | one listed profile (public) |
| `GET /advisors/me` | my profile if I applied, unread count, what I could share |
| `PUT /advisors/me/profile` | apply, or edit |
| `POST /advisors/me/accepting` `{on}` | take new chats, or pause |
| `GET /advisors/chats` | both inboxes |
| `POST /advisors/profile/{slug}/chat` `{topic, message, name, share_portfolio}` | start, or continue the open chat |
| `GET /advisors/chats/{id}?after=N` | a chat; messages after N |
| `POST /advisors/chats/{id}/messages` `{body}` | send — 422 `{message, sentence}` when refused |
| `POST /advisors/chats/{id}/close` `{block}` | end it |
| `POST /advisors/chats/{id}/share` `{share}` | reader shares or withdraws |
| `POST /advisors/chats/{id}/report` `{reason}` | report to the owner |
| `GET /admin/advisors?status=` | applications, counts (ADMIN_KEY) |
| `POST /admin/advisors/review` `{expert_id, action, note}` | approve / reject / suspend / feature / unfeature |
| `GET /admin/advisors/reports` | reported chats with the conversation |

A chat that is not yours answers 404, not 403, so ids cannot be probed.

## What is deliberately not here — and the decisions it waits on

**Payments.** Chats are free during the beta, and advisers are told not to ask
for money. Paid chats (a wallet and per-minute or per-session pricing, like
AstroTalk) need decisions that are the owner's: a payment gateway and its KYC,
Altaha's commission and GST on it, refunds, and — for registered advisers —
SEBI's rules on how and how much an adviser may charge, which apply to the
adviser, not to the platform. Take legal advice before turning this on.

**Photos.** Initials, for now. A photo is an upload, storage, and a moderation
queue; a remote image URL would tell a third party who is reading the page.

**Voice and video.** Calls need a media server or a paid provider; the chat
record is also what makes moderation possible.

**Push notifications.** Email first, as with the daily digest.

**Legal note.** Listing unregistered personalities beside registered advisers,
and SEBI's 2024 rules restricting registered entities' associations with
unregistered people who give advice or claim returns, are questions for a
lawyer before this is promoted. The educator rules above are built to keep
educators to education; they are a safeguard, not legal clearance.

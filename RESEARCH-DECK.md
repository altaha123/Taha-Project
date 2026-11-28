# The Research Deck

Research articles with photos, published by the owner only, each one ready to
post on X with a proper card.

| What | Where |
|---|---|
| The deck | `/research-deck` (`frontend/research-deck.html`, `.js`, `.css`) |
| One article | `/research-deck?a=<slug>` |
| The link to post on X | `/share/research/<slug>?v=<version>` (reads as a card, forwards to the article) |
| The card image | `/og/research.png?slug=<slug>&v=<version>` (1200×630, cover photo beside the title) |
| Rules and storage | `backend/research_deck.py` |
| HTTP | `backend/research_routes.py` |
| In the menus | Ideas → *Talk it over* → **Research Deck** (and the footer, and search) |

## Only the owner writes

Reading needs nothing. Every write (uploading a photo, saving, publishing,
unpublishing, deleting) goes to `/admin/research/*` and needs `ADMIN_KEY`, in
the `X-Admin-Key` header or `?key=`. **The editor is closed when `ADMIN_KEY` is
not set**, unlike the older control switches that stay open for a local run.

On the page: scroll to the bottom, press **Owner sign-in**, paste the admin key.
It is kept in that browser only (the same entry the Post drafts panel uses) and
is checked with the server before anything changes on screen. A wrong key is
refused and forgotten. Signed in, you see **New article**, your drafts (dashed
outline) and an **Edit this article** link on each article.

## Writing one

- **Title**, **summary** (up to 300 characters, and what X shows under the card),
  **stocks it is about** (symbols separated by commas; `uno minda` becomes
  `UNOMINDA`), **cover photo**.
- **Add photo** uploads one or more photos and puts `![caption](media:<id>)`
  where the cursor is. Edit the caption in the brackets.
- The body is a small Markdown: `#`/`##`/`###` headings, `- ` lists, `1. `
  lists, `> ` quotes, `**bold**`, `*italic*`, `` `code` ``, `[text](https://…)`,
  `---`, and `$TCS` links to that stock's page. Everything else is text:
  nothing typed is ever read as HTML.
- **Save draft** keeps it private (its photos too). **Publish** puts it on the
  deck and shows **Share on X**, **Copy link** and **More ways to share**
  (WhatsApp, Telegram, LinkedIn, copy or download the card).

## Sharing on X

**Share on X** opens X's composer with the title, as much of the summary as
fits, up to three `$CASHTAGS` and the `/share/research/…` link. X fetches that
link, reads its card tags and draws the card under the post. The link carries
`?v=<version>`, which goes up on every save, because X caches a card by URL; an
article edited after it was posted gets a fresh card the next time it is shared.
The article's address (`slug`) is set from the first title and never changes,
so links already posted keep working after a retitle.

## Photos

Every upload is opened and re-encoded by Pillow: anything that is not really a
JPEG, PNG, WebP or GIF is refused; EXIF is dropped (a phone photo's GPS
position goes with it); the long side is capped at 2000 px. Screenshots and
charts stay PNG, photographs become JPEG. Uploads over 3 MB are shrunk in the
browser before they are sent; the server limit is 15 MB.

Photos are stored **inside** `altaha_research.db` at the top of `DATA_DIR`,
not in a folder beside it, because `backup.py` copies only the files at the top
of `DATA_DIR`. The nightly R2 backup therefore carries every article and photo.
A photo in a draft is not public until its article is published; a photo
uploaded but never used in a saved article is deleted after seven days.

## Before posting research publicly

Each article ends with a line saying it is research for education and is not
a recommendation, and that Altaha is not SEBI-registered. As the README notes
for the portfolio review, publishing stock recommendations in India falls
under the SEBI Research Analysts Regulations. Keep that line true, and keep
buy/sell calls and price targets out of articles unless that has been looked
at.

## Tests

- `backend/tests/test_research_deck.py`: who may write, EXIF stripping, draft
  privacy, stable addresses, the share page and the card.
- `frontend/share.test.js`: the X post fits with its link and never points at
  the API host.
- `frontend/tests/research-deck-browser.cjs` (run by hand: `node
  frontend/tests/research-deck-browser.cjs`): reading, Share on X, the editor
  staying shut to anyone else, the owner's write-publish-share loop, phone width.

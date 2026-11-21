# Publishing to the Google Play Store

What to do, in order, and what to type into each form. The app itself is
covered in [`MOBILE.md`](MOBILE.md).

Everything Play asks for that could be prepared in advance is here or in
`mobile/store/`. What is left needs the owner: a Play Console account, the
signing key, and the answers that are promises.

## Before starting

Two addresses have to be live, because Play checks them:

| | |
|---|---|
| Privacy policy | `https://altahascreener.in/privacy` |
| Delete your account | `https://altahascreener.in/delete-account` |

Both exist on the branch and go live when it is merged to `main`. Merge first.

## 1. The account

Open one at [play.google.com/console](https://play.google.com/console). It
costs $25, once. Google verifies who you are, which takes a day or two.

**Personal or organisation.** A personal account created after November 2023
cannot publish straight away: it has to run a closed test with at least 12
testers who stay opted in for 14 days running, and only then may it apply for
production. An organisation account (a registered business, with a D-U-N-S
number) skips that. If there is a registered business, use it. It is also
the better answer to the regulatory question in MOBILE.md.

## 2. The signing key

Play only accepts an app signed with your upload key. Make it once and keep
it and its password somewhere safe; if it is lost Google can reset it, but
only by request.

On any computer with Java:

```bash
keytool -genkeypair -v -keystore upload-keystore.jks -alias altaha \
        -keyalg RSA -keysize 2048 -validity 10000
```

Then give it to GitHub, so every build is signed without the key leaving
there. Repository › Settings › Secrets and variables › Actions › New
repository secret, four times:

| Secret | Value |
|---|---|
| `ALTAHA_KEYSTORE_BASE64` | the output of `base64 -w0 upload-keystore.jks` |
| `ALTAHA_KEYSTORE_PASSWORD` | the keystore's password |
| `ALTAHA_KEY_ALIAS` | `altaha` |
| `ALTAHA_KEY_PASSWORD` | the key's password |

Run Actions › Mobile apps › Run workflow. The run now also keeps
`altaha-android-release-aab`: the file to upload.

## 3. Create the app

All apps › Create app.

| Field | Answer |
|---|---|
| App name | Altaha Screener |
| Default language | English (India) |
| App or game | App |
| Free or paid | Free |

## 4. Store listing

Grow › Store presence › Main store listing.

**Short description** (80 characters at most):

> A 0–100 score for any Indian stock, with every calculation shown.

**Full description:**

> Altaha Screener gives any NSE or BSE stock a score from 0 to 100 and shows
> how it got there.
>
> Type a company's name. The score is built from technical checks (trend,
> momentum, where the price sits in its 52-week range) and fundamental checks
> (profitability, debt, growth, valuation, the nine-point Piotroski score).
> Every check opens to show the figures that went in, the formula and the
> points it earned, with a one-line explanation in plain English.
>
> WHAT IS IN THE APP
> • Market: the indices, FII and DII flows, every sector, the day's movers and
>   headlines, big trades, order wins and the results calendar
> • Stock pages: the score, a chart, the quarterly results as filed, who owns
>   the company, and how it compares with its peers
> • Screener: tap what you want from a company (makes good money, owes
>   little, not too pricey) or write your own query
> • Watchlists, and a review of the portfolio you already hold
> • Money planner: the month your investments could pay your household's bills
> • A glossary, and a full account of how the score is worked out
>
> NO ACCOUNT NEEDED
> Every tool works without signing in. Sign in with your email address only
> if you want your portfolio and watchlists on every device, and one email
> after the market closes about the stocks you hold.
>
> Built by a Chartered Accountant. Free.
>
> Altaha Screener is for information and education. It is not investment
> advice, and it is not registered with SEBI as an investment adviser or a
> research analyst. Prices and filings come from the exchanges and other
> public sources and can be late or wrong. Decide for yourself, and ask a
> registered adviser before you invest.

Read that last paragraph and the README's first section together before
publishing. The description must not claim less than the app does: the
portfolio review gives a hold, trim or exit call on each holding.

**Pictures**, all in `mobile/store/` (made by `mobile/scripts/store-screenshots.cjs`):

| Play asks for | File |
|---|---|
| App icon, 512 × 512 | `icon-512.png` |
| Feature graphic, 1024 × 500 | `feature-graphic.png` |
| Phone screenshots, at least 2 | `phone-1.png` … `phone-5.png` |

| Field | Answer |
|---|---|
| App category | Finance |
| Email address | hello@altahascreener.in |
| Website | https://altahascreener.in |

## 5. App content

Policy › App content. Each of these is a declaration, so each has to be true.

**Privacy policy:** `https://altahascreener.in/privacy`

**Ads:** No, the app does not contain ads.

**App access:** Some of the app is behind a sign-in: saving to an account,
the daily email, adviser chats and the wealth desk. Play's reviewers need a
way in, and sign-in here is a code sent by email, which a reviewer cannot
receive. Either give them an address whose inbox they can read, or say in the
instructions box: *"Every tool works without signing in. Sign-in is optional
and only saves the portfolio and watchlist to an account. It uses a one-time
code sent by email."* If Google asks for more, a reviewer login has to be
built.

**Content rating:** Start the questionnaire with category *Reference, News or
Educational*. No violence, sexual content, drugs or gambling. Answer **Yes**
to users being able to communicate with each other: the adviser chat is that.
It has a report button and a block, which the form also asks about.

**Target audience:** 18 and over only.

**News app:** No. It shows market headlines but is not a news publisher.

**Data safety.** These have to agree with the privacy policy. The apps send
no analytics and no crash reports (MOBILE.md), so those are not declared.

| Question | Answer |
|---|---|
| Does the app collect or share user data? | Yes |
| Is all data encrypted in transit? | Yes |
| Can users request that data is deleted? | Yes: `https://altahascreener.in/delete-account` |

| Data type | Collected | Shared | Optional | Why |
|---|---|---|---|---|
| Personal info › Email address | Yes | No | Yes, only if you sign in | Account management, App functionality |
| Financial info › Other financial info (the saved portfolio) | Yes | No | Yes | App functionality |
| Messages › Other in-app messages (adviser chats) | Yes | No | Yes | App functionality |

"Shared" means given to another company for its own use. The email provider,
the hosts and the AI providers handle data on our behalf, which Play does not
count as sharing; the privacy policy names each of them.

**Financial features:** Play asks every app which financial features it has.
This is the declaration to take advice on. The app shows scores, picks and a
portfolio review with a call on each holding, and it lets a reader talk to
advisers. It does not lend, take deposits, trade or hold money.

**Government app, health app:** No.

## 6. Upload and test

Testing › Closed testing › Create track. Upload the `.aab`. When Play offers
**Play App Signing**, accept it: Google keeps the real signing key and yours
is only the upload key.

Add testers by email address (12 or more for a personal account) and send
them the opt-in link. They install it from the Play Store like any app.

## 7. Production

Personal account: after 14 days with 12 testers, Apply for production access
and answer the questions about the test. Then, for either kind of account:
Production › Create new release › pick the build › Send for review. Review
usually takes a few days for a new app.

## Every update after that

```bash
cd mobile && npm run set-version -- 1.0.1
```

Push, let the Mobile apps workflow build the new `.aab`, upload it as a new
release. Play refuses a build whose version is not higher than the last.

## After the app exists in the console

Setup › App signing shows a ready-made `assetlinks.json`. Saved as
`frontend/.well-known/assetlinks.json`, it makes links to altahascreener.in
open in the app (MOBILE.md, "Links that open the app").

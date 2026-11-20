# The Android and iOS apps

Altaha Screener as an app on a phone: the same pages as altahascreener.in,
inside a native app for each platform, talking to the same API.

Nothing was rewritten. The site is static pages and scripts with no build
step, it already signs people in with a token rather than a cookie, and the
API already answers any origin. That is exactly what
[Capacitor](https://capacitorjs.com) needs: it wraps a folder of web pages in
a real Android app and a real iOS app, and gives the pages a way to call the
phone. Every tool on the site is in the apps the day it ships on the site,
because it is the same file.

| | |
|---|---|
| App id | `in.altahascreener.app` on both platforms |
| Android | 7.0 and later (API 24), built against Android 16 (API 36) |
| iOS | 15 and later, iPhone and iPad |
| Version | `version` in `mobile/package.json`, set for both with `npm run set-version` |

## What is in `mobile/`

| Path | What it is |
|---|---|
| `scripts/build-web.mjs` | Copies `frontend/` into `www/`, the folder the apps ship. Never writes to `frontend/` |
| `src/bridge.js` | The first script on every page inside the app. Share, downloads, print, links, Back, the status bar |
| `src/routes.mjs` | Where a link goes inside the app. Pure functions, so every address the site publishes can be tested |
| `src/native.css` | The few rules that differ inside the app: the notch, and the Google button |
| `android/` | The Android Studio project |
| `ios/` | The Xcode project |
| `assets/` | The icon and the splash screen, as the five pictures every size is cut from |
| `tests/` | See "How it is checked" |

`www/` is built, never edited and never committed.

## What the app does that a web view does not

A page inside an app's web view is missing a handful of things a browser
gives it for free. Each one fails without an error: the button looks pressed
and nothing happens. `src/bridge.js` puts them back.

- **Share.** Android's web view has no `navigator.share`, and every Share
  button on the site hides itself when that is missing. In the app it opens
  the phone's share sheet, with the card image attached.
- **Downloads.** `<a download>` does nothing in a web view. A portfolio CSV,
  a score card or the planner's calendar entry is written to the app's cache
  and offered through the share sheet, which is where "Save to Files", Drive
  and WhatsApp all are.
- **Print.** `window.print()` is a no-op. It opens the system print dialog,
  which is also "Save as PDF". No published plugin does this, so each app
  carries a small one of its own, `ShellPlugin` (one Java file, one Swift
  file).
- **Links.** `/methodology` and `/stock-TCS` only resolve on the website
  because `frontend/vercel.json` rewrites them. Inside the app they would
  silently show the home page. The build hands the bridge the same table, so
  they open the page they stand for. A link to anywhere else (a filing, a
  news story, `/share/RELIANCE`) opens in a browser tab over the app and
  closes back to it. WhatsApp, Telegram and X links go to those apps.
- **Back.** Android's Back button walks the page history, and at the first
  page puts the app away.
- **The notch.** The app draws edge to edge. The header grows by the height
  of the status bar, and everything that measures from the header follows,
  because it all reads `--sh-chrome-h`.
- **Appearance.** The status bar's icons follow the site's light and dark
  setting, and so does the colour behind a page while the next one loads, so
  a dark page does not flash white on every tap.
- **No signal.** The chart library and the three fonts are inside the app,
  not on a CDN, so the first screen draws without waiting on anyone. Losing
  the connection shows a one-line notice; the figures need the API.
- **Where it is.** `window.API_BASE` and `window.SITE_URL` are set before any
  other script runs, so a shared link reads altahascreener.in and never the
  web view's own `localhost`.

Two things are deliberately different from the website:

- **The Google button is hidden.** Google refuses to sign anyone in from
  inside an app's web view. The six-digit email code works everywhere, which
  is why it exists.
- **Analytics are off.** `analytics.js` only reports from altahascreener.in,
  and the app is not at that address. Nothing is sent to PostHog or Sentry
  from the apps. That keeps the stores' privacy forms short. If the numbers
  are wanted, add the app's host to `HOSTS` there and declare it in both
  stores.

## Running it on your own machine

You need Node 22. For Android, Android Studio. For iOS, a Mac with a current Xcode.

```bash
cd mobile
npm ci
npm run android     # builds the bundle, copies it in, opens Android Studio
npm run ios         # the same, and opens Xcode
```

Press Run in either. To point the app at a different API while developing,
change `API_BASE` at the top of `scripts/build-web.mjs`.

**After any change to the website**, the app has to be built again to carry
it: `npm run sync`. Prices, scores and picks come from the API and are always
current; it is the pages themselves that are fixed at build time. A release of
the site does not change the apps until a new build is sent to the stores.

To change the icon or the splash screen, replace the pictures in `assets/`
and run `npm run icons`. The icon there is the site's 512px one enlarged to
1024px. A sharper original, if there is one, belongs in `assets/icon-only.png`
and `assets/icon-foreground.png` before the first store upload.

## How it is checked

| Check | Where it runs | What it proves |
|---|---|---|
| `tests/bundle.test.mjs` | `ci.yml`, every pull request | Every link written in `frontend/` has somewhere to go inside the app. Nothing loads from a CDN. Every page of the site is in the bundle |
| `tests/app-browser.cjs` | `ci.yml`, every pull request | The real bundle in a real browser, on a phone-sized screen with a notch. Share, a CSV export, print, Back, dark appearance, an outside link, a link opened from outside the app: each is done, and the call that reaches the phone is checked |
| `tests/android-smoke.sh` | `mobile-apps.yml`, on an Android 14 emulator | The APK installs, starts, loads the home page, and opens the stock page from `altaha://stock?ticker=TCS` |
| `tests/ios-smoke.sh` | `mobile-apps.yml`, on an iPhone simulator | The iOS app installs, starts and loads the home page, its own plugin answers, and iOS knows `altaha://` links are its. (iOS asks a person before following such a link from a script, so the test stops there.) |

The first two fake the phone one layer down (`tests/harness.cjs`) and need no
network. The last two are real operating systems; they are the only place a
crash on launch would show.

`mobile-apps.yml` runs when anything in `mobile/` changes, and by hand from
Actions › Mobile apps › Run workflow. Each run keeps the debug APK and a
screenshot of each app. **To put the app on an Android phone today**, download
`altaha-android-debug-apk` from the latest run and open it on the phone.

What none of this replaces: a person using each app on a real phone before a
release. Share sheets, the print dialog and the keyboard are the phone's own
screens, and no test here can see them.

## Releasing

Both stores refuse a build whose version is not higher than the last one, so
every upload starts with:

```bash
cd mobile
npm run set-version -- 1.0.1
```

### Android

One time: create the upload key and keep it somewhere safe. Losing it means
asking Google to reset it.

```bash
keytool -genkeypair -v -keystore upload-keystore.jks -alias altaha \
        -keyalg RSA -keysize 2048 -validity 10000
```

Then either build on your own machine, with `mobile/android/keystore.properties`
(never committed):

```
storeFile=/absolute/path/to/upload-keystore.jks
storePassword=...
keyAlias=altaha
keyPassword=...
```

```bash
cd mobile && npm run sync && cd android && ./gradlew bundleRelease
# → app/build/outputs/bundle/release/app-release.aab
```

or let GitHub build it. Add four repository secrets and every run of
`mobile-apps.yml` also produces `altaha-android-release-aab`:

| Secret | Value |
|---|---|
| `ALTAHA_KEYSTORE_BASE64` | `base64 -w0 upload-keystore.jks` |
| `ALTAHA_KEYSTORE_PASSWORD` | the keystore's password |
| `ALTAHA_KEY_ALIAS` | `altaha` |
| `ALTAHA_KEY_PASSWORD` | the key's password |

Upload the `.aab` in the Play Console. A new personal developer account has
to run a closed test with at least 12 testers for 14 days before Google
allows a public release; an organisation account does not.

### iOS

There is no way round a Mac and an Apple Developer Program membership.

1. `cd mobile && npm run ios`
2. In Xcode: the App target › Signing & Capabilities › choose your Team.
3. Product › Archive, then Distribute App › App Store Connect.
4. TestFlight first, then submit for review.

CI builds the iOS app unsigned for the simulator, which proves it compiles
and starts. It cannot sign it: that takes your certificate.

## Before either store will accept it

These are not code in `mobile/`. They are what the stores ask of the
product, and the first two will stop a submission.

1. **Deleting an account.** Both stores require that anybody who can create
   an account can delete it from inside the app, and Google wants a web
   address for it too. The site has no such thing today: there is no
   `DELETE /me`. It has to remove the user, their sessions, holdings,
   watchlists, saved screens, risk profile and whatever the wealth desk and
   the advisors keep for them.
2. **A privacy policy at a public address.** Both stores ask for the link,
   and both ask what is collected: an email address, a portfolio, a
   watchlist, and the daily email. The site has no such page.
3. **Who submits it.** Apple's guideline 5.1.1(ix) asks that apps in
   regulated fields, financial services among them, come from a legal entity
   and not an individual's account. The portfolio review gives hold, trim and
   exit calls, and the README is plain that the project is registered with
   SEBI as neither an adviser nor a research analyst. A reviewer may ask.
   Take the same legal advice the README already asks for before submitting,
   and consider whether the calls belong in the first version of the apps.
4. **Altaha Pro.** It is a waitlist and nothing is charged, which is fine.
   The day it is sold inside the apps, Apple and Google each require their
   own in-app purchase for it, and take their cut.
5. **A wrapped website.** Apple rejects apps that are "a repackaged website"
   (guideline 4.2). The share sheet, printing, saved files and links that
   open the app are what answer that. Notifications, below, answer it best.
6. Store listings: screenshots at each required size, a description, a
   support address, and the content-rating and data-safety questionnaires.

## What is not built yet

- **Notifications.** The natural one is the daily email as a push: what your
  holdings did, after the close. It needs a Firebase project, an Apple push
  key, a table of device tokens and a sender beside `digest.py`. None of that
  can be created without the owner's Google and Apple accounts.
- **Google and Apple sign-in.** Native Google sign-in needs OAuth client ids
  for each app. Once any third-party sign-in is offered on iOS, Apple
  requires Sign in with Apple beside it.
- **Updating the pages without a store release.** Possible (the pages are
  only files), and worth doing once the apps have users, because the site
  ships daily and a store review takes a day or two.

## Links that open the app

`altaha://stock?ticker=TCS` opens the app on that page today, on both
platforms, with no setup.

For links to altahascreener.in itself to open the app (the sign-in email's
link, a shared company page), each platform wants proof that the site and the
app belong to the same owner. The Android app already asks for these links;
Android ignores the request until the proof is there, so nothing changes
until then.

- **Android.** Serve `https://altahascreener.in/.well-known/assetlinks.json`
  (a file at `frontend/.well-known/assetlinks.json`) naming the package
  `in.altahascreener.app` and the SHA-256 fingerprint of the signing
  certificate. The Play Console shows the exact file under Setup › App
  signing once the app exists there.
- **iOS.** Add the Associated Domains capability in Xcode with
  `applinks:altahascreener.in`, and serve
  `https://altahascreener.in/.well-known/apple-app-site-association` naming
  `<Team ID>.in.altahascreener.app`. It has no file extension, so it needs a
  `Content-Type: application/json` header in `frontend/vercel.json`.

Where a link lands is decided in one place, `pageFor` in `src/routes.mjs`,
and tested in `tests/bundle.test.mjs`.

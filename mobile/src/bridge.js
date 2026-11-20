/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — the native bridge
   The first script on every page inside the Android and iOS apps.

   The pages are the website's pages, unchanged. A page inside an app's web
   view is missing a handful of things a browser gives it for free, and each
   one fails silently: the button looks pressed and nothing happens. This file
   puts them back.

     Share          Android's web view has no navigator.share. Every Share
                    button on the site checks for it and hides when it is
                    missing; here it opens the phone's share sheet.
     Downloads      <a download> does nothing in a web view. A CSV, a card
                    image or a calendar entry is written to the app's cache
                    and offered through the share sheet, which is where "Save
                    to Files", Drive and WhatsApp all are.
     Print          window.print() is a no-op. It opens the system print
                    dialog, which is also "Save as PDF".
     Links          An address with no ".html" (/methodology, /stock-TCS)
                    exists only because Vercel rewrites it; here it is mapped
                    to the page it stands for. Anything outside the site opens
                    in a browser tab over the app, and closes back to it.
     Back           Android's Back button walks the page history and puts the
                    app away at the first page, instead of doing nothing.
     Status bar     Follows the site's light and dark appearance.

   It also tells the pages where they are: window.API_BASE and window.SITE_URL
   are set before any other script runs, so a shared link reads
   altahascreener.in and never the web view's own "localhost".

   Everything is inside a try/catch or a rejected-promise handler. A missing
   plugin costs the one feature it backs and nothing else.
   ═══════════════════════════════════════════════════════════════════════════ */

import { Capacitor, registerPlugin, SystemBars, SystemBarsStyle } from '@capacitor/core';
import { App } from '@capacitor/app';
import { Browser } from '@capacitor/browser';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { Network } from '@capacitor/network';
import { Share } from '@capacitor/share';
import { SplashScreen } from '@capacitor/splash-screen';
import { pageFor, routeFor } from './routes.mjs';

/* Written in by scripts/build-web.mjs. */
const SITE = __SITE_URL__;
const API = __API_BASE__;
const ROUTES = __ROUTES__;
const PAGES = __PAGES__;
const BUILD = __BUILD__;

/* android/…/ShellPlugin.java and ios/App/App/ShellPlugin.swift. */
const Shell = registerPlugin('AltahaShell');

const native = Capacitor.isNativePlatform();
const platform = Capacitor.getPlatform();
const html = document.documentElement;
const quiet = () => {};

/* ── 1 · where the pages are ─────────────────────────────────────────────── */

window.API_BASE = API;
window.SITE_URL = SITE;
window.AltahaNative = { platform, version: BUILD.version, commit: BUILD.commit, built: BUILD.built };
html.classList.add('native-app', 'native-' + platform);

/* One line per page, in the phone's own log (logcat, Xcode's console). It is
   how tests/android-smoke.sh and tests/ios-smoke.sh know the page inside the
   app is the one that was asked for, and it is the first thing to look for
   when somebody reports a blank screen. */
if (native) console.log('[altaha] bridge ready: ' + platform + ' ' + BUILD.version + ' ' + location.pathname);

function toast(text) {
  try {
    let el = document.getElementById('native-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'native-toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.add('on');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.remove('on'), 3200);
  } catch (e) {}
}

/* ── 2 · links ───────────────────────────────────────────────────────────── */

const routing = { site: SITE, api: API, routes: ROUTES, pages: PAGES };
const route = (href) => routeFor(href, location.href, routing);

function go(r) {
  if (r.kind === 'local') { location.href = new URL(r.href, location.href).href; return; }
  if (r.kind === 'browser' && native) {
    Browser.open({ url: r.url }).catch(() => { location.href = r.url; });
    return;
  }
  // Outside the app's own host the web view hands the address to the phone,
  // which is how a wa.me link reaches WhatsApp rather than a web page.
  location.href = r.url;
}

function isDownload(a) {
  if (a.hasAttribute('download')) return true;
  try { return /\.(csv|ics|xlsx?)$/i.test(new URL(a.href, location.href).pathname); }
  catch (e) { return false; }
}

/* On window, in the bubble phase: the page's own handlers run first, and a
   link one of them has already dealt with (preventDefault) is left alone. */
window.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button) return;
  const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
  if (!a) return;
  const raw = a.getAttribute('href') || '';
  if (!raw || raw.charAt(0) === '#' || /^javascript:/i.test(raw)) return;
  if (native && isDownload(a)) { e.preventDefault(); saveAnchor(a); return; }
  const r = route(a.href);
  if (r) { e.preventDefault(); go(r); return; }
  // A page of the app's own, asked for in a new tab. There are no tabs.
  if (a.target === '_blank') { e.preventDefault(); location.href = a.href; }
});

/* window.open has three uses on the site: an outside link, the pop-out chart
   (a page of the app's own), and an empty window that a report is written
   into and printed. */
const browserOpen = window.open;
window.open = function (url) {
  if (!url) return native ? printWindow() : browserOpen.apply(window, arguments);
  const r = route(String(url));
  if (r) go(r); else location.href = new URL(String(url), location.href).href;
  return { closed: false, close: quiet, focus: quiet, blur: quiet };
};

/* ── 3 · print ───────────────────────────────────────────────────────────── */

function fire(name) { try { window.dispatchEvent(new Event(name)); } catch (e) {} }

function print(options) {
  fire('beforeprint');
  return Shell.print(options)
    .catch(() => toast('Printing is not available on this device.'))
    .then(() => fire('afterprint'));
}

function installPrint() {
  window.print = function () { print({ name: document.title || 'Altaha Screener' }); };
}

function printWindow() {
  let buffer = '';
  const doc = {
    open: quiet,
    write: (s) => { buffer += String(s); },
    writeln: (s) => { buffer += String(s) + '\n'; },
    close: quiet,
  };
  return {
    closed: false, document: doc, focus: quiet, blur: quiet, close: quiet,
    print: () => {
      const title = /<title>([^<]*)<\/title>/i.exec(buffer);
      print({ name: (title && title[1]) || document.title || 'Altaha Screener', html: buffer, baseUrl: SITE + '/' });
    },
  };
}

/* ── 4 · files: share and download ───────────────────────────────────────── */

function base64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error('could not read the file'));
    reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ''));
    reader.readAsDataURL(blob);
  });
}

function safeName(name, blob) {
  const ext = { 'image/png': 'png', 'image/jpeg': 'jpg', 'text/csv': 'csv', 'text/calendar': 'ics',
    'application/pdf': 'pdf', 'text/plain': 'txt' }[String((blob && blob.type) || '').split(';')[0]] || 'bin';
  let n = String(name || '').replace(/[^\w.\- ]+/g, '').trim().slice(-80);
  if (!n) n = 'altaha';
  return /\.[a-z0-9]{2,5}$/i.test(n) ? n : n + '.' + ext;
}

/* Into the cache, which is the one folder both platforms let an app hand to
   another app with no permission prompt. */
function stash(blob, name, folder) {
  return base64(blob).then((data) => Filesystem.writeFile({
    path: folder + '/' + safeName(name, blob), data, directory: Directory.Cache, recursive: true,
  })).then((res) => res.uri);
}

function cancelled(e) { return /cancel|abort|dismiss/i.test(String((e && e.message) || e)); }

function installShare() {
  if (navigator.share) return;   // iOS has its own, and it works
  const canShare = (data) => !data || !data.files ||
    Array.prototype.every.call(data.files, (f) => f instanceof Blob);
  const share = (data) => {
    data = data || {};
    const files = data.files ? Array.prototype.slice.call(data.files) : [];
    return Promise.all(files.map((f) => stash(f, f.name, 'shared'))).then((uris) => {
      const options = { dialogTitle: data.title || 'Share' };
      if (data.title) options.title = data.title;
      if (data.text) options.text = data.text;
      if (data.url) options.url = data.url;
      if (uris.length) options.files = uris;
      return Share.share(options);
    }).then(() => undefined, (e) => {
      // The site treats AbortError as "the reader closed the sheet".
      const err = new Error((e && e.message) || 'Share failed');
      err.name = cancelled(e) ? 'AbortError' : 'NotAllowedError';
      throw err;
    });
  };
  try {
    Object.defineProperty(navigator, 'share', { value: share, configurable: true, writable: true });
    Object.defineProperty(navigator, 'canShare', { value: canShare, configurable: true, writable: true });
  } catch (e) {}
}

/* The site makes a blob, clicks a link to it and revokes the address in the
   same breath. Saving is asynchronous here, so the blob behind each address
   is remembered until a minute after it is revoked. */
const blobs = new Map();
function rememberBlobs() {
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = (object) => {
    const url = create(object);
    if (object instanceof Blob) blobs.set(url, object);
    return url;
  };
  URL.revokeObjectURL = (url) => {
    setTimeout(() => blobs.delete(url), 60000);
    return revoke(url);
  };
}

function save(href, name) {
  const known = blobs.get(href);
  const blob = known ? Promise.resolve(known) : fetch(href).then((r) => {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.blob();
  });
  return blob.then((b) => {
    const file = safeName(name || href.split(/[?#]/)[0].split('/').pop(), b);
    return stash(b, file, 'downloads').then((uri) =>
      Share.share({ files: [uri], dialogTitle: 'Save or send ' + file }));
  }).catch((e) => { if (!cancelled(e)) toast('Could not save that file. Please try again.'); });
}

function saveAnchor(a) { return save(a.href, a.getAttribute('download')); }

function installDownloads() {
  rememberBlobs();
  // a.click() on a link that was never added to the page raises no event the
  // listener above could see, and that is how every export on the site works.
  const click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute('download') && /^(blob|data|https?):/i.test(this.href)) { saveAnchor(this); return; }
    return click.call(this);
  };
}

/* ── 5 · the phone ───────────────────────────────────────────────────────── */

function hex(color) {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(color || '');
  if (!m || (m[4] !== undefined && Number(m[4]) === 0)) return '';
  return '#' + [m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('');
}

/* The status bar's icons, and the colour behind the page while the next one
   loads: without it a dark page flashes white on every tap. */
let painted = '';
function paintTheme() {
  const dark = html.getAttribute('data-theme') === 'dark';
  let color = '';
  try {
    // --paper first: the page fades between appearances, so for a third of a
    // second after the switch its painted background is still the old colour,
    // and a custom property has no such in-between.
    const paper = getComputedStyle(html).getPropertyValue('--paper').trim();
    color = /^#[0-9a-f]{6}$/i.test(paper) ? paper
      : hex(getComputedStyle(document.body || html).backgroundColor) ||
        hex(getComputedStyle(html).backgroundColor);
  } catch (e) {}
  color = (color || (dark ? '#0C0B08' : '#FBFAF7')).toUpperCase();
  if (painted === dark + color) return;
  painted = dark + color;
  SystemBars.setStyle({ style: dark ? SystemBarsStyle.Dark : SystemBarsStyle.Light }).catch(quiet);
  Shell.setBackground({ color, dark }).catch(quiet);
}

function offline(isOffline) {
  let el = document.getElementById('native-offline');
  if (!el && isOffline && document.body) {
    el = document.createElement('div');
    el.id = 'native-offline';
    el.setAttribute('role', 'status');
    el.textContent = 'No connection. Figures will refresh when you are back online.';
    document.body.appendChild(el);
  }
  if (el) el.classList.toggle('on', !!isOffline);
}

function installPhone() {
  App.addListener('backButton', (state) => {
    if (state && state.canGoBack) history.back();
    else App.minimizeApp().catch(quiet);
  }).catch(quiet);

  /* A link to the site, or altaha://…, opened from outside the app. */
  App.addListener('appUrlOpen', (event) => {
    const url = String((event && event.url) || '');
    const page = pageFor(url, routing);
    if (page) location.href = new URL(page, location.href).href;
    // One of the site's server-rendered pages (/stocks, /share/RELIANCE): the
    // app does not carry it, so it is shown over the app rather than dropped.
    else if (/^https?:/i.test(url)) Browser.open({ url }).catch(quiet);
  }).catch(quiet);

  new MutationObserver(paintTheme).observe(html, { attributes: true, attributeFilter: ['data-theme'] });

  Network.addListener('networkStatusChange', (s) => offline(!s.connected)).catch(quiet);

  const ready = () => {
    paintTheme();
    // The splash screen stays until there is a page to show, and not a
    // moment longer. capacitor.config.json takes it down by itself after
    // three seconds, in case this line is never reached.
    SplashScreen.hide({ fadeOutDuration: 200 }).catch(quiet);
    Network.getStatus().then((s) => offline(!s.connected)).catch(quiet);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();

  // A tap on the bottom bar should feel like a tap on a tab bar.
  document.addEventListener('click', (e) => {
    const t = e.target && e.target.closest ? e.target.closest('.ux-bottom a, .ux-bottom button') : null;
    if (t) Haptics.impact({ style: ImpactStyle.Light }).catch(quiet);
  }, true);
}

if (native) {
  try { installDownloads(); } catch (e) {}
  try { installPrint(); } catch (e) {}
  try { installShare(); } catch (e) {}
  try { installPhone(); } catch (e) {}
}

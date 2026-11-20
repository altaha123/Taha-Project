/* Build the web assets the apps ship with.
 *
 * The website has no build step and the apps do not give it one. This copies
 * frontend/ into mobile/www and makes the four changes a page needs to live
 * inside an app instead of at altahascreener.in:
 *
 *   1. Nothing is fetched from a CDN. The chart library and the three fonts
 *      are copied in, so the first screen does not wait on unpkg or Google
 *      Fonts and still draws with no signal.
 *   2. The viewport covers the whole screen (viewport-fit=cover), and
 *      native.css keeps the header and the bottom bar clear of the notch and
 *      the gesture bar.
 *   3. native-bridge.js is the first script on every page. It is what makes
 *      Share, downloads, printing, the Back button and outside links behave
 *      like an app (src/bridge.js).
 *   4. Tests, tools and the Vercel config stay behind.
 *
 * frontend/ is never written to. Run it again after any change to the site:
 *
 *     npm run build        (this file)
 *     npx cap sync         (copies www into the Android and iOS projects)
 */
import { build } from 'esbuild';
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MOBILE = path.resolve(HERE, '..');
const SRC = path.resolve(MOBILE, '..', 'frontend');
const OUT = path.join(MOBILE, 'www');
const MODULES = path.join(MOBILE, 'node_modules');

const SITE_URL = 'https://altahascreener.in';
const API_BASE = 'https://taha-project.onrender.com';

/* What the website needs and the app does not. */
const SKIP_DIRS = new Set(['tests', 'tools', 'node_modules', '.well-known']);
const SKIP_FILES = new Set(['vercel.json', 'robots.txt']);
const skip = (name) => SKIP_FILES.has(name) || /\.test\.js$/.test(name);

function copyTree(from, to) {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    const a = path.join(from, entry.name), b = path.join(to, entry.name);
    if (entry.isDirectory()) { if (!SKIP_DIRS.has(entry.name)) copyTree(a, b); }
    else if (!skip(entry.name)) fs.copyFileSync(a, b);
  }
}

/* ── 1 · the chart library and the fonts, from node_modules ─────────────── */

const CHART_CDN = /https:\/\/(?:unpkg\.com|cdn\.jsdelivr\.net\/npm)\/lightweight-charts@[\d.]+\/dist\/lightweight-charts\.standalone\.production\.js/g;
const CHART_LOCAL = 'vendor/lightweight-charts.js';

const FONTS = [
  { pkg: 'inter', family: 'Inter', weights: [400, 500, 600, 700, 800], styles: ['normal'] },
  { pkg: 'ibm-plex-mono', family: 'IBM Plex Mono', weights: [400, 500, 600], styles: ['normal'] },
  { pkg: 'instrument-serif', family: 'Instrument Serif', weights: [400], styles: ['normal', 'italic'] },
];
/* latin carries the alphabet; latin-ext carries the rupee sign. */
const SUBSETS = ['latin', 'latin-ext'];

function vendorFonts() {
  const dir = path.join(OUT, 'vendor', 'fonts');
  fs.mkdirSync(dir, { recursive: true });
  let css = '/* Written by mobile/scripts/build-web.mjs. The same three families the site\n' +
            '   asks Google Fonts for, served from inside the app. */\n';
  for (const font of FONTS) {
    const pkgDir = path.join(MODULES, '@fontsource', font.pkg);
    for (const weight of font.weights) for (const style of font.styles) {
      /* fontsource names its sheets 400.css and 400-italic.css, and each one
         holds a block per subset with the unicode-range Google publishes. */
      const sheet = fs.readFileSync(
        path.join(pkgDir, style === 'italic' ? `${weight}-italic.css` : `${weight}.css`), 'utf8');
      for (const subset of SUBSETS) {
        const file = `${font.pkg}-${subset}-${weight}-${style}.woff2`;
        const block = sheet.split('@font-face').find((b) => b.includes(`/${file})`));
        if (!block) throw new Error(`no ${subset} block for ${font.family} ${weight} ${style}`);
        const range = /unicode-range:\s*([^;]+);/.exec(block);
        if (!range) throw new Error(`no unicode-range for ${file}`);
        fs.copyFileSync(path.join(pkgDir, 'files', file), path.join(dir, file));
        css += `@font-face{font-family:'${font.family}';font-style:${style};font-weight:${weight};` +
               `font-display:swap;src:url(${file}) format('woff2');unicode-range:${range[1].trim()}}\n`;
      }
    }
  }
  fs.writeFileSync(path.join(dir, 'fonts.css'), css);
}

/* ── 2 · every page ─────────────────────────────────────────────────────── */

function rewriteHtml(html, name) {
  let out = html;

  // The fonts. Each page has two preconnects and one stylesheet link.
  out = out.replace(/[ \t]*<link[^>]+rel="preconnect"[^>]+fonts\.(?:googleapis|gstatic)\.com[^>]*>\s*\n?/g, '');
  const before = out;
  out = out.replace(/<link[^>]+href="https:\/\/fonts\.googleapis\.com\/css2[^"]*"[^>]*>/g,
    '<link rel="stylesheet" href="vendor/fonts/fonts.css">');
  const hadFonts = before !== out;

  // The whole screen, including behind the status bar and the home indicator.
  const viewport = /<meta\s+name="viewport"\s+content="([^"]*)"\s*\/?>/;
  const m = viewport.exec(out);
  if (!m) throw new Error(`${name}: no viewport meta tag to extend`);
  const bridge = '<script src="native-bridge.js"></script>';
  out = out.replace(viewport,
    `<meta name="viewport" content="${m[1]}, viewport-fit=cover" />\n${bridge}`);

  // The bridge has to run before any script that looks for navigator.share,
  // API_BASE or SITE_URL, so it must come before the first other script.
  const firstScript = out.search(/<script\b/);
  if (out.indexOf(bridge) !== firstScript) {
    out = out.replace(bridge, '');
    out = out.slice(0, firstScript) + bridge + out.slice(firstScript);
  }

  // A page with no fixed header keeps itself clear of the status bar another
  // way (native.css), and has to know before the first paint.
  if (!/<script[^>]+src="shell\.js/.test(out)) out = out.replace(/<html\b/, '<html data-native-plain');

  // Last in the head, so it wins over the page's own rules.
  if (!/<\/head>/.test(out)) throw new Error(`${name}: no </head>`);
  out = out.replace('</head>', '<link rel="stylesheet" href="native.css">\n</head>');

  return { out, hadFonts };
}

/* ── 3 · the build ──────────────────────────────────────────────────────── */

function commit() {
  try { return execSync('git rev-parse --short HEAD', { cwd: MOBILE, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); }
  catch (e) { return ''; }
}

/* The addresses that exist only because vercel.json rewrites them. Inside the
   app there is no Vercel, so the bridge is handed the same table. */
function routes() {
  const vercel = JSON.parse(fs.readFileSync(path.join(SRC, 'vercel.json'), 'utf8'));
  const local = {}, remote = [];
  for (const r of vercel.rewrites || []) {
    if (/^https?:/.test(r.destination)) remote.push(r.source);
    else local[r.source] = r.destination.replace(/^\//, '');
  }
  return { local, remote };
}

async function main() {
  const pkg = JSON.parse(fs.readFileSync(path.join(MOBILE, 'package.json'), 'utf8'));
  fs.rmSync(OUT, { recursive: true, force: true });
  copyTree(SRC, OUT);

  fs.mkdirSync(path.join(OUT, 'vendor'), { recursive: true });
  fs.copyFileSync(
    path.join(MODULES, 'lightweight-charts', 'dist', 'lightweight-charts.standalone.production.js'),
    path.join(OUT, CHART_LOCAL));
  vendorFonts();

  let pages = 0, fontPages = 0, cdnHits = 0;
  for (const name of fs.readdirSync(OUT)) {
    const file = path.join(OUT, name);
    if (/\.html$/.test(name)) {
      const { out, hadFonts } = rewriteHtml(fs.readFileSync(file, 'utf8'), name);
      pages++; if (hadFonts) fontPages++;
      cdnHits += (out.match(CHART_CDN) || []).length;
      fs.writeFileSync(file, out.replace(CHART_CDN, CHART_LOCAL));
    } else if (/\.js$/.test(name)) {
      const js = fs.readFileSync(file, 'utf8');
      const n = (js.match(CHART_CDN) || []).length;
      if (n) { cdnHits += n; fs.writeFileSync(file, js.replace(CHART_CDN, CHART_LOCAL)); }
    }
  }

  fs.copyFileSync(path.join(MOBILE, 'src', 'native.css'), path.join(OUT, 'native.css'));
  const pageNames = fs.readdirSync(OUT).filter((n) => /\.html$/.test(n)).sort();

  const info = { version: pkg.version, commit: commit(), built: new Date().toISOString() };
  await build({
    entryPoints: [path.join(MOBILE, 'src', 'bridge.js')],
    outfile: path.join(OUT, 'native-bridge.js'),
    bundle: true, format: 'iife', target: 'es2020',
    minify: true, legalComments: 'none',
    define: {
      __SITE_URL__: JSON.stringify(SITE_URL),
      __API_BASE__: JSON.stringify(API_BASE),
      __ROUTES__: JSON.stringify(routes()),
      __PAGES__: JSON.stringify(pageNames),
      __BUILD__: JSON.stringify(info),
    },
  });
  fs.writeFileSync(path.join(OUT, 'app-build.json'), JSON.stringify(info, null, 2) + '\n');

  // A page that still reaches for a CDN is a page that hangs with no signal.
  const leaks = [];
  for (const name of fs.readdirSync(OUT)) {
    if (!/\.(html|js|css)$/.test(name) || name === 'native-bridge.js') continue;
    const text = fs.readFileSync(path.join(OUT, name), 'utf8');
    if (/<(?:script|link)[^>]+(?:src|href)="https?:\/\/(?:unpkg\.com|cdn\.jsdelivr\.net|fonts\.googleapis\.com)/.test(text)) leaks.push(name);
  }
  if (leaks.length) throw new Error('still loading from a CDN: ' + leaks.join(', '));

  const files = fs.readdirSync(OUT, { recursive: true }).filter((f) => fs.statSync(path.join(OUT, f)).isFile());
  const bytes = files.reduce((s, f) => s + fs.statSync(path.join(OUT, f)).size, 0);
  console.log(`www: ${files.length} files, ${(bytes / 1048576).toFixed(1)} MB · ${pages} pages ` +
    `(${fontPages} with fonts) · ${cdnHits} chart-library links made local · ${info.commit || 'no commit'}`);
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });

#!/usr/bin/env node
/* check-theme.cjs — the theme guardrail. Runs in CI (.github/workflows/ci.yml).

   Fails when a stylesheet, a page or a script names a colour or a type size
   that is not a token from tokens.css:

     colour       a raw #hex, rgb(), rgba(), hsl() or hsla()
     font-size    anything but var(--fs-*)
     font-family  anything but var(--font-*)
     font-weight  anything but 400, 500 or 600
     line-height  anything but var(--lh-*)

   tokens.css is the one file allowed to write a value down. A line that has
   a real reason to break the rule says so on that line:

       ctx.font = '600 62px ' + F.display;   // theme-ok: canvas pixels of a 1200px export

   Usage: node frontend/tools/check-theme.cjs [--summary] [file ...] */
'use strict';
const fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const summary = args.includes('--summary');
const named = args.filter(a => !a.startsWith('--'));

const SKIP = new Set(['tokens.css']);
const files = (named.length ? named.map(f => path.resolve(f)) : fs.readdirSync(root)
  .filter(f => /\.(css|html|js)$/.test(f) && !/\.test\.js$/.test(f) && !SKIP.has(f))
  .map(f => path.join(root, f)));

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])/g;
const FUNC = /\b(?:rgba?|hsla?)\(\s*(?!var\()[^)]*\)/g;
const COLOURISH = /(colou?r|background|fill|stroke|border|shadow|outline|Style|stop)\b[^;{}]{0,40}$/i;

const problems = [];
function report(file, line, rule, text) {
  problems.push({ file: path.relative(path.resolve(root, '..'), file), line, rule, text: text.trim().slice(0, 110) });
}

/* A hex-looking token is a colour unless it is plainly something else: an
   element id in a selector or a URL fragment, an HTML entity, an anchor. */
function isColour(src, idx, tok, cssValue) {
  const before = src.slice(Math.max(0, idx - 48), idx);
  if (/&$/.test(before)) return false;                       // &#8377;
  if (/(href=["']|url\(\s*["']?|xlink:href=["'])$/.test(before)) return false;
  const body = tok.slice(1);
  if (cssValue) return true;
  // a whole string literal that is nothing but a hex: "#fff", '#0A0A0B'
  const q = src[idx - 1], after = src[idx + tok.length];
  if ((q === '"' || q === "'" || q === '`') && after === q && !/(querySelector(All)?|getElementById|closest|matches|href|hash)\s*[(=]\s*$/.test(before.slice(0, -1))) return true;
  if (/\d/.test(body) && /[a-fA-F]/.test(body) && body.length >= 6) return true;
  if (/^(\w)\1+$/.test(body) || /^\d+$/.test(body) && body.length >= 6) return COLOURISH.test(before) || body.length >= 6;
  if (body.length >= 6) return /[0-9]/.test(body) || COLOURISH.test(before);
  return COLOURISH.test(before);                             // #fff after "color:" yes, #add in a selector no
}

function lineOf(src, idx) { let n = 1; for (let i = 0; i < idx; i++) if (src.charCodeAt(i) === 10) n++; return n; }

function checkDecl(file, src, at, prop, value, lineText) {
  if (/theme-ok/.test(lineText)) return;
  const p = prop.toLowerCase(), v = value.replace(/!important/g, '').trim();
  const line = () => lineOf(src, at);
  if (p === 'font-size') {
    if (!/^(var\(--fs-[a-z0-9]+\)|inherit|0|1em|100%|initial|unset)$/.test(v) && !/[$+'"`{]/.test(v))
      report(file, line(), 'font-size', prop + ':' + value);
  } else if (p === 'font-family') {
    if (!/^(var\(--font-(display|sans|mono)\)|inherit|initial|unset)$/.test(v) && !/[$+{]/.test(v))
      report(file, line(), 'font-family', prop + ':' + value);
  } else if (p === 'font-weight') {
    if (!/^(400|500|600|inherit|normal|initial|unset)$/.test(v) && !/[$+'"`{]/.test(v))
      report(file, line(), 'font-weight', prop + ':' + value);
  } else if (p === 'line-height') {
    if (!/^(var\(--lh-[a-z0-9]+\)|inherit|normal|0|initial|unset)$/.test(v) && !/[$+'"`{]/.test(v))
      report(file, line(), 'line-height', prop + ':' + value);
  } else if (p === 'font') {
    if (v !== 'inherit' && !/[$+{]/.test(v) && !/^(italic\s+)?(400|500|600)\s+var\(--fs-[a-z0-9]+\)(\/(var\(--lh-[a-z0-9]+\)|inherit|normal))?\s+var\(--font-(display|sans|mono)\)$/.test(v))
      report(file, line(), 'font', prop + ':' + value);
  }
}

const DECL = /(?<![\w$.-])(font-size|font-family|font-weight|line-height|font)\s*:\s*([^;{}<>\n]+?)\s*(?=;|\}|"|'|`|$|\n|\\)/gm;

for (const file of files) {
  const raw = fs.readFileSync(file, 'utf8');
  const isCss = file.endsWith('.css');
  // comments are prose; blank them but keep the length so line numbers hold
  const blank = s => s.replace(/[^\n]/g, ' ');
  let src = raw.replace(/\/\*[\s\S]*?\*\//g, m => /theme-ok/.test(m) ? m : blank(m));
  if (!isCss) src = src.replace(/<!--[\s\S]*?-->/g, blank).replace(/(^|[^:'"`\\])\/\/[^\n]*/g, (m, a) => /theme-ok/.test(m) ? m : a + blank(m.slice(a.length)));
  const lines = raw.split('\n');
  const textOf = idx => lines[lineOf(src, idx) - 1] || '';

  // 1. raw colours
  for (const m of src.matchAll(HEX)) {
    const t = textOf(m.index);
    if (/theme-ok/.test(t)) continue;
    const cssValue = isCss && /:[^;{}]*$/.test(src.slice(Math.max(0, m.index - 200), m.index)) &&
                     !/[{}][^:;{}]*$/.test(src.slice(Math.max(0, m.index - 200), m.index));
    if (isColour(src, m.index, m[0], cssValue)) report(file, lineOf(src, m.index), 'colour', m[0] + '  ' + t);
  }
  for (const m of src.matchAll(FUNC)) {
    const t = textOf(m.index);
    if (/theme-ok/.test(t)) continue;
    if (/^(rgba?|hsla?)\(\s*$/.test(m[0])) continue;
    report(file, lineOf(src, m.index), 'colour', m[0] + '  ' + t);
  }
  for (const m of src.matchAll(/%23[0-9a-fA-F]{3,8}\b/g)) {
    if (!/theme-ok/.test(textOf(m.index))) report(file, lineOf(src, m.index), 'colour', m[0] + ' in a data URI');
  }

  // 2. type
  for (const m of src.matchAll(DECL)) {
    // in a script, `font: x` can be an object key; only a value that reads as CSS counts
    if (!isCss && !/px|pt|\bem\b|var\(|Inter|serif|mono|^\s*[1-9]00\s*$|^\s*\.?\d/.test(m[2])) continue;
    if (!isCss && /^[A-Za-z_$][\w$.]*\s*(\(|,|\)|$)/.test(m[2]) && !/^(inherit|normal|bold|italic)\b/.test(m[2])) continue;
    checkDecl(file, src, m.index, m[1], m[2], textOf(m.index));
  }
  if (!isCss) {
    for (const m of src.matchAll(/['"`](?:IBM Plex Mono|Instrument Serif|Georgia|Courier New)\b|\bfont(?:Size|Family)\s*[:=]\s*(?:\d|['"`])/g)) {
      if (!/theme-ok/.test(textOf(m.index))) report(file, lineOf(src, m.index), 'font', textOf(m.index));
    }
  }
}

if (summary) {
  const by = {};
  for (const p of problems) { by[p.file] = by[p.file] || {}; by[p.file][p.rule] = (by[p.file][p.rule] || 0) + 1; }
  for (const [f, r] of Object.entries(by).sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y) - Object.values(a[1]).reduce((x, y) => x + y)))
    console.log(f.padEnd(44), Object.entries(r).map(([k, v]) => k + ' ' + v).join(', '));
} else {
  for (const p of problems) console.log(`${p.file}:${p.line}  [${p.rule}]  ${p.text}`);
}
if (problems.length) {
  console.log(`\ncheck-theme: ${problems.length} value(s) that are not tokens. Use a token from frontend/tokens.css (see THEME.md).`);
  process.exit(1);
}
console.log(`check-theme: ${files.length} files, every colour and type size is a token.`);

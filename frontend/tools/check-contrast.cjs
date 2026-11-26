#!/usr/bin/env node
/* check-contrast.cjs — WCAG AA for the palette, both themes. Runs in CI.

   Reads the colours straight out of tokens.css and checks every pairing the
   design allows: each text colour on each surface it may sit on, the text on
   an accent fill, each chip's ink on its own tint, and the marks (focus ring,
   chart series) against the surface they are drawn on.

     4.5:1   text at reading sizes
     3:1     large text (24px, or 18.66px bold) and non-text marks

   Hairline borders are decorative and deliberately quiet; they are reported
   for the record and do not fail the run.

   Usage: node frontend/tools/check-contrast.cjs [--all]   (--all prints passes too) */
'use strict';
const fs = require('node:fs'), path = require('node:path');
const css = fs.readFileSync(path.join(__dirname, '..', 'tokens.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const all = process.argv.includes('--all');

function block(re) {
  const m = re.exec(css);
  if (!m) throw new Error('tokens.css: block not found ' + re);
  const out = {};
  for (const d of m[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[d[1]] = d[2].trim();
  return out;
}
const light = block(/:root\s*\{([\s\S]*?)\n\}/);
const dark = Object.assign({}, light, block(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/));

function parse(v) {
  let m;
  if ((m = /^#([0-9a-f]{6})$/i.exec(v))) return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16)).concat(1);
  if ((m = /^rgba?\(([^)]+)\)$/i.exec(v))) { const p = m[1].split(/[\s,\/]+/).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  return null;
}
const over = (f, b) => [0, 1, 2].map(i => f[i] * f[3] + b[i] * (1 - f[3])).concat(1);
const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const SURFACES = ['--bg', '--surface', '--surface-raised'];
const TEXT = ['--text-primary', '--text-secondary', '--text-muted', '--highlight-text', '--gain', '--loss', '--warning', '--info'];
const CHIPS = [['--highlight-text', '--highlight-subtle'], ['--text-primary', '--highlight-subtle'], ['--gain', '--gain-bg'],
               ['--loss', '--loss-bg'], ['--warning', '--warning-bg'], ['--info', '--info-bg']];
const MARKS = ['--highlight', '--focus-ring', '--accent', '--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6'];
const HAIRLINES = ['--border', '--border-strong'];

let failed = 0, checked = 0;
function run(name, t) {
  const col = n => { const c = parse(t[n]); if (!c) throw new Error(name + ': ' + n + ' is not a plain colour: ' + t[n]); return c; };
  const rows = [];
  const check = (fg, bg, need, note, under) => {
    // a translucent tint is judged where it lands: over the card, and over the raised surface
    let b = col(bg); if (b[3] < 1) b = over(b, col(under || '--surface'));
    let f = col(fg); if (f[3] < 1) f = over(f, b);
    const r = ratio(f, b), ok = r >= need;
    checked++; if (!ok && need) failed++;
    rows.push({ ok, text: `${ok ? ' ok ' : need ? 'FAIL' : 'note'}  ${r.toFixed(2).padStart(5)}:1  (needs ${need || '-'})  ${fg} on ${bg}${under ? ' over ' + under : ''}  ${note || ''}` });
  };
  for (const bg of SURFACES) for (const fg of TEXT) check(fg, bg, 4.5);
  check('--on-accent', '--accent', 4.5, 'primary button');
  check('--on-accent', '--accent-hover', 4.5, 'primary button, hover');
  for (const [fg, bg] of CHIPS) { check(fg, bg, 4.5, 'chip'); check(fg, bg, 4.5, 'chip', '--surface-raised'); }
  for (const fg of MARKS) check(fg, '--surface', 3, 'mark');
  for (const fg of ['--highlight', '--focus-ring', '--accent']) check(fg, '--bg', 3, 'mark');
  check('--highlight', '--surface', 3, 'hero figure (large text)');
  check('--highlight', '--bg', 3, 'hero figure (large text)');
  for (const fg of HAIRLINES) check(fg, '--surface', 0, 'hairline, decorative');
  console.log(`\n${name}`);
  for (const r of rows) if (all || !r.ok) console.log('  ' + r.text);
  const bad = rows.filter(r => !r.ok && !/^note/.test(r.text)).length;
  console.log(`  ${rows.length} pairs, ${bad} below AA`);
}
run('Light: Ivory and Navy', light);
run('Dark: Midnight and Cognac', dark);
if (failed) { console.log(`\ncheck-contrast: ${failed} pair(s) below WCAG AA.`); process.exit(1); }
console.log(`\ncheck-contrast: ${checked} pairs checked, all text and marks meet WCAG AA.`);

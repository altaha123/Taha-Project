# Theme: Navy and Cognac

The look of Altaha is defined once, in [`frontend/tokens.css`](frontend/tokens.css).
Everything else names a token. A raw hex, an `rgb()` or a font size that is not a
token fails CI (`node frontend/tools/check-theme.cjs`).

Light is "Ivory and Navy". Dark is "Midnight and Cognac". Think tailored suit and
leather briefcase: rich, restrained, uncrowded. No purple, no neon, no gradients
on chrome, no glow, no glass.

## Files

| File | What it is |
|---|---|
| `frontend/tokens.css` | Every colour, font, size, radius and spacing value. Loaded first on every page. The only file allowed to contain a raw value. |
| `frontend/theme.js` | Sets `data-theme` on `<html>` before first paint, owns the toggle, and hands token values to scripts (`AltahaTheme`). |
| `frontend/type.css` | The seven text roles. |
| `frontend/components.css` | Button, tab, table, card, chip, field, tooltip, skeleton. Loaded last. |
| `frontend/fonts/` | Fraunces, Inter and JetBrains Mono, self-hosted, `font-display: swap`, preloaded on every page, with metric-matched fallbacks so the swap moves nothing. |
| `frontend/tools/build-brand.py` | Recolours the logo mark and writes the favicon and app icons. |
| `docs/theme/` | Before and after screenshots. |
| `frontend/tools/check-theme.cjs` | The guardrail. |
| `frontend/tools/check-contrast.cjs` | WCAG AA check of every text and background pair in both modes. |

## Colour

Use the semantic name. Never the value.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F7F3EC` | `#080D1A` | The page |
| `--surface` | `#FFFFFF` | `#101828` | Cards |
| `--surface-raised` | `#FBF8F3` | `#172136` | Hover rows, inputs, dropdowns, modals, table headers |
| `--border` | `#E2D8C8` | `#222E45` | Hairlines |
| `--border-strong` | `#CDBFA8` | `#33415E` | Focused borders, the rule under a heading |
| `--text-primary` | `#0F1A30` | `#F2EADF` | Text. Navy, never black; ivory, never white |
| `--text-secondary` | `#5E6472` | `#A3AAB8` | Supporting text |
| `--text-muted` | `#676C77` | `#8791A3` | Labels, captions, axis text |
| `--accent` | `#14213D` | `#C47A3A` | Primary button, active nav, logo. Two or three per screen |
| `--accent-hover` | `#1E2F55` | `#D58C4C` | |
| `--on-accent` | `#F7F3EC` | `#080D1A` | Text on an accent fill, and only there |
| `--highlight` | `#A8642C` | `#E3A869` | Hero figures, the line under the active tab, icons of note |
| `--highlight-text` | `#8F5322` | `#E3A869` | Cognac at reading sizes: links, chip text, the active tab label |
| `--highlight-subtle` | `#F3E6D6` | cognac 12% | Selected rows, neutral chips |
| `--gain` / `--gain-bg` | `#2A7253` / `#E3F1EA` | `#6FCF97` / 12% | A rise. Data only |
| `--loss` / `--loss-bg` | `#B03A2E` / `#F6E3E0` | `#E8705E` / 12% | A fall. Data only |
| `--warning` / `--warning-bg` | `#8F5E12` / `#F6EBD6` | `#E0B054` / 12% | |
| `--info` / `--info-bg` | `#2F5D8A` / `#E3ECF4` | `#7FA7D9` / 12% | |
| `--focus-ring` | `#A8642C` | `#E3A869` | Focus outline and field border |
| `--chart-1` … `--chart-6` | cognac, navy, sage, sand, slate, rust | cognac, steel blue, sage, sand, slate, rust | Chart series, in this order |
| `--grid` | border at 50% | | Chart gridlines |
| `--wash`, `--wash-strong` | text at 4%, 8% | | A faint tint on any surface |
| `--scrim` | | | Behind a modal |
| `--ring` | 3px, focus ring at 20% | | Focus halo on a field |
| `--shadow-raised` | one soft shadow | `none` | Menus, modals, a card on hover. Nothing at rest |

Rules:

- **Accent is scarce.** `--accent` goes on the primary action, the active
  destination and the logo. `--highlight` goes on key numbers and the active
  tab underline. If a screen has more than three accent things, one is wrong.
- **Green and red are data.** Never decoration, and always with ▲ or ▼
  (`.chg-up`, `.chg-down`). Gain and loss colour the text in a table cell, not
  the cell.
- **`--on-accent` is only for text sitting on `--accent`.** Text on a card is
  `--text-primary`, `--text-secondary` or `--text-muted`.
- A tint over a surface is `color-mix(in srgb, var(--token) N%, transparent)`,
  not an `rgba()`.

### Where the palette differs from the brief, and why

Six values in the original brief did not meet WCAG AA and were adjusted:

| Token | Brief | Measured | Shipped | Now |
|---|---|---|---|---|
| Light `--text-muted` | `#8A8E98` | 3.0–3.3:1 | `#676C77` | 4.8–5.3:1 |
| Dark `--text-muted` | `#6F788A` | 3.6–4.4:1 | `#8791A3` | 5.1–6.1:1 |
| Light `--highlight` as small text | `#A8642C` | 3.8–4.6:1 | new `--highlight-text` `#8F5322` | 5.0–6.1:1 |
| Light `--gain` | `#2E7D5B` | 4.3:1 on `--gain-bg` | `#2A7253` | 5.0:1 |
| Light `--warning` | `#B7791F` | 3.3–3.6:1 | `#8F5E12` | 5.0–5.6:1 |
| Light chart sand | `#C9A97A` | 2.2:1 on white | `#A88752` | 3.4:1 |

`--highlight` itself is unchanged: it passes at the sizes it is used at
(large figures, 2px rules, icons). Hairline borders are 1.3–1.9:1 by design.

## Type

Fraunces for headings and hero figures. Inter for everything read. JetBrains
Mono for ticker symbols only. Nothing else is loaded.

| Role | Token | Size | Weight | Font | Line height | Use |
|---|---|---|---|---|---|---|
| display | `--fs-display` | 40px | 400 | Fraunces | 1.1 | Hero metrics: an index level, a portfolio value |
| h1 | `--fs-h1` | 30px | 500 | Fraunces | 1.2 | Page titles |
| h2 | `--fs-h2` | 22px | 500 | Fraunces | 1.25 | Section headings |
| h3 | `--fs-h3` | 16px | 600 | Inter | 1.3 | Card titles |
| body | `--fs-body` | 14px | 400 | Inter | 1.55 | Text |
| small | `--fs-small` | 13px | 400 | Inter | 1.5 | Secondary text |
| label | `--fs-label` | 11px | 500 | Inter | 1.4 | UPPERCASE, tracked `.08em`, muted |

Rules:

- Nothing is set at a size outside this table. The size decides the font:
  22px and up is Fraunces, 16px and down is Inter.
- Headings of 22px and up are tracked `var(--ls-heading)` (-0.01em).
- Hierarchy comes from size and colour, not weight. Nothing is heavier than
  600 and Fraunces is never heavier than 500.
- Figures are tabular everywhere (`font-variant-numeric: tabular-nums` on
  `body`).
- Text reads from the left. Numbers in tables sit on the right. Data is never
  centred.
- One exception: form fields use `--fs-input`, which is 14px on a desktop and
  16px at phone width or under a finger, because iOS zooms the page when a
  smaller field takes focus.

Classes for new markup: `.t-display`, `.t-h1`, `.t-h2`, `.t-h3`, `.t-body`,
`.t-small`, `.t-label`, `.t-ticker`.

## Shape and space

| Token | Value | Use |
|---|---|---|
| `--r-card` | 12px | Cards, modals, tooltips, dropdowns |
| `--r-control` | 8px | Inputs, buttons |
| `--r-pill` | 999px | The primary action, chips |
| `--r-xs` | 4px | Marks too small to be a control: a bar, a swatch |
| `--card-pad` | 24px (16px under 720px) | Card padding |
| `--gutter` | 32px (16px under 720px) | Page gutters |
| `--row-h` | 48px | Table rows |
| `--control-h` | 40px | Buttons |
| `--sp-1` … `--sp-16` | 4px … 64px | The 4px spacing grid |

- Borders are 1px hairlines in `--border`. No heavy outlines.
- No shadows in dark mode. In light mode there is one, `--shadow-raised`, for
  things that are actually raised.
- Spacing is on a 4px grid: every padding, margin and gap of 4px or more is
  a multiple of 4.
- Leave room. Sections are separated by `--sp-12`.

## Components

Defined in `frontend/components.css`.

| Component | Class | Notes |
|---|---|---|
| Primary button | `.btn-primary` | Accent fill, pill, 40px, weight 500. One per screen |
| Secondary button | `.btn-secondary` | Transparent, 1px `--border-strong` |
| Ghost button | `.btn-ghost` | Words only, cognac on hover |
| Tabs | `.tabs` > `.tab` | Cognac label and a 2px line when active. No filled pill tabs |
| Table | `table` | Label-style header on `--surface-raised`, 48px rows, hairlines between rows only, `.num` right-aligned |
| Card | `.card`, `.card-title`, `.card-meta` | Surface, hairline, 12px, 24px padding |
| Metric | `.metric`, `.metric-label`, `.metric-value`, `.metric-change` | Label on top, Fraunces figure, change below |
| Change | `.chg-up`, `.chg-down` | Colour plus ▲ or ▼ |
| Chip | `.chip`, `.badge` (+ `.gain`, `.loss`, `.warn`, `.info`) | Pill, 11px, weight 500 |
| Field | `.field`, or any `input`, `select`, `textarea` | Raised fill, hairline, cognac border and a 3px halo on focus |
| Overlay | `.tip`, `.menu`, `.modal` | Raised surface, `--border-strong`, 12px |
| Skeleton | `.skeleton` | A slow, faint pass of light |
| Section header | `.section-head` (+ `.ruled`) | 11px label, Fraunces h2, optional rule |

## Theme switching

- The default is the system preference. The sun and moon button in the header
  switches; the choice is kept in `localStorage` under `altaha-theme`.
- `theme.js` is a blocking script in `<head>`, so `data-theme` is set before
  anything paints.
- Colours cross-fade over 200ms when the theme is switched, not when a page
  loads.
- Charts redraw on the `altaha:theme` window event.

## Colours in scripts

Canvas and the chart libraries cannot read `var(--x)`. Ask `AltahaTheme`:

```js
var t = AltahaTheme.chart();
// t.series[0..5], t.fills[0..5] (15%, flat), t.gain, t.loss, t.grid, t.axis,
// t.text, t.surface, t.border, t.lineWidth (1.5), t.axisSize (11),
// t.fontSans, t.fontDisplay, t.fontMono

AltahaTheme.color('--gain');          // the value now
AltahaTheme.alpha('--border', 0.5);   // as rgba()
AltahaTheme.onChange(redraw);         // or listen for 'altaha:theme'
```

Chart rules: 1.5px lines; an area is its line colour at 15%, flat; gridlines
are `--border` at 50%; axis labels are `--text-muted` at 11px; candles and
volume use gain and loss.

SVG built as a string can name tokens directly: `stroke="var(--gain)"`.

## The guardrail

```bash
node frontend/tools/check-theme.cjs            # fails on a raw colour or type value
node frontend/tools/check-theme.cjs --summary  # counts by file
node frontend/tools/check-contrast.cjs         # WCAG AA, both modes
```

A line with a real reason to break the rule carries a `theme-ok:` comment
saying why, for example a canvas that draws a 1200px image in image pixels.

/* Node test for investor-pictures.js — run by CI, no browser needed.
 *
 * The page forgives everything this file refuses: a picture that does not
 * load removes itself and the initials show, so a wrong id, a missing file or
 * a moved host would never be seen as an error. It would be seen as a card
 * that quietly has no picture. And a photograph with no author beside it
 * breaks the licence it was published under without looking any different.
 *
 *  1. Every id is one backend/investors.py lists. The fixture read here is
 *     written by the real module (backend/tests/make_investors_fixture.py).
 *  2. A photograph is a file in assets/investors/ named for its id, small
 *     enough for a phone, and carries its author, licence and source.
 *  3. Nothing is linked from another server except a listed company's logo,
 *     from the one image host the wealth desk already uses.
 *  4. No file is left in assets/investors/ that nothing shows.
 */

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const PICTURES = require("./investor-pictures.js");
const FOLDER = "assets/investors";
const LOGO = /^https:\/\/images\.dhan\.co\/symbol\/[A-Z0-9&_-]+\.png$/;
const MAX_BYTES = 60 * 1024;

const directory = JSON.parse(fs.readFileSync(
  path.join(__dirname, "tests/fixtures/investors-directory.json"), "utf8"));
const known = new Set(directory.investors.map(i => i.id));
assert.ok(known.size > 20, "the investor fixture looks empty");

const shown = new Set();
for (const [id, pic] of Object.entries(PICTURES)) {
  assert.ok(known.has(id),
    `"${id}" is not an investor id in backend/investors.py (or is a redirect, which has no card)`);
  assert.ok(pic.kind === "photo" || pic.kind === "logo",
    `${id}: kind must be "photo" or "logo", not ${JSON.stringify(pic.kind)}`);
  assert.ok(typeof pic.src === "string" && pic.src, `${id}: no src`);

  if (/^[a-z]+:/i.test(pic.src) || pic.src.startsWith("//")) {
    assert.ok(pic.kind === "logo" && LOGO.test(pic.src),
      `${id}: ${pic.src} is linked from another server. Only a listed company's ` +
      `logo may be, from images.dhan.co/symbol/<NSE symbol>.png; keep anything ` +
      `else as a file in ${FOLDER}/`);
  } else {
    const m = pic.src.match(/^assets\/investors\/([a-z0-9-]+)\.(jpg|png|webp)$/);
    assert.ok(m && m[1] === id,
      `${id}: a kept picture is ${FOLDER}/${id}.jpg (or .png, .webp), not ${pic.src}`);
    const file = path.join(__dirname, pic.src);
    assert.ok(fs.existsSync(file), `${id}: ${pic.src} is not in the repository`);
    const bytes = fs.statSync(file).size;
    assert.ok(bytes > 0 && bytes <= MAX_BYTES,
      `${id}: ${pic.src} is ${bytes} bytes; a 256 px square should be under ${MAX_BYTES}`);
    shown.add(path.basename(pic.src));
  }

  if (pic.kind === "photo") {
    assert.ok(!/^[a-z]+:/i.test(pic.src), `${id}: a photograph is kept as a file`);
    for (const field of ["credit", "license", "source"]) {
      assert.ok(typeof pic[field] === "string" && pic[field].trim(),
        `${id}: a photograph needs its ${field}; the page prints it, and a free ` +
        `licence requires it`);
    }
    assert.ok(/^https:\/\//.test(pic.source),
      `${id}: source is the page the photograph was taken from, as an https link`);
    assert.ok(pic.license_url === undefined || /^https:\/\//.test(pic.license_url),
      `${id}: license_url, where there is one, is an https link to the licence`);
  }
}

// The same host the wealth desk draws its logos from. If that moves, this
// moves with it rather than being left pointing at the old one.
assert.ok(
  fs.readFileSync(path.join(__dirname, "wealth.js"), "utf8")
    .includes("https://images.dhan.co/symbol/"),
  "wealth.js no longer uses images.dhan.co for logos; move the logos here too");

const folder = path.join(__dirname, FOLDER);
const kept = fs.existsSync(folder) ? fs.readdirSync(folder) : [];
for (const name of kept) {
  assert.ok(shown.has(name),
    `${FOLDER}/${name} is not shown by any entry in investor-pictures.js`);
}

console.log(`investor pictures ok: ${Object.keys(PICTURES).length} on file, ` +
  `${kept.length} kept as files`);

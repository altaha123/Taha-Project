/* The Android launcher icon, after `capacitor-assets generate`.
 *
 * An Android icon is two layers: a background, and a foreground the launcher
 * may slide and scale over it. The generator shrinks BOTH into the middle
 * two-thirds, which leaves a ring of nothing round the background; the
 * launcher fills that ring with a colour of its own, and the first build of
 * this app had a teal halo because of it. The background has to cover the
 * whole icon, so here it is a plain colour: the site's page colour, which is
 * also the colour of the tile the mark is drawn on.
 *
 * `npm run icons` runs this for you.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const RES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..',
  'android', 'app', 'src', 'main', 'res');
const PAPER = '#FBFAF7';

const icon = `<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground>
        <inset android:drawable="@mipmap/ic_launcher_foreground" android:inset="16.7%" />
    </foreground>
</adaptive-icon>
`;
for (const name of ['ic_launcher.xml', 'ic_launcher_round.xml']) {
  fs.writeFileSync(path.join(RES, 'mipmap-anydpi-v26', name), icon);
}
fs.writeFileSync(path.join(RES, 'values', 'ic_launcher_background.xml'),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${PAPER}</color>\n</resources>\n`);
console.log('Android launcher icon: the background covers the whole icon.');

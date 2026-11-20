/* One version number for both apps.
 *
 *     npm run set-version -- 1.0.1
 *
 * Android reads "version" from package.json when it builds (android/app/build.gradle)
 * and works its whole-number build code out of it. Xcode has no such hook: the
 * version an iPhone shows lives in the project file, twice. This writes all of
 * them, so the two stores are never sent different numbers for the same build.
 *
 * Both stores refuse a build whose number is not higher than the last one they
 * were sent, so every upload needs a new version.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MOBILE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const version = process.argv[2] || '';
const m = /^(\d+)\.(\d{1,2})\.(\d{1,2})$/.exec(version);
if (!m) {
  console.error('Usage: npm run set-version -- 1.0.1   (three numbers; the last two below 100)');
  process.exit(1);
}
const code = Number(m[1]) * 10000 + Number(m[2]) * 100 + Number(m[3]);

for (const name of ['package.json', 'package-lock.json']) {
  const file = path.join(MOBILE, name);
  const json = JSON.parse(fs.readFileSync(file, 'utf8'));
  json.version = version;
  if (json.packages && json.packages['']) json.packages[''].version = version;
  fs.writeFileSync(file, JSON.stringify(json, null, 2) + '\n');
}

const project = path.join(MOBILE, 'ios', 'App', 'App.xcodeproj', 'project.pbxproj');
let pbx = fs.readFileSync(project, 'utf8');
const marketing = pbx.match(/MARKETING_VERSION = [^;]+;/g) || [];
const build = pbx.match(/CURRENT_PROJECT_VERSION = [^;]+;/g) || [];
if (marketing.length !== 2 || build.length !== 2) {
  console.error('The Xcode project no longer has the two version lines this expects. Nothing was changed there.');
  process.exit(1);
}
pbx = pbx.replace(/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${version};`)
         .replace(/CURRENT_PROJECT_VERSION = [^;]+;/g, `CURRENT_PROJECT_VERSION = ${code};`);
fs.writeFileSync(project, pbx);

console.log(`Both apps are now ${version} (build ${code}).`);

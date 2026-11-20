/* What the two browser tests share: a server that answers the way the app's
 * own does, and a stand-in for the phone.
 *
 * There is no phone in CI. What there is, is the exact bundle the apps ship
 * (mobile/www) and a real browser engine. The gap between that and a phone is
 * the native side of Capacitor, so this fakes exactly that and nothing above
 * it: the page finds window.androidBridge and a table of plugin methods, as
 * it would on Android, and every call it makes to the phone is recorded in
 * window.__native.calls instead of being carried out. The bridge under test
 * (src/bridge.js) is the real, bundled one.
 */
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const WWW = path.resolve(__dirname, '..', 'www');

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.md': 'text/plain; charset=utf-8',
};

/* Capacitor's local server: a file if there is one, and index.html for any
   address with no extension. That second rule is why /methodology has to be
   routed by the bridge: left alone it would quietly show the home page. */
function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (p === '/') p = '/index.html';
    let file = path.join(WWW, p);
    if (!file.startsWith(WWW)) { res.writeHead(403).end(); return; }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      if (path.extname(p)) { res.writeHead(404).end('not found'); return; }
      file = path.join(WWW, 'index.html');
    }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => {
    resolve({ server, origin: 'http://localhost:' + server.address().port });
  }));
}

/* Runs in the page before any of its scripts. */
function fakePhone() {
  const promise = (names) => names.map((name) => ({ name, rtype: 'promise' }));
  const listen = [{ name: 'addListener' }, { name: 'removeListener', rtype: 'promise' }];
  const calls = [], listeners = {};
  const results = {
    'Filesystem.writeFile': (o) => ({ uri: 'file:///data/cache/' + o.path }),
    'Network.getStatus': () => ({ connected: true, connectionType: 'wifi' }),
  };
  window.__native = {
    calls, listeners, results,
    emit(plugin, event, data) { (listeners[plugin + ':' + event] || []).forEach((cb) => cb(data)); },
    made(plugin, method) { return calls.filter((c) => c.plugin === plugin && c.method === method); },
  };
  window.androidBridge = { postMessage() {} };
  window.Capacitor = {
    PluginHeaders: [
      { name: 'App', methods: listen.concat(promise(['minimizeApp', 'exitApp', 'getInfo'])) },
      { name: 'Browser', methods: listen.concat(promise(['open', 'close'])) },
      { name: 'Filesystem', methods: promise(['writeFile', 'readFile', 'deleteFile', 'mkdir']) },
      { name: 'Haptics', methods: promise(['impact']) },
      { name: 'Network', methods: listen.concat(promise(['getStatus'])) },
      { name: 'Share', methods: promise(['share', 'canShare']) },
      { name: 'SplashScreen', methods: promise(['hide', 'show']) },
      { name: 'SystemBars', methods: promise(['setStyle', 'show', 'hide']) },
      { name: 'AltahaShell', methods: promise(['print', 'setBackground']) },
    ],
    nativePromise(plugin, method, options) {
      calls.push({ plugin, method, options });
      const r = results[plugin + '.' + method];
      try { return Promise.resolve(r ? r(options || {}) : undefined); }
      catch (e) { return Promise.reject(e); }
    },
    nativeCallback(plugin, method, options, callback) {
      if (method === 'addListener') {
        const key = plugin + ':' + options.eventName;
        (listeners[key] = listeners[key] || []).push(callback);
      }
      return Promise.resolve(plugin + ':' + method);
    },
  };
  // Android's web view has no Web Share. Desktop Chromium on some systems does.
  try { delete Navigator.prototype.share; delete Navigator.prototype.canShare; } catch (e) {}
}

const PAGES = fs.existsSync(WWW) ? fs.readdirSync(WWW).filter((n) => /\.html$/.test(n)).sort() : [];

module.exports = { WWW, PAGES, serve, fakePhone };

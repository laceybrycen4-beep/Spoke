// Spoke app-shell cache: lets the app open with no signal once it has been opened online.
// Map tiles are cached separately by the page (IndexedDB), so this file stays small.
const CACHE = 'spoke-shell-v7';
const SHELL = [
  './', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png',
  'https://unpkg.com/maplibre-gl@5.23.0/dist/maplibre-gl.js',
  'https://unpkg.com/maplibre-gl@5.23.0/dist/maplibre-gl.css'
];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, url = req.url;
  if (req.method !== 'GET') return;
  if (req.mode === 'navigate') {            // always try for the newest app first
    e.respondWith(fetch(req).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put('./index.html', c)); return r; })
      .catch(() => caches.match('./index.html')));
    return;
  }
  if (SHELL.includes(url) || url.startsWith('https://fonts.googleapis.com/') || url.startsWith('https://fonts.gstatic.com/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put(req, c)); return r; })));
  }
});

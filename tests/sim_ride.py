"""Spoke end-to-end ride simulation.

Run:  python3 tests/sim_ride.py [path/to/index.html]
Needs: pip install playwright (Chromium or Chrome). Optional: MAPLIBRE_DIR=/path/to/maplibre-gl/dist
to exercise the real map; otherwise the map library is stubbed and the canvas fallback is used.

What it checks (exit code 1 on any failure):
  1. Page loads with no JavaScript errors.
  2. A simulated 130 s GPS ride at a known speed records distance within 3% of the truth.
  3. Ending the ride opens Confirm-with-Garmin; entering Garmin numbers updates calibration.
  4. Backup writes rides/, tracks/ and calibration.json to a mocked private GitHub repo.
  5. After calibration, a second ride's distance is closer to the Garmin number than the first.
  6. Voice navigation: on a loaded GPX route with a right turn, Spoke speaks a "turn right" prompt.
  7. Ride tracks are stored (IndexedDB) and the ride summary card opens after a ride.
Prints a JSON summary on the last line for the weekly agent to read.
"""
import asyncio, base64, json, math, os, sys
from playwright.async_api import async_playwright

HTML = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'index.html'))
ML = os.environ.get('MAPLIBRE_DIR')
SPEED = 13.0      # m/s true speed
SECONDS = 130     # ride length per simulated ride
GARMIN_BIAS = 0.97  # pretend Garmin measured 3% less than true GPS distance (forces calibration to act)

def path_points(n, lat0=32.78, lon0=-96.80):
    pts = []
    for i in range(n + 1):
        d = SPEED * i
        pts.append((lat0 + d / 111320.0, lon0))
    return pts

async def ride(pg, ctx, start_idx=0):
    pts = path_points(SECONDS + 5)
    await ctx.set_geolocation({'latitude': pts[0][0], 'longitude': pts[0][1], 'accuracy': 5})
    await pg.wait_for_timeout(1200)
    await pg.click('#bStart')
    for i in range(1, SECONDS + 1):
        await ctx.set_geolocation({'latitude': pts[i][0], 'longitude': pts[i][1], 'accuracy': 5})
        await pg.wait_for_timeout(1000)
    dist_txt = await pg.evaluate("document.getElementById('dist').textContent")
    # unlock (auto-lock on start), then End twice to save
    box = await pg.query_selector('#bLock')
    await box.dispatch_event('pointerdown'); await pg.wait_for_timeout(1000); await box.dispatch_event('pointerup')
    await pg.wait_for_timeout(700)
    await pg.click('#bEnd'); await pg.click('#bEnd'); await pg.wait_for_timeout(600)
    return float(dist_txt)

async def main():
    fails, store, errs = [], {}, []
    async with async_playwright() as p:
        exe = '/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        b = await p.chromium.launch(executable_path=exe, args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, permissions=['geolocation'],
                                  geolocation={'latitude': 32.78, 'longitude': -96.80, 'accuracy': 5})
        pg = await ctx.new_page()
        pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.add_init_script("window.__said=[]; if(window.speechSynthesis){ speechSynthesis.speak=u=>window.__said.push(u.text); speechSynthesis.cancel=()=>{}; }")

        async def cdn(route):
            u = route.request.url
            if ML and u.endswith('.js'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.js'))
            if ML and u.endswith('.css'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.css'))
            await route.fulfill(body='', content_type='text/css' if u.endswith('.css') else 'application/javascript')
        await pg.route('https://unpkg.com/**', cdn)
        await pg.route('https://fonts.googleapis.com/**', lambda r: r.fulfill(body='', content_type='text/css'))
        await pg.route('https://tiles.openfreemap.org/**', lambda r: r.fulfill(body='{"version":8,"sources":{},"layers":[]}', content_type='application/json'))

        async def github(route):
            req, u = route.request, route.request.url
            path = u.split('/contents/', 1)[1] if '/contents/' in u else ''
            if not path:
                return await route.fulfill(json={'full_name': 'test/spoke-data', 'private': True, 'permissions': {'push': True}})
            if req.method == 'PUT':
                body = json.loads(req.post_data); store[path] = json.loads(base64.b64decode(body['content']).decode())
                return await route.fulfill(status=201, json={'content': {'sha': 'x'}})
            if path in store:
                return await route.fulfill(json={'sha': 'x', 'name': path})
            return await route.fulfill(status=404, json={'message': 'Not Found'})
        await pg.route('https://api.github.com/**', github)

        await pg.goto('file://' + HTML); await pg.wait_for_timeout(1500)
        if errs: fails.append('load errors: ' + '; '.join(errs))

        # backup setup
        await pg.click('nav button[data-v=set]')
        await pg.fill('#bkTok', 'test-token'); await pg.dispatch_event('#bkTok', 'change')
        await pg.click('#bkTest'); await pg.wait_for_timeout(800)
        await pg.click('nav button[data-v=ride]')

        truth_km = SPEED * SECONDS / 1000
        d1 = await ride(pg, ctx)
        mi = await pg.evaluate("document.querySelector('.uDist').textContent") == 'mi'
        d1_km = d1 * 1.609344 if mi else d1
        err1 = (d1_km - truth_km) / truth_km * 100
        if abs(err1) > 3: fails.append(f'ride 1 distance {d1_km:.3f} km vs truth {truth_km:.3f} km ({err1:+.1f}%)')

        # summary card -> Garmin confirm
        if not await pg.is_visible('#sGpx'): fails.append('ride summary card did not open after ride')
        else: await pg.click('#sCf'); await pg.wait_for_timeout(300)
        if not await pg.is_visible('#gSave'): fails.append('Garmin compare form did not open')
        ntrk = await pg.evaluate("new Promise(r=>{const q=indexedDB.open('spoke');q.onsuccess=()=>{const t=q.result.transaction('kv').objectStore('kv').getAllKeys();t.onsuccess=()=>r(t.result.filter(k=>String(k).startsWith('trk_')).length)}})")
        if ntrk < 1: fails.append('ride track was not stored in IndexedDB')
        garmin_km = truth_km * GARMIN_BIAS
        await pg.fill('#gDist', f'{(garmin_km / 1.609344 if mi else garmin_km):.3f}')
        await pg.fill('#gMov', f'0:{SECONDS // 60:02d}:{SECONDS % 60:02d}')
        await pg.click('#gSave'); await pg.wait_for_timeout(600)
        cal = await pg.evaluate("JSON.parse(localStorage.getItem('rc_cal'))")
        if not cal or cal.get('n') != 1: fails.append('calibration did not record the confirmed ride')
        if cal and not cal.get('kGps', 1) < 1: fails.append(f"GPS factor did not move toward Garmin (kGps={cal.get('kGps')})")
        await pg.click('#gOk')
        await pg.wait_for_timeout(2500)
        for need in ('calibration.json',):
            if need not in store: fails.append(f'backup missing {need}')
        if not any(k.startswith('rides/') for k in store): fails.append('backup missing rides/*.json')
        if not any(k.startswith('tracks/') for k in store): fails.append('backup missing tracks/*.json')

        # ride 2: calibrated distance should be closer to Garmin
        d2 = await ride(pg, ctx)
        d2_km = d2 * 1.609344 if mi else d2
        e1, e2 = abs(d1_km - garmin_km), abs(d2_km - garmin_km)
        if await pg.is_visible('#sDone'): await pg.click('#sDone')
        # voice navigation on a route with a right turn
        import tempfile
        lat0, lon0 = 32.79, -96.79
        route = [(lat0 + 13*i/111320.0, lon0) for i in range(33)]
        route += [(route[-1][0], lon0 + 13*i/(111320.0*math.cos(math.radians(lat0)))) for i in range(1, 33)]
        gpx = '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Turn test</name><trkseg>' + \
              ''.join(f'<trkpt lat="{x:.6f}" lon="{y:.6f}"></trkpt>' for x, y in route) + '</trkseg></trk></gpx>'
        gp = os.path.join(tempfile.mkdtemp(), 'turn.gpx'); open(gp, 'w').write(gpx)
        await pg.set_input_files('#rtFile', gp); await pg.wait_for_timeout(500)
        await pg.evaluate("window.__said=[]")
        for la, lo in route[:45]:
            await ctx.set_geolocation({"latitude": la, "longitude": lo, "accuracy": 5}); await pg.wait_for_timeout(1000)
        said = await pg.evaluate("window.__said")
        if not any('turn right' in t.lower() for t in said): fails.append(f'no spoken "turn right" prompt on the route (said: {said})')
        if not e2 < e1: fails.append(f'calibration did not reduce error vs Garmin (ride1 off {e1:.3f} km, ride2 off {e2:.3f} km)')
        if errs: fails.append('runtime errors: ' + '; '.join(errs))
        await b.close()

    summary = {'ok': not fails, 'fails': fails, 'truth_km': round(truth_km, 3), 'ride1_km': round(d1_km, 3),
               'ride1_err_pct': round(err1, 2), 'garmin_km': round(garmin_km, 3), 'ride2_km': round(d2_km, 3),
               'backup_files': sorted(store.keys()), 'spoken': said}
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails))
    print(json.dumps(summary))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

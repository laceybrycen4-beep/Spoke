"""Spoke navigation checks: offline map cache, climb mode, GPS speed spike filtering.

Run:  python3 tests/sim_nav.py [path/to/index.html]   (needs MAPLIBRE_DIR=/path/to/maplibre-gl/dist)
Exit code 1 on failure; last line is a JSON summary.
"""
import asyncio, json, math, os, sys, tempfile
from playwright.async_api import async_playwright

HTML = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'index.html'))
ML = os.environ.get('MAPLIBRE_DIR')
LAT0, LON0 = 32.80, -96.75
def north(m): return m / 111320.0

STYLE = {"version": 8, "sources": {"openmaptiles": {"type": "vector", "url": "https://tiles.openfreemap.org/planet"}},
         "glyphs": "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
         "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#dfe6ee"}},
                    {"id": "w", "type": "fill", "source": "openmaptiles", "source-layer": "water", "paint": {"fill-color": "#9cf"}}]}
TILEJSON = {"tiles": ["https://tiles.openfreemap.org/planet/v1/{z}/{x}/{y}.pbf"], "minzoom": 0, "maxzoom": 14}

def route_gpx():
    pts = []
    for i in range(0, 161):                       # 4 km north: flat 2.5 km, climb 1.0 km +70 m, then flat
        d = i * 25
        ele = 150 + (0 if d < 2500 else min(70, (d - 2500) * 0.07))
        pts.append((LAT0 + north(d), LON0, ele))
    body = ''.join(f'<trkpt lat="{a:.6f}" lon="{b:.6f}"><ele>{e:.1f}</ele></trkpt>' for a, b, e in pts)
    return '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Climb test</name><trkseg>' + body + '</trkseg></trk></gpx>', pts

async def main():
    fails, net = [], {'tiles': 0, 'offline_tile_requests': 0}
    offline = {'on': False}
    gpx, pts = route_gpx()
    gp = os.path.join(tempfile.mkdtemp(), 'climb.gpx'); open(gp, 'w').write(gpx)
    async with async_playwright() as p:
        exe = '/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        b = await p.chromium.launch(executable_path=exe, args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, permissions=['geolocation'],
                                  geolocation={'latitude': LAT0, 'longitude': LON0, 'accuracy': 5})
        await ctx.add_init_script("window.__said=[]; if(window.speechSynthesis){ speechSynthesis.speak=u=>window.__said.push(u.text); speechSynthesis.cancel=()=>{}; }")
        errs = []

        async def cdn(route):
            u = route.request.url
            if ML and u.endswith('.js'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.js'))
            if ML and u.endswith('.css'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.css'))
            await route.fulfill(body='', content_type='application/javascript')
        async def ofm(route):
            u = route.request.url
            if offline['on']:
                if '/planet/v1/' in u: net['offline_tile_requests'] += 1
                return await route.abort()
            h = {'Access-Control-Allow-Origin': '*'}
            if '/styles/' in u: return await route.fulfill(json=STYLE, headers=h)
            if u.rstrip('/').endswith('/planet'): return await route.fulfill(json=TILEJSON, headers=h)
            if '/planet/v1/' in u: net['tiles'] += 1; return await route.fulfill(body=b'', headers=h, content_type='application/x-protobuf')
            return await route.fulfill(body=b'', headers=h)
        await ctx.route('https://unpkg.com/**', cdn)
        await ctx.route('https://fonts.googleapis.com/**', lambda r: r.fulfill(body='', content_type='text/css'))
        await ctx.route('https://tiles.openfreemap.org/**', ofm)

        pg = await ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto('file://' + HTML); await pg.wait_for_timeout(1200)

        # load climb route, check climb detection
        await pg.click('nav button[data-v=map]'); await pg.wait_for_timeout(2500)
        await pg.click('#bRoute'); await pg.set_input_files('#rtFile', gp); await pg.wait_for_timeout(800)
        await pg.click('#bRoute'); await pg.wait_for_timeout(300)
        prof = await pg.inner_text('#rtProf')
        if 'Climb 1' not in prof: fails.append(f'climb not detected in route profile: {prof[:120]!r}')

        # offline download of the route corridor
        await pg.click('#offSave'); await pg.wait_for_timeout(500)
        await pg.click('#ofGo')
        for _ in range(60):
            await pg.wait_for_timeout(500)
            if 'Saved:' in await pg.inner_text('#offInfo'): break
        info = await pg.inner_text('#offInfo')
        if 'Saved:' not in info: fails.append(f'offline save did not finish: {info!r}')
        await pg.click('#rtClose')

        # go offline, reload, map must load style + tiles from the phone cache
        offline['on'] = True
        await pg.reload(); await pg.wait_for_timeout(1000)
        await pg.click('nav button[data-v=map]'); await pg.wait_for_timeout(3000)
        toast = await pg.inner_text('#toast')
        if 'not saved offline' in toast: fails.append('offline reload: style not available from cache')
        if net['offline_tile_requests'] > 0: fails.append(f"offline reload still requested {net['offline_tile_requests']} tiles from the network")

        # climb mode: ride into the climb
        await pg.click('nav button[data-v=ride]')
        for d in range(2000, 2800, 25):
            await ctx.set_geolocation({'latitude': LAT0 + north(d), 'longitude': LON0, 'accuracy': 5}); await pg.wait_for_timeout(250)
        card = await pg.inner_text('#climbRide')
        if 'Climb 1 of 1' not in card: fails.append(f'climb card not shown on the climb: {card!r}')
        said = await pg.evaluate('window.__said')
        if not any('climb ahead' in t.lower() for t in said): fails.append(f'no spoken climb warning (said: {said})')

        # GPS spike: steady 10 m/s, one 300 m glitch, max speed must stay sane
        for _ in range(14):   # stand still so the speed filter settles after the fast climb replay
            await ctx.set_geolocation({'latitude': LAT0 + north(2800), 'longitude': LON0, 'accuracy': 5}); await pg.wait_for_timeout(1000)
        await pg.click('#bStart')
        base = 2800
        for i in range(25):
            lat = LAT0 + north(base + 10 * i); lon = LON0 + (0.0032 if i == 15 else 0)
            await ctx.set_geolocation({'latitude': lat, 'longitude': lon, 'accuracy': 5}); await pg.wait_for_timeout(1000)
        mx = float(await pg.inner_text('#maxSpd'))
        mi = (await pg.inner_text('.uSpd')) == 'mph'
        true_v = 10 * 3.6 / (1.609344 if mi else 1)
        if mx > true_v * 1.35: fails.append(f'GPS glitch inflated max speed to {mx} (true {true_v:.1f})')
        if errs: fails.append('page errors: ' + '; '.join(errs))
        await pg.screenshot(path=os.path.join(tempfile.gettempdir(), 'spoke_nav.png'))
        await b.close()
    summary = {'ok': not fails, 'fails': fails, 'route_profile': prof[:160], 'offline_info': info, 'climb_card': card[:120],
               'max_speed': mx, 'true_speed': round(true_v, 1), 'spoken': said}
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails)); print(json.dumps(summary))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

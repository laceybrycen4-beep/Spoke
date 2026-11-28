"""Spoke insights + share check.

Run:  python3 tests/sim_insights.py
Seeds 7 synthetic 5 km runs (newest is the fastest, with a negative split), opens the newest
activity and checks the PR, pacing, zone and trend insights, then builds a share image and
checks it reaches the share sheet as a 1080x1920 PNG.
"""
import asyncio, json, os, sys, time, math
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def make_run(day_offset, v1, v2, hr1, hr2, lat0=32.83, lon0=-96.78):
    start = int(time.time()*1000) - day_offset*86400000
    pts, d, t = [], 0.0, start
    while d < 5200:
        v = v1 if d < 2600 else v2
        hr = hr1 if d < 2600 else hr2
        ang = d / 900.0
        pts.append({'t': t, 'lat': lat0 + (math.sin(ang)*500)/111320, 'lon': lon0 + (math.cos(ang)*500 - 500)/(111320*math.cos(math.radians(lat0))), 'ele': 150, 'hr': hr, 'pw': None, 'cad': None})
        d += v; t += 1000
    dist_km = 5.2
    moving = len(pts)
    summ = {'id': start, 'sport': 'run', 'dist': dist_km, 'distRaw': dist_km, 'rawGps': dist_km, 'rawWheel': 0, 'moving': moving, 'elapsed': moving,
            'avgSpd': dist_km/(moving/3600), 'maxSpd': max(v1, v2)*3.6, 'gain': 20, 'avgHr': round((hr1+hr2)/2), 'avgPw': None, 'np': None, 'kj': 0, 'laps': 0,
            'hasTrack': True, 'backed': True, 'trackBacked': True}
    return summ, pts

async def main():
    fails, errs, shared = [], [], {}
    runs = []
    for k, (v1, v2) in enumerate([(3.0,3.0),(3.05,3.0),(3.1,3.05),(3.0,3.1),(3.15,3.1),(3.2,3.15),(3.45,3.6)]):
        runs.append(make_run(9-k, v1, v2, 148 if k<6 else 150, 150 if k<6 else 154))
    rides = [r for r, _ in reversed(runs)]
    async with async_playwright() as p:
        exe = '/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        b = await p.chromium.launch(executable_path=exe)
        ctx = await b.new_context(viewport={'width': 390, 'height': 844})
        await ctx.add_init_script("""window.__shared=null; navigator.canShare=()=>true; navigator.share=async (d)=>{ const f=d.files[0]; const bm=await createImageBitmap(f); window.__shared={type:f.type, size:f.size, name:f.name, w:bm.width, h:bm.height}; };""")
        await ctx.route('https://**', lambda r: r.fulfill(body='', content_type='text/plain'))
        pg = await ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto('file://' + ROOT + '/index.html'); await pg.wait_for_timeout(800)
        await pg.evaluate("rides => localStorage.setItem('rc_rides', JSON.stringify(rides))", rides)
        await pg.evaluate("""tracks => new Promise(res=>{ const q=indexedDB.open('spoke',1); q.onupgradeneeded=()=>q.result.createObjectStore('kv');
            q.onsuccess=()=>{ const tx=q.result.transaction('kv','readwrite'); for(const [id,pts] of tracks) tx.objectStore('kv').put(pts,'trk_'+id); tx.oncomplete=()=>res(true); }; })""",
            [[r['id'], pts] for r, pts in runs])
        await pg.reload(); await pg.wait_for_timeout(800)
        await pg.click('nav button[data-v=act]'); await pg.wait_for_timeout(1500)
        await pg.click('#hist .act .ah'); await pg.wait_for_timeout(2500)
        txt = await pg.inner_text('#mbox')
        for need in ('New PR: fastest 5K', 'Negative split', 'Last 4 runs average', 'Best efforts', 'Heart-rate zones'):
            if need not in txt: fails.append(f'insights missing: {need!r}')
        if 'PR' not in await pg.inner_text('#mbox .ibe'): fails.append('PR badge not shown on best efforts')
        await pg.screenshot(path='/tmp/spoke_insights.png', full_page=False)
        await pg.click('#aShare'); await pg.wait_for_timeout(1500)
        await pg.click('#shTpl button[data-t=map]'); await pg.wait_for_timeout(800)
        await pg.screenshot(path='/tmp/spoke_share.png')
        await pg.click('#shGo'); await pg.wait_for_timeout(1500)
        shared = await pg.evaluate('window.__shared')
        if not shared or shared.get('type') != 'image/png' or shared.get('w') != 1080 or shared.get('h') != 1920: fails.append(f'share image wrong: {shared}')
        if errs: fails.append('page errors: ' + '; '.join(errs))
        await b.close()
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails))
    print(json.dumps({'ok': not fails, 'fails': fails, 'shared': shared}))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

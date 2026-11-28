"""Spoke run mode check.

Run:  python3 tests/sim_run.py
Switches to Run, checks the coach picks running workouts, runs ~1.2 km (metric) and checks
pace display, the spoken 1 km split, and that the saved activity is a run with pace.
"""
import asyncio, json, os, sys
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LAT0, LON0 = 32.82, -96.77
V = 8.0   # m/s, kept under the 30 km/h run cap so the GPS filter accepts it

async def main():
    fails, errs = [], []
    async with async_playwright() as p:
        exe = '/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        b = await p.chromium.launch(executable_path=exe)
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, permissions=['geolocation'],
                                  geolocation={'latitude': LAT0, 'longitude': LON0, 'accuracy': 5})
        await ctx.add_init_script("window.__said=[]; if(window.speechSynthesis){ speechSynthesis.speak=u=>window.__said.push(u.text); speechSynthesis.cancel=()=>{}; }")
        await ctx.route('https://**', lambda r: r.fulfill(body='', content_type='text/plain'))
        pg = await ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto('file://' + ROOT + '/index.html'); await pg.wait_for_timeout(900)
        await pg.click('nav button[data-v=set]'); await pg.select_option('#units', 'met'); await pg.click('nav button[data-v=ride]')
        await pg.click('#v-ride .sportsel button[data-sp=run]'); await pg.wait_for_timeout(300)
        if (await pg.inner_text('#spdL')) != 'Pace': fails.append('speed tile not switched to Pace in Run mode')

        # coach in run mode
        await pg.click('nav button[data-v=wk]')
        names = await pg.inner_text('#wkList')
        if 'Easy run' not in names or 'Sweet spot' in names: fails.append('workout list not filtered to running')
        await pg.select_option('#cFeel', 'tired'); await pg.click('#coachGo'); await pg.wait_for_timeout(100)
        if 'Recovery jog' not in await pg.inner_text('#coachOut'): fails.append('coach did not pick a recovery jog for a tired runner')
        await pg.select_option('#cFeel', 'normal'); await pg.select_option('#cGoal', 'faster'); await pg.click('#coachGo'); await pg.wait_for_timeout(100)
        if 'Intervals 6' not in await pg.inner_text('#coachOut'): fails.append('coach did not pick running intervals')
        await pg.click('nav button[data-v=ride]')

        # run ~1.25 km
        for _ in range(3):
            await ctx.set_geolocation({'latitude': LAT0, 'longitude': LON0, 'accuracy': 5}); await pg.wait_for_timeout(1000)
        await pg.click('#bStart')
        d = 0.0; pace_seen = None
        for i in range(1, 160):
            d += min(V, 2.0 * i)
            await ctx.set_geolocation({'latitude': LAT0 + d / 111320, 'longitude': LON0, 'accuracy': 5}); await pg.wait_for_timeout(1000)
            if i == 40: pace_seen = await pg.inner_text('#spd') + ' ' + await pg.inner_text('#spdU')
        said = await pg.evaluate('window.__said')
        if not any('kilometer 1' in t.lower() for t in said): fails.append(f'no spoken 1 km split (said: {said})')
        if not pace_seen or not pace_seen.endswith('/km') or not pace_seen.startswith('2:0'): fails.append(f'pace display wrong at 8 m/s (expected ~2:05 /km): {pace_seen!r}')
        box = await pg.query_selector('#bLock'); await box.dispatch_event('pointerdown'); await pg.wait_for_timeout(1000); await box.dispatch_event('pointerup')
        await pg.wait_for_timeout(500); await pg.click('#bEnd'); await pg.click('#bEnd'); await pg.wait_for_timeout(800)
        saved = await pg.evaluate("(JSON.parse(localStorage.getItem('rc_rides'))||[])[0]")
        if not saved or saved.get('sport') != 'run': fails.append('activity not saved as a run')
        if not saved or not saved.get('splits'): fails.append('splits not saved with the run')
        if await pg.is_visible('#sDone'): await pg.click('#sDone')
        await pg.click('nav button[data-v=act]'); await pg.wait_for_timeout(500)
        card = await pg.inner_text('#hist')
        if ' run' not in card.lower() or 'Pace' not in card: fails.append(f'activity card not shown as a run with pace: {card[:120]!r}')
        if errs: fails.append('page errors: ' + '; '.join(errs))
        await b.close()
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails))
    print(json.dumps({'ok': not fails, 'fails': fails, 'pace_at_8ms': pace_seen, 'spoken': [t for t in said if 'ilometer' in t]}))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

"""Spoke workouts + coach check (time-compressed with ?wkscale=0.02).

Run:  python3 tests/sim_workout.py
Checks the coach's picks for three situations, then rides the VO2 workout end to end:
spoken step cues, automatic laps per step, completion, and the workout in the ride summary.
"""
import asyncio, json, os, sys, time
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LAT0, LON0 = 32.81, -96.76

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
        await pg.goto('file://' + ROOT + '/index.html?wkscale=0.02'); await pg.wait_for_timeout(1000)
        await pg.click('nav button[data-v=wk]')

        async def coach(t, feel, goal):
            await pg.select_option('#cTime', t); await pg.select_option('#cFeel', feel); await pg.select_option('#cGoal', goal)
            await pg.click('#coachGo'); await pg.wait_for_timeout(150)
            return await pg.inner_text('#coachOut')
        out = await coach('60', 'tired', 'faster')
        if 'Recovery' not in out: fails.append(f'tired rider was not given recovery: {out[:80]!r}')
        out = await coach('60', 'normal', 'faster')
        if 'VO2' not in out: fails.append(f'rested rider wanting speed did not get VO2: {out[:80]!r}')
        yesterday = int(time.time() * 1000) - 20 * 3600 * 1000
        await pg.evaluate(f"localStorage.setItem('rc_rides', JSON.stringify([{{id:{yesterday}, dist:40, moving:5400, avgHr:160, gain:300, avgSpd:26}}]))")
        out = await coach('60', 'normal', 'faster')
        if 'Zone 2' not in out: fails.append(f'hard ride yesterday did not lead to an easy day: {out[:80]!r}')
        await pg.evaluate("localStorage.setItem('rc_rides','[]')")
        await coach('60', 'normal', 'faster')

        # ride the coach's VO2 pick
        await pg.click('#coachOut button[data-wk="vo2"]'); await pg.wait_for_timeout(200)
        if 'VO2' not in await pg.inner_text('#wkSel'): fails.append('workout not shown as selected')
        await pg.click('nav button[data-v=ride]')
        if not await pg.is_visible('#wkRide.on'): fails.append('workout panel not shown before start')
        await pg.click('#bStart')
        for i in range(1, 80):
            await ctx.set_geolocation({'latitude': LAT0 + 8 * i / 111320, 'longitude': LON0, 'accuracy': 5}); await pg.wait_for_timeout(1000)
            if i == 25: mid = await pg.inner_text('#wkRide')
        said = await pg.evaluate('window.__said')
        laps = await pg.evaluate("document.querySelectorAll('#lapList .r').length - 1")
        for need in ('Workout: VO2', 'Interval 1 of 5', 'Interval 5 of 5', 'Workout complete'):
            if not any(need.lower() in t.lower() for t in said): fails.append(f'missing spoken cue: {need!r}')
        if laps < 10: fails.append(f'expected an automatic lap per step, got {laps}')
        if 'Zone' not in mid and 'Recover' not in mid: fails.append(f'workout panel mid-ride looks wrong: {mid!r}')
        await pg.screenshot(path='/tmp/spoke_wk_end.png')
        box = await pg.query_selector('#bLock'); await box.dispatch_event('pointerdown'); await pg.wait_for_timeout(1000); await box.dispatch_event('pointerup')
        await pg.wait_for_timeout(500); await pg.click('#bEnd'); await pg.click('#bEnd'); await pg.wait_for_timeout(600)
        saved = await pg.evaluate("(JSON.parse(localStorage.getItem('rc_rides'))||[])[0] || null")
        if not saved or not saved.get('wk') or 'VO2' not in saved['wk'].get('name',''): fails.append(f'workout not saved with the ride: {saved and saved.get("wk")!r}')
        elif not saved['wk'].get('done'): fails.append('saved workout not marked complete')
        if errs: fails.append('page errors: ' + '; '.join(errs))
        await b.close()
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails))
    print(json.dumps({'ok': not fails, 'fails': fails, 'laps': laps, 'spoken': said[:12]}))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

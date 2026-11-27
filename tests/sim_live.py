"""Spoke live tracking + SOS check: a rider page sends encrypted updates through a mocked ntfy relay,
a friend's live.html page decrypts and shows them, then the rider presses SOS.

Run:  python3 tests/sim_live.py   (optional MAPLIBRE_DIR=/path/to/maplibre-gl/dist)
"""
import asyncio, json, os, sys, urllib.parse
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ML = os.environ.get('MAPLIBRE_DIR')
LAT0, LON0 = 32.80, -96.75

async def main():
    fails, posts, errs = [], {}, []
    async with async_playwright() as p:
        exe = '/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        b = await p.chromium.launch(executable_path=exe, args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, permissions=['geolocation'],
                                  geolocation={'latitude': LAT0, 'longitude': LON0, 'accuracy': 6})
        async def cdn(route):
            u = route.request.url
            if ML and u.endswith('.js'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.js'))
            if ML and u.endswith('.css'): return await route.fulfill(path=os.path.join(ML, 'maplibre-gl.css'))
            await route.fulfill(body='', content_type='application/javascript')
        async def ntfy(route):
            req = route.request; u = urllib.parse.urlparse(req.url); topic = u.path.strip('/').split('/')[0]
            h = {'Access-Control-Allow-Origin': '*'}
            if req.method == 'POST':
                posts.setdefault(topic, []).append(req.post_data)
                return await route.fulfill(json={'id': 'x', 'event': 'message'}, headers=h)
            msgs = posts.get(topic, [])
            if u.path.endswith('/json'):
                return await route.fulfill(body=''.join(json.dumps({'event': 'message', 'message': m}) + '\n' for m in msgs), headers=h, content_type='application/x-ndjson')
            if u.path.endswith('/sse'):
                body = ''.join('data: ' + json.dumps({'event': 'message', 'message': m}) + '\n\n' for m in msgs)
                return await route.fulfill(body=body or ': ping\n\n', headers=h, content_type='text/event-stream')
            await route.fulfill(status=404, headers=h)
        await ctx.route('https://unpkg.com/**', cdn)
        await ctx.route('https://fonts.googleapis.com/**', lambda r: r.fulfill(body='', content_type='text/css'))
        await ctx.route('https://tiles.openfreemap.org/**', lambda r: r.fulfill(body='{"version":8,"sources":{},"layers":[]}', content_type='application/json', headers={'Access-Control-Allow-Origin': '*'}))
        await ctx.route('https://ntfy.sh/**', ntfy)

        rider = await ctx.new_page(); rider.on('pageerror', lambda e: errs.append('rider: ' + str(e)))
        await rider.goto('file://' + ROOT + '/index.html'); await rider.wait_for_timeout(1200)
        # turn on live tracking, set name and an emergency contact
        await rider.click('nav button[data-v=set]')
        await rider.select_option('#liveOn', '1'); await rider.fill('#liveName', 'Brycen'); await rider.dispatch_event('#liveName', 'change')
        await rider.fill('[data-i="0"][data-f="n"]', 'Dario'); await rider.dispatch_event('[data-i="0"][data-f="n"]', 'change')
        await rider.fill('[data-i="0"][data-f="p"]', '+1 (214) 555-0101'); await rider.dispatch_event('[data-i="0"][data-f="p"]', 'change')
        link = await rider.inner_text('#liveLink')
        if 'live.html#spk' not in link: fails.append(f'no share link generated: {link!r}')
        await rider.click('nav button[data-v=ride]')
        await rider.click('#bStart')
        for i in range(1, 20):
            await ctx.set_geolocation({'latitude': LAT0 + 8 * i / 111320, 'longitude': LON0, 'accuracy': 6}); await rider.wait_for_timeout(1000)
        sent = sum(len(v) for v in posts.values())
        if sent < 1: fails.append('rider sent no live updates')
        if any('Brycen' in m for v in posts.values() for m in v): fails.append('live update is not encrypted (name visible in relay)')

        friend = await ctx.new_page(); friend.on('pageerror', lambda e: errs.append('viewer: ' + str(e)))
        await friend.goto(link); await friend.wait_for_timeout(2500)
        who = await friend.inner_text('#who'); pill = await friend.inner_text('#pill')
        if 'Brycen' not in who: fails.append(f'viewer did not decrypt rider name: {who!r}')
        if 'Live' not in pill: fails.append(f'viewer not showing live status: {pill!r}')

        # SOS: hold 2 s, check call/text buttons and that followers see it
        box = await rider.query_selector('#bSos')
        await box.dispatch_event('pointerdown'); await rider.wait_for_timeout(1800)
        call = await rider.get_attribute('.sosbig', 'href'); sms = await rider.get_attribute('.sosc', 'href')
        if call != 'tel:911': fails.append(f'call button wrong: {call!r}')
        if not sms or not sms.startswith('sms:+12145550101') or 'maps.google.com' not in urllib.parse.unquote(sms): fails.append(f'text button wrong: {sms!r}')
        await rider.wait_for_timeout(1500)
        await friend.reload(); await friend.wait_for_timeout(2500)
        sos_txt = await friend.inner_text('#sos')
        if 'SOS' not in sos_txt or 'Brycen' not in sos_txt: fails.append(f'viewer did not show SOS: {sos_txt!r}')
        await friend.screenshot(path='/tmp/spoke_live_viewer.png'); await rider.screenshot(path='/tmp/spoke_sos.png')
        await rider.click('#sosOk'); await rider.wait_for_timeout(1500)
        await friend.reload(); await friend.wait_for_timeout(2500)
        if await friend.is_visible('#sos.on'): fails.append('viewer still shows SOS after rider cancelled')
        if errs: fails.append('page errors: ' + '; '.join(errs))
        await b.close()
    print(('PASS' if not fails else 'FAIL') + '\n' + '\n'.join(fails))
    print(json.dumps({'ok': not fails, 'fails': fails, 'updates_sent': sent}))
    sys.exit(0 if not fails else 1)

asyncio.run(main())

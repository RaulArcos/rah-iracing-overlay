"""Isolated Chromium proof; boundary fixtures, NOT live SDK accuracy evidence."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from preview_server import preview_server
from test_radar_traffic import radar


def properties():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / 'src').rglob('properties.json')}


def run():
    from playwright.sync_api import sync_playwright
    from PIL import Image, ImageDraw
    scratch = ROOT / '.git' / 'radar-traffic'
    scratch.mkdir(exist_ok=True)
    before = properties()
    evidence, errors = [], []
    initial = radar(CarIdxLapDistPct=[.5, .504, .516, .496, .484],
                    CarIdxTrackSurface=[3] * 5, CarLeftRight=1,
                    WeekendInfo={'TrackLength': '5 km'})
    moved = radar(CarIdxLapDistPct=[.5, .508, .516, .492, .484],
                  CarIdxTrackSurface=[3] * 5, CarLeftRight=4,
                  WeekendInfo={'TrackLength': '5 km'})
    with preview_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ('original', 'glass'):
            for width in (320, 375):
                page = browser.new_page(viewport={'width': width, 'height': 210},
                                        reduced_motion='reduce', device_scale_factor=1)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/socket.io.min.js', lambda route: route.fulfill(
                    content_type='application/javascript',
                    body='window.handlers={};window.io=()=>({on:(e,h)=>handlers[e]=h});'))
                page.route('**/overlay_settings.js', lambda route: route.fulfill(
                    content_type='application/javascript', body='/* isolated defaults; no settings writes */'))
                page.goto(f'{base}/overlay/radar?theme={theme}', wait_until='networkidle')
                assert page.locator('html').get_attribute('data-rah-theme') == theme
                captures = []

                def update(data):
                    page.evaluate('d => handlers.radar_update(d)', data)

                def positions():
                    return page.locator('.traffic-car').evaluate_all('''els => els.map(e => {
                        const r=e.getBoundingClientRect();
                        return {label:e.textContent,x:r.x,y:r.y+r.height/2,top:e.style.top};
                    })''')

                def capture(state):
                    panel = page.locator('#proximity-panel').bounding_box()
                    assert panel['x'] >= 0 and panel['y'] >= 0 and panel['width'] <= width
                    assert panel['y'] + panel['height'] <= 210, panel
                    legend = page.locator('#traffic-range').bounding_box()
                    assert legend['y'] + legend['height'] <= 210, legend
                    filename = f'{theme}-{width}-{state}.png'
                    page.screenshot(path=str(scratch / filename))
                    evidence.append(dict(theme=theme, viewport=[width, 210], state=state,
                                         screenshot=filename, positions=positions(), panel=panel,
                                         status=page.locator('#radar-status').inner_text()))
                    captures.append((state, filename))

                update(initial)
                a = positions()
                assert len(a) == 4, a
                assert len({round(p['x'], 2) for p in a}) == 1
                capture('four-cars-before')
                update(moved)
                b = positions()
                assert len(b) == 4, b
                a_by_label = {point['label']: point for point in a}
                b_by_label = {point['label']: point for point in b}
                assert b_by_label['#21']['y'] < a_by_label['#21']['y'], (a, b)
                assert b_by_label['#44']['y'] > a_by_label['#44']['y'], (a, b)
                assert b_by_label['#7']['y'] == a_by_label['#7']['y']
                assert b_by_label['IDX 4']['y'] == a_by_label['IDX 4']['y']
                assert page.locator('#left-alert').inner_text() == 'CAR LEFT'
                assert page.locator('#right-alert').inner_text() == 'CAR RIGHT'
                capture('motion-both-sides')
                update({**initial, 'nearby': [{'car_idx': 1, 'distance_pct': 0},
                                             {'car_idx': 2, 'distance_pct': 0}]})
                assert page.locator('.traffic-car').count() == 1
                assert '2 cars' in page.locator('.traffic-car').inner_text()
                capture('coincident')
                cross_zero = {**initial, 'nearby': [
                    {'car_idx': 1, 'distance_pct': .002},
                    {'car_idx': 2, 'distance_pct': -.002}]}
                update(cross_zero)
                cross_positions = positions()
                assert [point['top'] for point in cross_positions] == ['46%', '54%']
                update({**cross_zero, 'nearby': list(reversed(cross_zero['nearby']))})
                assert positions() == cross_positions
                capture('opposite-sides-separated')
                update({**cross_zero, 'nearby': [cross_zero['nearby'][0],
                    {'car_idx': 2, 'distance_pct': -.004}]})
                assert [point['top'] for point in positions()] == ['46%', '58%']
                capture('rear-moves-independently')
                update({**initial, 'nearby': [{'car_idx': 1, 'distance_pct': .03}]})
                assert not positions()
                assert '1 outside' in page.locator('#traffic-range').inner_text()
                capture('outside')
                update({**initial, 'track_length_m': None})
                assert not positions()
                assert page.locator('#ahead-distance').inner_text() == '-- m'
                capture('missing-length')
                update({**initial, 'nearby': [None, {'car_idx': -1, 'distance_pct': .001},
                                            {'car_idx': 0, 'distance_pct': 0}]})
                assert not positions()
                capture('invalid-and-own')
                update({**initial, 'nearby': [{'car_idx': 1, 'distance_pct': .01,
                                             'car_number': '<img onerror=bad>'}]})
                assert page.locator('.traffic-car img').count() == 0
                assert '<img' in page.locator('.traffic-car').inner_text()
                capture('literal-metadata')
                for state, action in (
                    ('null', lambda: update(None)),
                    ('disconnect', lambda: page.evaluate('handlers.disconnect()')),
                    ('error', lambda: page.evaluate('handlers.connect_error()')),
                    ('stale', lambda: page.wait_for_timeout(3300)),
                ):
                    update(initial)
                    action()
                    assert not positions()
                    assert 'unavailable' in page.locator('#radar-status').inner_text().lower()
                    capture(state)
                # Contact sheet views every captured state with provenance outside widget.
                sheet = Image.new('RGB', (width * 3, 242 * ((len(captures) + 2) // 3)), '#222630')
                draw = ImageDraw.Draw(sheet)
                for i, (state, filename) in enumerate(captures):
                    x, y = i % 3 * width, i // 3 * 242
                    draw.text((x + 4, y + 2), f'FIXTURE / {theme} {width} / {state}', fill='white')
                    image = Image.open(scratch / filename).convert('RGBA')
                    sheet.paste(image, (x, y + 25), image)
                sheet.save(scratch / f'contact-{theme}-{width}.png')
                page.close()
        # Real existing opt-in demo, no fixture replacement of its payload or adapter.
        for theme in ('original', 'glass'):
            page = browser.new_page(viewport={'width': 375, 'height': 300})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'{base}/overlay/radar?demo=1&theme={theme}&embed=1', wait_until='networkidle')
            page.wait_for_timeout(100)
            first = page.locator('.traffic-car').evaluate_all('els => els.map(e=>e.style.top)')
            assert first, 'existing demo must put visible cars in plot range'
            page.screenshot(path=str(scratch / f'demo-{theme}-before.png'))
            page.wait_for_timeout(1300)
            second = page.locator('.traffic-car').evaluate_all('els => els.map(e=>e.style.top)')
            assert second and first != second, (first, second)
            page.screenshot(path=str(scratch / f'demo-{theme}-after.png'))
            evidence.append(dict(theme=theme, state='existing-demo-motion', before=first, after=second))
            page.close()
        browser.close()
    assert not errors, errors
    assert before == properties(), 'user properties changed during verification'
    result = dict(provenance='Boundary fixtures via public provider; NOT live SDK',
                  cases=evidence, page_errors=errors, properties_sha256=before)
    (scratch / 'evidence.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(cases=len(evidence), page_errors=errors, properties_preserved=len(before),
                          artifacts=str(scratch))))


if __name__ == '__main__':
    run()

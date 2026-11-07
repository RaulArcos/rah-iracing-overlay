"""Manual Chromium evidence: frozen anonymous fixtures, isolated read-only Flask.

Run: python tests/relative_ai_browser.py
Optional separate live read (no browser): python tests/relative_ai_browser.py --live
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from preview_server import preview_server
from test_relative_ai_accuracy import observed_sample, relative


def live_read():
    import irsdk
    sdk = irsdk.IRSDK()
    result = {}
    try:
        result['startup'] = sdk.startup()
        result['connected'] = bool(sdk.is_connected)
        if result['startup'] and result['connected']:
            sdk.freeze_var_buffer_latest()
            idx = sdk['PlayerCarIdx']
            info = sdk['DriverInfo'] or {}
            drivers = info.get('Drivers', [])
            player = next((d for d in drivers if d.get('CarIdx') == idx), {})
            result.update(player_index=idx, best=sdk['LapBestLapTime'], last=sdk['LapLastLapTime'],
                          driver_estimate=info.get('DriverCarEstLapTime'),
                          player={k: player.get(k) for k in ('IRating', 'LicString', 'LicLevel',
                                  'LicSubLevel', 'LicColor', 'CarIsAI', 'CarClassEstLapTime')},
                          bot_count=sum(d.get('CarIsAI') == 1 for d in drivers))
            pcts, times = sdk['CarIdxLapDistPct'], sdk['CarIdxEstTime']
            result['on_track_bot_count'] = sum(d.get('CarIsAI') == 1 and
                0 <= d.get('CarIdx', -1) < len(pcts) and pcts[d['CarIdx']] >= 0 for d in drivers)
            result['player_track_pct'] = pcts[idx]
            result['player_profile_time'] = times[idx]
    finally:
        sdk.shutdown()
    print(json.dumps(result))


def browser_check():
    from playwright.sync_api import sync_playwright
    scratch = ROOT / '.git' / 'relative-ai-debug'
    scratch.mkdir(exist_ok=True)
    cases = {
        'observed-ai-wrap-ahead': (observed_sample(), '+1.2s'),
        'wrap-behind': (observed_sample(CarIdxLapDistPct=[.005, .99, -1],
                                        CarIdxEstTime=[.4, 80.9, 0]), '-1.2s'),
        'nonuniform': (observed_sample(CarIdxLapDistPct=[.1, .4, -1],
                                      CarIdxEstTime=[1, 70, 0]), '+69.0s'),
        'missing-timing': (observed_sample(CarIdxEstTime=[80.9, None, 0]), '--'),
        'negative-zero': (observed_sample(CarIdxLapDistPct=[.5, .4999, -1],
                                         CarIdxEstTime=[40, 39.999, 0]), '0.0s'),
        'finish-zero-forward': (observed_sample(CarIdxLapDistPct=[1, .005, -1],
                                                CarIdxEstTime=[0, .4, 0]), '+0.4s'),
        'finish-zero-reverse': (observed_sample(CarIdxLapDistPct=[.005, 1, -1],
                                                CarIdxEstTime=[.4, 0, 0]), '-0.4s'),
    }
    evidence = []
    with preview_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 900, 'height': 450}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/socket.io.min.js', lambda route: route.fulfill(
            content_type='application/javascript', body='window.handlers={}; window.io=()=>({on:(e,h)=>handlers[e]=h});'))
        # Appearance settings are unrelated and must never read/write user properties here.
        page.route('**/overlay_settings.js', lambda route: route.fulfill(
            content_type='application/javascript', body='/* isolated appearance defaults */'))
        for theme in ('original', 'glass'):
            for name, (sample, expected) in cases.items():
                payload = relative(sample)
                payload['player']['name'] = 'Player (SDK profile unavailable)'
                payload['cars'][0]['name'] = '<img src=x onerror=alert(1)>'
                page.goto(f'{base}/overlay/relative?theme={theme}', wait_until='networkidle')
                page.evaluate("""label => {
                    const heading=document.createElement('div'); heading.textContent=label;
                    heading.style.cssText='color:white;background:#18202d;font:14px sans-serif;padding:8px';
                    document.body.prepend(heading);
                }""", f'FROZEN TEST FIXTURE · {name} · {theme} · NOT LIVE SDK')
                page.evaluate('data => handlers.relative_update(data)', payload)
                rows = page.locator('#relative-body .relative-row')
                assert rows.count() == 2
                assert page.locator('.rah-player .relative-gap').inner_text() == '0.0s'
                assert page.locator('.relative-row:not(.rah-player) .relative-gap').last.inner_text() == expected
                assert page.locator('#rel-sof').inner_text() == 'AI session'
                assert page.locator('#relative-body img').count() == 0
                assert 'online profile unavailable' in page.locator('.rah-player .race-rating').get_attribute('title').lower()
                text = page.locator('#relative-body').inner_text()
                assert '~' not in text and '-0.0s' not in text
                assert page.locator('html').get_attribute('data-rah-theme') == theme
                filename = f'{name}-{theme}.png'
                page.screenshot(path=str(scratch / filename))
                evidence.append(dict(case=name, theme=theme, gap=expected, screenshot=filename))
                page.evaluate("handlers.disconnect()")
                assert rows.count() == 0
                if name == 'observed-ai-wrap-ahead':
                    page.evaluate('data => handlers.relative_update(data)', payload)
                    page.wait_for_timeout(4200)
                    assert rows.count() == 0
                    assert page.locator('#rel-status').text_content() == 'Stale: no data'
        assert not errors, errors
        browser.close()
    (scratch / 'browser-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(dict(browser_cases=len(evidence), page_errors=errors, artifacts=str(scratch))))


if __name__ == '__main__':
    live_read() if '--live' in sys.argv else browser_check()

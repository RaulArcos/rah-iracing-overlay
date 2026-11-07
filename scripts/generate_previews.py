"""Generate every native (2 per overlay) transparent previews using installed Playwright.

Run from any directory: python scripts/generate_previews.py [--qa-only]
All scratch and browser evidence lives in .git/menu-previews. No SDK is loaded.
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

from preview_server import ROOT, SRC, preview_server
from preview_browser_qa import check_demo, check_menu, digest
from preview_pixels import compare_pixels


def validate_png(path, resolution):
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'Invalid PNG: {path}'
    assert struct.unpack('>II', data[16:24]) == (resolution['width'], resolution['height'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qa-only', action='store_true', help='Verify existing images without replacing them')
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    scratch = ROOT / '.git' / 'menu-previews'
    scratch.mkdir(parents=True, exist_ok=True)
    properties = sorted((SRC / 'overlays').glob('*/properties.json'))
    before = {str(p.relative_to(ROOT)): digest(p) for p in properties}
    (scratch / 'properties-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    report = {'demos': [], 'menu': [], 'socket_requests': [], 'websockets': [], 'writes': [], 'errors': []}
    staged = []
    with preview_server() as base, sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(scratch / 'chromium-profile'),
                                                       device_scale_factor=1, reduced_motion='reduce',
                                                       args=['--disable-gpu'])
        # The isolated profile belongs to this tool; no user browser profile is opened.
        context.clear_cookies()
        # External legacy launcher fonts/icons are irrelevant to native captures.
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base)
                      else route.abort())
        context.on('request', lambda req: report['socket_requests'].append(req.url)
                   if '/socket.io/' in req.url else None)
        context.on('request', lambda req: report['writes'].append(req.url)
                   if req.method != 'GET' else None)
        def monitor(page):
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.on('websocket', lambda ws: report['websockets'].append(ws.url))
        context.on('page', monitor)
        page = context.new_page()
        page.goto(base)
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='networkidle')
        overlays = page.request.get(base + '/get_overlays').json()
        baseline_storage = page.evaluate('JSON.stringify(localStorage)')
        for prop in properties:
            name = prop.parent.name
            resolution = json.loads(prop.read_text(encoding='utf-8'))['resolution']
            page.set_viewport_size({'width': resolution['width'], 'height': resolution['height'] + 100})
            for theme in ('original', 'glass'):
                box = check_demo(page, name, theme, base, resolution)
                assert page.evaluate('JSON.stringify(localStorage)') == baseline_storage
                # Capture only the native widget surface, excluding the toolbar.
                # Native transparent padding is retained when the card is smaller.
                path = scratch / f'{name}-{theme}.png'
                page.screenshot(path=str(path), omit_background=True,
                                clip={'x': 0, 'y': box['y'], **resolution})
                validate_png(path, resolution)
                target = prop.parent / 'static' / 'images' / f'preview-{theme}.png'
                staged.append((path, target, resolution))
                page.screenshot(path=str(scratch / f'demo-{name}-{theme}.png'), omit_background=True)
                report['demos'].append({'overlay': name, 'theme': theme, 'bounds': box,
                                        'dimensions': resolution, 'sha256': digest(path),
                                        'animated': True, 'pause_resume': True, 'storage_unchanged': True})
        expected = 2 * len(properties)
        assert len(staged) == expected
        for i in range(0, expected, 2):
            assert digest(staged[i][0]) != digest(staged[i + 1][0]), 'Theme captures must differ'
        assert not any(report[key] for key in ('errors', 'socket_requests', 'websockets', 'writes')), report
        # Render and validate EVERYTHING before replacing any public preview.
        if not args.qa_only:
            for path, target, _ in staged:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Copy via same-directory temporary file, then atomic replace per PNG.
                temporary = target.with_suffix('.png.tmp')
                temporary.write_bytes(path.read_bytes())
                os.replace(temporary, target)
        for _, target, resolution in staged:
            validate_png(target, resolution)
        if args.qa_only:
            report['reproduction'] = []
            for path, target, _ in staged:
                report['reproduction'].append({'image': str(target.relative_to(ROOT)),
                    **compare_pixels(page, path, target, target.parents[2].name)})
        report['menu'] = check_menu(page, base, overlays, scratch)
        assert not any(report[key] for key in ('errors', 'socket_requests', 'websockets', 'writes')), report
        context.close()
    after = {str(p.relative_to(ROOT)): digest(p) for p in properties}
    assert before == after, 'Capture must not change properties'
    report['properties_before'] = before
    report['properties_after'] = after
    assert 'data_provider' not in sys.modules and 'irsdk' not in sys.modules
    report['server_sdk_loaded'] = False
    (scratch / 'browser-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: {len(staged)} native PNGs; {len(staged)} animated demos; {len(staged)} menu previews; zero Socket.IO, websocket or write requests.')
    print('Evidence: .git/menu-previews/browser-report.json (all property hashes unchanged)')


if __name__ == '__main__':
    main()

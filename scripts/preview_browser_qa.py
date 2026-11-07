"""Real Chromium assertions shared by generation and repeatable browser smoke."""
import hashlib


def widget_signature(page):
    return page.locator('.rah-race').evaluate("""el => JSON.stringify({
        text: el.innerText, styles: Array.from(el.querySelectorAll('[style]')).map(x => x.style.cssText),
        canvas: Array.from(el.querySelectorAll('canvas')).map(x => x.toDataURL())})""")


def check_demo(page, name, theme, base, resolution):
    page.goto(f'{base}/overlay/{name}?demo=1&theme={theme}', wait_until='networkidle')
    page.wait_for_function('window.RAHDemo && RAHDemo.ready')
    assert page.locator('#rah-demo-toolbar').is_visible()
    assert 'not iRacing' in page.locator('#rah-demo-toolbar').inner_text()
    assert page.locator('html').get_attribute('data-rah-theme') == theme
    page.evaluate('RAHDemo.seek(300)')
    page.wait_for_timeout(60)
    before = widget_signature(page)
    assert 'Waiting for data' not in before and 'No observed laps' not in before
    page.wait_for_timeout(600)
    assert before == widget_signature(page), f'{name}: pause changed data'
    page.get_by_role('button', name='Resume', exact=True).click()
    page.wait_for_timeout(550)
    assert page.evaluate('RAHDemo.tick') > 300
    # Some race fields change at a lap boundary, rather than every tick.
    # Inspect deterministic later frames as well as the running timer.
    changed = before != widget_signature(page)
    for _ in range(6):
        page.evaluate('RAHDemo.step(12)')
        page.wait_for_timeout(20)
        changed = changed or before != widget_signature(page)
    assert changed, f'{name}: did not animate'
    page.get_by_role('button', name='Pause', exact=True).click()
    stopped = page.evaluate('RAHDemo.tick')
    page.wait_for_timeout(350)
    assert page.evaluate('RAHDemo.tick') == stopped
    page.evaluate('RAHDemo.seek(300)')
    page.wait_for_timeout(60)
    if name == 'laptime_graph':
        assert page.locator('.laplog-row.rah-table-row').count() == 10
    if name == 'standings':
        assert page.locator('.st-group-title').count() == 3
        assert page.locator('.st-row.rah-player').count() == 1
    if name == 'relative':
        assert page.locator('.relative-row.rah-player').count() == 1
    panel = page.locator('.rah-race')
    page.evaluate('window.scrollTo(0, 0)')
    box = panel.bounding_box()
    toolbar_box = page.locator('#rah-demo-toolbar').bounding_box()
    assert box['y'] >= toolbar_box['y'] + toolbar_box['height'], f'{name}: toolbar overlaps {box} / {toolbar_box}'
    assert toolbar_box['y'] == 0, f'{name}: toolbar must stay at top of viewport'
    assert box['x'] >= 0 and box['width'] <= resolution['width'] + 1
    assert box['height'] <= resolution['height'] + 1, f'{name}: exceeds native capture: {box}'
    return box


def check_menu(page, base, overlays, scratch):
    """Launcher v2: every overlay selectable, live embedded demo per theme."""
    page.set_viewport_size({'width': 1400, 'height': 1000})
    page.goto(base, wait_until='networkidle')
    page.wait_for_selector('.ov-item')
    evidence = []
    for overlay in overlays:
        name = overlay['folder_name']
        page.locator(f'.ov-item[data-folder="{name}"] .ov-item__select').click()
        for theme in ('original', 'glass'):
            page.select_option('#themeSelect', theme)
            expected = f'/overlay/{name}?demo=1&theme={theme}'
            page.wait_for_function("""expected => document.getElementById('previewFrame')
                .getAttribute('src') === expected + '&embed=1'""", arg=expected)
            frame = page.frame_locator('#previewFrame')
            frame.locator('.rah-race').first.wait_for()
            assert page.locator('#previewDemo').get_attribute('href') == expected + '&stage=1'
            assert page.locator('#previewDemo').get_attribute('target') == '_blank'
            assert 'simulated' in page.locator('.preview-caption').inner_text().lower()
            assert page.locator('#previewTitle').inner_text().lower() == overlay['display_name'].lower()
            page.locator('#detail').screenshot(path=str(scratch / f'menu-{name}-{theme}.png'))
            evidence.append({'overlay': name, 'theme': theme, 'demo': expected, 'loaded': True})
    with page.expect_popup() as popup_info:
        page.locator('#previewDemo').click()
    popup = popup_info.value
    popup.wait_for_function('window.RAHDemo && RAHDemo.ready')
    assert popup.url.endswith('?demo=1&theme=glass&stage=1')
    assert popup.locator('#rah-demo-toolbar').is_visible()
    popup.close()
    assert page.locator('#previewTitle img, #previewDescription script').count() == 0
    return evidence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

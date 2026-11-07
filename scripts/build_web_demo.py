"""Export every overlay's browser demo as static files for a website.

    python scripts/build_web_demo.py <output-dir>

Writes <output-dir>/demo/<overlay>.html plus the CSS, JS, fonts and images
they need, with relative URLs, so a static host (GitHub Pages) can run the
real overlays on simulated data. Open them as
``demo/<overlay>.html?demo=1&embed=1&theme=original|glass``.
Also writes <output-dir>/demo/overlays.json (names, sizes, preview images).
No iRacing SDK, Socket.IO server or desktop window is involved.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from preview_server import ROOT, SRC  # noqa: F401  (sets sys.path to src/)


def main(out):
    out = Path(out).resolve()
    demo = out / 'demo'
    assets = demo / 'assets'
    if demo.exists():
        shutil.rmtree(demo)
    (assets / 'common').mkdir(parents=True)

    from flask import Flask
    from interface import interface_bp
    from overlays import overlays_bp
    app = Flask(__name__)
    app.register_blueprint(interface_bp)
    app.register_blueprint(overlays_bp, url_prefix='/overlay')

    @app.route('/common/js/<path:filename>')
    def serve_common_js(filename):
        return ''

    client = app.test_client()

    # Shared assets: CSS, the browser-side JS, fonts.
    shutil.copytree(SRC / 'common' / 'css', assets / 'common' / 'css')
    shutil.copytree(SRC / 'common' / 'fonts', assets / 'common' / 'fonts')
    js = assets / 'common' / 'js'
    js.mkdir()
    for name in ('overlay_theme.js', 'overlay_settings.js', 'race_metadata.js', 'socket.io.min.js',
                 'demo_race.js', 'demo_scenario.js', 'demo_adapter.js'):
        shutil.copy(SRC / 'common' / 'js' / name, js / name)
    # Absolute /common/... URLs inside the CSS become relative to the CSS file.
    for css in (assets / 'common' / 'css').glob('*.css'):
        text = css.read_text(encoding='utf-8')
        text = text.replace("url('/common/css/", "url('./").replace("url('/common/fonts/", "url('../fonts/")
        css.write_text(text, encoding='utf-8')

    catalog = []
    for props in sorted((SRC / 'overlays').glob('*/properties.json')):
        name = props.parent.name
        info = json.loads(props.read_text(encoding='utf-8'))
        html = client.get(f'/overlay/{name}?demo=1').get_data(as_text=True)
        html = re.sub(r'/overlay/' + name + r'/static/', f'assets/{name}/', html)
        html = html.replace('/common/css/', 'assets/common/css/').replace('/common/js/', 'assets/common/js/')
        assert '/overlay/' not in html and '"/common' not in html, name
        (demo / f'{name}.html').write_text(html, encoding='utf-8')
        static = props.parent / 'static'
        target = assets / name
        shutil.copytree(static, target, ignore=shutil.ignore_patterns('preview.gif', '__pycache__'))
        catalog.append({
            'name': name,
            'display_name': info.get('display_name', name),
            'width': info['resolution']['width'],
            'height': info['resolution']['height'],
            'preview': {theme: f'assets/{name}/images/preview-{theme}.png'
                        for theme in ('original', 'glass')
                        if (static / 'images' / f'preview-{theme}.png').is_file()},
        })
    (demo / 'overlays.json').write_text(json.dumps(catalog, indent=2), encoding='utf-8')
    print(f'Exported {len(catalog)} overlay demos to {demo}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

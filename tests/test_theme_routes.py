"""Theme selection tests (T2, S2-S5).

Exercises the public HTTP surface with the Flask test client and a fake
pywebview process: the accessible launcher selector markup, the common theme
asset routes, per-overlay theme includes, unchanged overlay discovery, and the
small explicit theme whitelist used when building desktop launch URLs. No GUI,
server, or real iRacing SDK is started, and no overlay properties.json is
mutated.
"""

import hashlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from flask import Flask, send_from_directory  # noqa: E402

import interface as interface_module  # noqa: E402
from interface import interface_bp  # noqa: E402
from overlays import overlays_bp  # noqa: E402

SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))

OVERLAYS = [
    'input_telemetry',
    'relative',
    'radar',
    'blindspot',
    'track_map',
    'laptime_graph',
    'fuel_finish',
    'session_strip',
    'battle_pace',
    'standings',
    'pit_assistant',
    'weather',
    'broadcast_driver',
]


def make_app():
    """Build the same blueprint registration WebInterface uses, without the
    SocketIO server, DataProvider, or telemetry thread."""
    app = Flask(__name__)
    app.register_blueprint(interface_bp, url_prefix='/')
    app.register_blueprint(overlays_bp, url_prefix='/overlay')

    # Mirror the app-level /common/js route registered by
    # WebInterface._setup_routes so overlay templates can resolve url_for
    # exactly as they do in production.
    @app.route('/common/js/<path:filename>')
    def serve_common_js(filename):
        return send_from_directory(os.path.join(SRC_ROOT, 'common', 'js'), filename)

    return app


class FakeOverlayProcess:
    """Stands in for multiprocessing.Process; records the launch arguments."""

    launched = []

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None):
        self.target = target
        self.args = args
        self._alive = False
        FakeOverlayProcess.launched.append(self)

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def terminate(self):
        self._alive = False

    def join(self, timeout=None):
        pass


class ThemeRouteTestBase(unittest.TestCase):
    def setUp(self):
        FakeOverlayProcess.launched = []
        interface_module.opened_overlays.clear()
        interface_module.overlay_theme_preferences.clear()
        self.app = make_app()
        self.client = self.app.test_client()
        patches = [
            mock.patch('multiprocessing.Process', FakeOverlayProcess),
            mock.patch('time.sleep', lambda seconds: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def overlay_url(self, folder_name):
        return f'http://127.0.0.1:8085/overlay/{folder_name}'

    def display_name(self, folder_name):
        overlays = self.client.get('/get_overlays').get_json()
        return next(o['display_name'] for o in overlays if o['folder_name'] == folder_name)


class TestCommonThemeAssets(ThemeRouteTestBase):
    def test_common_css_route_serves_shared_theme_stylesheet(self):
        response = self.client.get('/common/css/overlay-theme.css')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/css', response.headers['Content-Type'])
        body = response.get_data(as_text=True)
        self.assertIn('[data-rah-theme="glass"]', body)
        self.assertIn('.rah-card', body)

    def test_common_js_route_serves_theme_runtime(self):
        response = self.client.get('/common/js/overlay_theme.js')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn('RAHOverlayTheme', response.get_data(as_text=True))


class TestOverlayThemeIncludes(ThemeRouteTestBase):
    def test_every_overlay_page_includes_theme_and_base_assets(self):
        for name in OVERLAYS:
            with self.subTest(overlay=name):
                response = self.client.get(f'/overlay/{name}')
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                self.assertIn('/common/css/overlay-theme.css', body)
                self.assertIn('/common/js/overlay_theme.js', body)
                self.assertIn(f'{name}.css', body)
                self.assertIn('socket.io.min.js', body)
                self.assertLess(
                    body.index(f'{name}.css'),
                    body.index('overlay-theme.css'),
                    'theme stylesheet must load after the base stylesheet',
                )

    def test_overlay_route_serves_identical_html_regardless_of_theme_param(self):
        # Theme selection for browser/OBS URLs is resolved client-side; the
        # public overlay route must not fork its response on ?theme=.
        plain = self.client.get('/overlay/input_telemetry')
        themed = self.client.get('/overlay/input_telemetry?theme=glass')
        invalid = self.client.get('/overlay/input_telemetry?theme=neon')
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(plain.get_data(), themed.get_data())
        self.assertEqual(plain.get_data(), invalid.get_data())

    def test_unknown_overlay_still_404(self):
        response = self.client.get('/overlay/does_not_exist')
        self.assertEqual(response.status_code, 404)


class TestLauncherSelector(ThemeRouteTestBase):
    def test_launcher_page_has_accessible_default_original_theme_selector(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('for="themeSelect"', body)
        self.assertIn('id="themeSelect"', body)
        self.assertIn('<option value="original" selected', body)
        self.assertIn('<option value="glass"', body)
        self.assertIn('overlay_theme.js', body)

    def test_get_overlays_payload_shape_is_unchanged(self):
        response = self.client.get('/get_overlays')
        self.assertEqual(response.status_code, 200)
        overlays = response.get_json()
        expected_keys = {
            'display_name', 'folder_name', 'description', 'url',
            'position', 'dpi_info', 'preview_gif',
        }
        self.assertEqual({o['folder_name'] for o in overlays}, set(OVERLAYS))
        for overlay in overlays:
            self.assertEqual(set(overlay.keys()), expected_keys)
            self.assertNotIn('?', overlay['url'], 'discovery URLs must stay query-free')


class TestLaunchThemeWhitelist(ThemeRouteTestBase):
    def post_launch(self, payload):
        response = self.client.post(
            '/launch', json=payload, follow_redirects=True)
        return response

    def test_launch_without_theme_keeps_the_plain_overlay_url(self):
        response = self.post_launch({'overlay': self.display_name('input_telemetry'), 'transparent': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'success')
        self.assertEqual(set(response.get_json().keys()), {'status', 'message', 'transparent'})
        self.assertEqual(len(FakeOverlayProcess.launched), 1)
        self.assertEqual(FakeOverlayProcess.launched[0].args[0], self.overlay_url('input_telemetry'))

    def test_launch_pins_whitelisted_themes_in_the_url(self):
        for theme in ('glass', 'original'):
            with self.subTest(theme=theme):
                FakeOverlayProcess.launched = []
                response = self.post_launch({
                    'overlay': self.display_name('input_telemetry'),
                    'transparent': True,
                    'theme': theme,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    FakeOverlayProcess.launched[0].args[0],
                    f'{self.overlay_url("input_telemetry")}?theme={theme}',
                )

    def test_launch_rejects_non_whitelisted_themes_without_touching_the_url(self):
        for theme in ('neon', '', '<script>', None, 123, {'glass': True}):
            with self.subTest(theme=theme):
                FakeOverlayProcess.launched = []
                response = self.post_launch({
                    'overlay': self.display_name('radar'),
                    'transparent': True,
                    'theme': theme,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()['status'], 'success')
                self.assertEqual(
                    FakeOverlayProcess.launched[0].args[0],
                    self.overlay_url('radar'),
                    f'theme {theme!r} must not reach the launch URL',
                )

    def test_launch_unknown_overlay_keeps_existing_error_response(self):
        # Unknown display names already fell through to the pre-existing 400
        # "Overlay name not provided." branch before the theme system.
        response = self.post_launch({'overlay': 'Nope', 'transparent': True})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['status'], 'error')

    def test_relaunch_preserves_the_pinned_theme_in_memory(self):
        self.post_launch({'overlay': self.display_name('input_telemetry'),
                          'transparent': True, 'theme': 'glass'})
        FakeOverlayProcess.launched = []
        response = self.client.post('/toggle_transparency', json={
            'overlay': self.display_name('input_telemetry')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'success')
        url = FakeOverlayProcess.launched[0].args[0]
        self.assertEqual(url, f'{self.overlay_url("input_telemetry")}?theme=glass')

    def test_relaunch_without_a_pinned_theme_keeps_the_plain_url(self):
        self.post_launch({'overlay': self.display_name('relative'), 'transparent': True})
        FakeOverlayProcess.launched = []
        response = self.client.post('/toggle_transparency', json={
            'overlay': self.display_name('relative')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FakeOverlayProcess.launched[0].args[0], self.overlay_url('relative'))

    def test_theme_preference_is_per_overlay(self):
        self.post_launch({'overlay': self.display_name('input_telemetry'),
                          'transparent': True, 'theme': 'glass'})
        self.post_launch({'overlay': self.display_name('relative'), 'transparent': True})
        urls = [p.args[0] for p in FakeOverlayProcess.launched]
        self.assertEqual(urls[0], f'{self.overlay_url("input_telemetry")}?theme=glass')
        self.assertEqual(urls[1], self.overlay_url('relative'))

    def test_launches_do_not_mutate_overlay_properties(self):
        def digest(folder_name):
            path = os.path.join(SRC_ROOT, 'overlays', folder_name, 'properties.json')
            with open(path, 'rb') as properties_file:
                return hashlib.sha256(properties_file.read()).hexdigest()

        before = {name: digest(name) for name in OVERLAYS}
        self.post_launch({'overlay': self.display_name('input_telemetry'),
                          'transparent': True, 'theme': 'glass'})
        self.client.post('/toggle_transparency', json={'overlay': self.display_name('input_telemetry')})
        self.assertEqual(before, {name: digest(name) for name in OVERLAYS})


if __name__ == '__main__':
    unittest.main()

"""Per-overlay appearance settings: validation, routes, runtime injection."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from test_theme_routes import make_app, OVERLAYS
import interface as interface_module
from interface import sanitize_settings, SETTINGS_DEFAULTS, scaled_resolution


class SanitizeTests(unittest.TestCase):
    def test_defaults_for_garbage(self):
        for raw in (None, [], 'x', 3, {'opacity': 'loud'}):
            self.assertEqual(sanitize_settings(raw), SETTINGS_DEFAULTS)

    def test_clamps_and_whitelists(self):
        clean = sanitize_settings({'opacity': 5, 'bg_opacity': 400, 'scale': 1000, 'theme': 'neon',
                                   'accent': '#ABCDEF', 'show_header': False, 'show_footer': 'no',
                                   'hidden': ['wheel', 'WHEEL', '../x', 'wheel', 7, 'clutch'],
                                   'evil': '<script>'})
        self.assertEqual(clean['opacity'], 20)
        self.assertEqual(clean['bg_opacity'], 100)
        self.assertEqual(clean['scale'], 200)
        self.assertEqual(clean['theme'], '')
        self.assertEqual(clean['accent'], '#abcdef')
        self.assertIs(clean['show_header'], False)
        self.assertIs(clean['show_footer'], True)
        self.assertEqual(clean['hidden'], ['clutch', 'wheel'])
        self.assertNotIn('evil', clean)
        self.assertEqual(sanitize_settings({'accent': 'red'})['accent'], '#e2483d')
        self.assertEqual(sanitize_settings({'opacity': True})['opacity'], 100)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def fake_properties(self):
        path = os.path.join(self.tmp, 'properties.json')
        with open(path, 'w') as handle:
            json.dump({'name': 'radar', 'resolution': {'width': 320, 'height': 210}}, handle)
        return path

    def test_get_returns_defaults_and_native_size(self):
        for name in OVERLAYS:
            data = self.client.get('/overlay_settings/' + name).get_json()
            self.assertEqual(data['resolution'].keys(), {'width', 'height'})
            data.pop('resolution')
            self.assertEqual(set(data), set(SETTINGS_DEFAULTS))
        self.assertEqual(self.client.get('/overlay_settings/nope').status_code, 404)
        self.assertEqual(self.client.get('/overlay_settings/..%2Finterface').status_code, 404)

    def test_post_persists_sanitized_settings_only_under_settings_key(self):
        path = self.fake_properties()
        with mock.patch.object(interface_module, '_overlay_properties_path', return_value=path):
            response = self.client.post('/overlay_settings/radar', json={'scale': 150, 'hidden': ['x'], 'bad': 1})
            self.assertEqual(response.get_json()['settings']['scale'], 150)
            with open(path) as handle:
                stored = json.load(handle)
            self.assertEqual(stored['resolution'], {'width': 320, 'height': 210})
            self.assertEqual(stored['settings']['hidden'], ['x'])
            self.assertNotIn('bad', stored['settings'])
            self.assertEqual(scaled_resolution({'width': 320, 'height': 210}, 'radar'),
                             {'width': 480, 'height': 315})

    def test_every_overlay_page_loads_settings_runtime_once(self):
        for name in OVERLAYS:
            html = self.client.get('/overlay/' + name).get_data(as_text=True)
            self.assertEqual(html.count('/common/js/overlay_settings.js'), 1)
            self.assertLess(html.index('overlay_theme.js'), html.index('overlay_settings.js'))


if __name__ == '__main__':
    unittest.main()

"""Public HTTP contracts for isolated demos and native preview discovery."""
import hashlib
import struct
import unittest
from pathlib import Path

from test_theme_routes import make_app, OVERLAYS, SRC_ROOT


class MenuPreviewTests(unittest.TestCase):
    def setUp(self):
        self.client = make_app().test_client()

    def test_exact_opt_in_and_injection_order_for_every_overlay(self):
        for name in OVERLAYS:
            with self.subTest(name=name):
                url = '/overlay/' + name
                live = self.client.get(url).text
                for query in ('', '?demo=0', '?demo=true', '?demo=01', '?demo=',
                              '?demo=unknown', '?demo=1&demo=0'):
                    self.assertEqual(self.client.get(url + query).text, live)
                self.assertNotIn('demo_adapter.js', live)
                demo = self.client.get(url + '?demo=1&theme=glass').text
                self.assertIn('/common/js/demo_adapter.js', demo)
                self.assertLess(demo.index('socket.io.min.js'), demo.index('demo_adapter.js'))
                self.assertLess(demo.index('demo_scenario.js'), demo.index('demo_adapter.js'))
                self.assertEqual(demo.count('demo_adapter.js'), 1)
        self.assertEqual(self.client.get('/overlay/not_an_overlay?demo=1').status_code, 404)

    def test_preview_mapping_matches_existing_files_preserves_live_urls(self):
        overlays = self.client.get('/get_overlays').json
        self.assertEqual(len(overlays), 14)
        for overlay in overlays:
            self.assertIn('preview_gif', overlay)
            self.assertNotIn('?', overlay['url'])
            name = overlay['folder_name']
            expected = {theme: f'/overlay/{name}/static/images/preview-{theme}.png'
                        for theme in ('original', 'glass')
                        if (Path(SRC_ROOT) / 'overlays' / name / 'static' / 'images' /
                            f'preview-{theme}.png').is_file()}
            self.assertEqual(overlay['preview_images'], expected)
            for url in expected.values():
                response = self.client.get(url)
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/png')
                self.assertTrue(response.data.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_26_native_pngs_have_valid_dimensions_and_distinct_themes(self):
        import json
        for name in OVERLAYS:
            root = Path(SRC_ROOT) / 'overlays' / name
            resolution = json.loads((root / 'properties.json').read_text())['resolution']
            digests = []
            for theme in ('original', 'glass'):
                data = (root / 'static' / 'images' / f'preview-{theme}.png').read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]),
                                 (resolution['width'], resolution['height']))
                digests.append(hashlib.sha256(data).hexdigest())
            self.assertNotEqual(*digests)


if __name__ == '__main__':
    unittest.main()

"""R2 additive enrichment, exercised only through the public telemetry entry."""
import math
import unittest
from unittest.mock import patch

from test_battle_standings import DRIVERS, SocketTestBase, race_sample, session_info, standings_cars
from test_telemetry_accuracy import FakeSDK, make_provider


def enriched_sample(**overrides):
    drivers = [dict(d, IRating=2000 + d['CarIdx'] * 100, LicString='A 3.42',
                    LicSubLevel=342, LicColor='0x0153db',
                    CarClassColor='0xffda59' if d['CarClassID'] == 200 else '0xe94580')
               for d in DRIVERS]
    return race_sample(DriverInfo={'Drivers': drivers}, **overrides)


class TestRosterEnrichment(unittest.TestCase):
    def test_same_real_metadata_on_both_widgets_and_actual_player(self):
        data = make_provider(enriched_sample()).get_telemetry_data()
        cars = standings_cars(data)
        player = data['relative_data']['player']
        self.assertEqual((player['car_idx'], player['name'], player['is_player']), (1, 'Ada', True))
        self.assertNotIn(1, [c['car_idx'] for c in data['relative_data']['cars']])
        for relative in [player] + data['relative_data']['cars']:
            for key in ('irating', 'license', 'safety_rating', 'license_color', 'class_color',
                        'positions_gained', 'positions_gained_source'):
                self.assertEqual(relative[key], cars[relative['car_idx']][key], key)
        self.assertEqual((player['irating'], player['license'], player['safety_rating']), (2100, 'A', 3.42))
        self.assertEqual(player['license_color'], '#0153db')
        self.assertEqual(player['class_color'], '#e94580')
        self.assertIsNone(player['positions_gained'])

    def test_bad_ratings_license_and_colors_stay_null(self):
        for bad in (None, True, -1, 0, 2.5, 'oops', float('nan'), float('inf')):
            with self.subTest(bad=bad):
                sample = enriched_sample()
                sample['DriverInfo']['Drivers'][1].update(
                    IRating=bad, LicString='<img onerror=x>', LicSubLevel=bad,
                    LicColor='red;url(x)', CarClassColor='javascript:x')
                car = standings_cars(make_provider(sample).get_telemetry_data())[1]
                for key in ('irating', 'license', 'safety_rating', 'license_color', 'class_color'):
                    self.assertIsNone(car[key], key)

    def test_sof_uses_exponential_formula_and_flags_partial_or_missing(self):
        data = make_provider(enriched_sample()).get_telemetry_data()
        gt3 = next(g for g in data['standings_data']['classes'] if g['class_id'] == 100)
        ratings = [2100, 2300, 2500, 2600]
        expected = round(-1600 / math.log(2) * math.log(sum(2 ** (-r / 1600) for r in ratings) / 4))
        self.assertEqual(gt3['sof'], {'value': expected, 'rated': 4, 'total': 4, 'complete': True})
        self.assertEqual(data['relative_data']['player_class_sof'], gt3['sof'])
        for missing in (1, 4):
            sample = enriched_sample()
            for driver in [d for d in sample['DriverInfo']['Drivers'] if d['CarClassID'] == 100][:missing]:
                driver['IRating'] = 0
            group = next(g for g in make_provider(sample).get_telemetry_data()['standings_data']['classes']
                         if g['class_id'] == 100)
            self.assertFalse(group['sof']['complete'])
            self.assertEqual(group['sof']['rated'], 4 - missing)
            self.assertEqual(group['sof']['value'] is None, missing == 4)
            if missing == 1:
                expected_partial = round(-1600 / math.log(2) * math.log(
                    sum(2 ** (-r / 1600) for r in ratings[1:]) / 3))
                self.assertEqual(group['sof']['value'], expected_partial)

    def test_qualifying_and_current_results_are_never_invented_start_positions(self):
        for kind in ('Practice', 'Race'):
            info = session_info(kind)
            info['Sessions'][0].update(QualifyPositions=[{'CarIdx': 1, 'Position': 0}],
                                       ResultsPositions=[{'CarIdx': 1, 'Position': 6}])
            sample = enriched_sample(SessionInfo=info)
            data = make_provider(sample).get_telemetry_data()
            self.assertIsNone(standings_cars(data)[1]['positions_gained'])
            self.assertIsNone(data['relative_data']['player']['positions_gained_source'])

    def test_summary_shared_and_missing_values_do_not_become_zero(self):
        sample = enriched_sample(SessionTime=1234.5, TrackTempCrew=27.2)
        data = make_provider(sample).get_telemetry_data()
        summary = data['standings_data']['session_summary']
        self.assertEqual(summary, data['relative_data']['session_summary'])
        self.assertEqual(summary['elapsed_s'], 1234.5)
        self.assertEqual(summary['track_temp_c'], 27.2)
        self.assertEqual(summary['field_size'], 6)
        self.assertEqual(summary['lap_limit'], 20)
        data = make_provider({'Lap': 1}).get_telemetry_data()
        self.assertIsNone(data['relative_data']['player'])
        self.assertIsNone(data['standings_data']['session_summary']['elapsed_s'])

    def test_enrichment_does_not_change_gap_values_or_disconnected_contract(self):
        provider = make_provider(enriched_sample())
        data = provider.get_telemetry_data()
        self.assertEqual(standings_cars(data)[1]['interval_s'], 2.9)
        self.assertTrue(all(c['gap_is_estimate'] for c in data['relative_data']['cars']))
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_numeric_yaml_colors_and_excluded_roster_members(self):
        sample = enriched_sample()
        sample['DriverInfo']['Drivers'][1].update(CarClassColor=0xe94580, LicColor=0x0153db)
        sample['DriverInfo']['Drivers'][3]['IsSpectator'] = 1
        result = make_provider(sample).get_telemetry_data()
        self.assertEqual(standings_cars(result)[1]['class_color'], '#e94580')
        self.assertEqual(standings_cars(result)[1]['license_color'], '#0153db')
        group = next(g for g in result['standings_data']['classes'] if g['class_id'] == 100)
        self.assertEqual(group['sof']['total'], 3)
        self.assertEqual(result['standings_data']['session_summary']['field_size'], 5)

    def test_unknown_class_never_claims_a_mixed_class_sof(self):
        sample = enriched_sample()
        for driver in sample['DriverInfo']['Drivers']:
            driver.pop('CarClassID')
        result = make_provider(sample).get_telemetry_data()
        self.assertEqual(result['standings_data']['classes'][0]['sof'],
                         {'value': None, 'rated': 0, 'total': 0, 'complete': False})
        self.assertIsNone(result['relative_data']['player_class_sof']['value'])


class TestPublicR2Routes(SocketTestBase):
    def test_public_events_deliver_shared_enrichment_and_clear_disconnect(self):
        self.web.data_provider.ir_sdk = FakeSDK(enriched_sample())
        # Legacy namespaces use an older disconnect callback signature; match
        # existing legacy socket tests and verify disconnect clearing in JS.
        relative = self.client('/relative', disconnect=False)
        standings = self.client('/standings')
        self.web._process_telemetry_data()
        rel = self.events(relative, '/relative', 'relative_update')[0]
        stand = self.events(standings, '/standings', 'standings_update')[0]
        self.assertEqual(rel['player']['irating'], 2100)
        self.assertEqual(rel['player']['irating'], stand['classes'][1]['cars'][1]['irating'])
        self.assertEqual(rel['session_summary'], stand['session_summary'])
        self.web.data_provider.is_connected = False
        self.web._process_telemetry_data()
        # Empty telemetry causes server-wide silence; both scripts clear stale data.
        self.assertEqual(self.events(relative, '/relative', 'relative_update'), [])
        self.assertEqual(self.events(standings, '/standings', 'standings_update'), [])
        with patch.object(self.web.data_provider, 'get_telemetry_data', return_value={'speed': 1}):
            self.web._process_telemetry_data()
        # A nonempty poll lacking sections preserves the existing per-widget defaults.
        self.assertEqual(self.events(relative, '/relative', 'relative_update')[0]['cars'], [])
        self.assertEqual(self.events(standings, '/standings', 'standings_update'), [None])

    def test_public_routes_load_opt_in_theme_and_shared_metadata_locally(self):
        http = self.web.app.test_client()
        for name in ('relative', 'standings'):
            for theme in ('original', 'glass'):
                with http.get(f'/overlay/{name}?theme={theme}') as response:
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertLess(html.index('overlay-theme.css'), html.index('race-system.css'))
                    self.assertLess(html.index('race_metadata.js'), html.index(f'{name}.js'))
                    self.assertIn('rah-race', html)
        with http.get('/common/js/race_metadata.js') as response:
            self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()

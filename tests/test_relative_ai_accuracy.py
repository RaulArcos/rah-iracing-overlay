"""Relative source and observed AI placeholders through the public poll."""
import unittest

from test_telemetry_accuracy import base_sample, make_provider


def observed_sample(**overrides):
    drivers = [dict(CarIdx=i, CarNumber=str(i), CarClassID=0,
                    CarClassEstLapTime=81.6658, CarIsAI=int(i != 0),
                    IRating=1 if i == 0 else 0, LicString='R 0.01' if i == 0 else 'R 0.00',
                    LicLevel=1, LicSubLevel=1 if i == 0 else 0, LicColor='0xundefined')
               for i in range(3)]
    sample = base_sample(PlayerCarIdx=0, DriverInfo={'Drivers': drivers},
                         LapBestLapTime=-1, LapLastLapTime=-1,
                         CarIdxPosition=[1, 2, 3], CarIdxLapCompleted=[2, 2, 2],
                         CarIdxLapDistPct=[.99, .005, -1], CarIdxEstTime=[80.9, .4, 0])
    sample.update(overrides)
    return sample


def relative(sample):
    return make_provider(sample).get_telemetry_data()['relative_data']


class RelativeAccuracy(unittest.TestCase):
    def test_observed_wrap_and_profiles(self):
        data = relative(observed_sample())
        self.assertEqual(len(data['cars']), 1)
        self.assertAlmostEqual(data['cars'][0]['gap'], 1.1658)
        self.assertEqual(data['cars'][0]['gap_source'], 'sdk_class_profile')
        self.assertTrue(data['cars'][0]['is_ai'])
        self.assertIsNone(data['player']['irating'])
        self.assertIsNone(data['player']['license'])
        self.assertEqual(data['player']['profile_unavailable_reason'], 'ai_session_placeholder')
        self.assertIsNone(data['player_class_sof']['value'])
        self.assertTrue(data['session_summary']['is_ai_session'])

    def test_wrap_reverse_and_nonuniform_branch(self):
        for pcts, times, expected in [([.005, .99, -1], [.4, 80.9, 0], -1.1658),
                                      ([.1, .4, -1], [1, 70, 0], 69),
                                      ([.9, .1, -1], [30, 20, 0], 71.6658)]:
            with self.subTest(pcts=pcts):
                car = relative(observed_sample(CarIdxLapDistPct=pcts, CarIdxEstTime=times))['cars'][0]
                self.assertAlmostEqual(car['gap'], expected)

    def test_different_class_normalizes_profile_period(self):
        sample = observed_sample(CarIdxLapDistPct=[.2, .3, -1], CarIdxEstTime=[10, 30, 0])
        sample['DriverInfo']['Drivers'][1].update(CarClassID=2, CarClassEstLapTime=100)
        car = relative(sample)['cars'][0]
        self.assertAlmostEqual(car['gap'], 30 / 100 * 81.6658 - 10)
        self.assertEqual(car['gap_source'], 'sdk_normalized_class_profile')

    def test_start_finish_endpoint_representations_are_equivalent(self):
        period = 81.6658
        cases = [([1, .005, -1], [0, .4, 0], .4),
                 ([.005, 1, -1], [.4, 0, 0], -.4),
                 ([.99, 1, -1], [80.9, 0, 0], .7658),
                 ([0, .005, -1], [period, .4, 0], .4),
                 ([.005, 0, -1], [.4, period, 0], -.4),
                 ([0, 1, -1], [0, period, 0], 0)]
        for pcts, times, expected in cases:
            with self.subTest(pcts=pcts, times=times):
                car = relative(observed_sample(CarIdxLapDistPct=pcts, CarIdxEstTime=times))['cars'][0]
                self.assertAlmostEqual(car['gap'], expected)

    def test_malformed_roster_cannot_replace_other_valid_telemetry(self):
        for invalid in (7, True, 'invalid', {}, None):
            sample = observed_sample()
            sample['DriverInfo']['Drivers'] = invalid
            with self.subTest(drivers=invalid):
                data = make_provider(sample).get_telemetry_data()
                self.assertAlmostEqual(data['speed'], sample['Speed'] * 3.6)
                self.assertIn('fuel_finish_data', data)
                self.assertIsNone(data['relative_data']['cars'][0]['gap'])
        sample = observed_sample()
        sample['DriverInfo'] = {}
        sample['SessionInfo']['DriverInfo'] = 'invalid'
        data = make_provider(sample).get_telemetry_data()
        self.assertAlmostEqual(data['speed'], sample['Speed'] * 3.6)
        self.assertIn('fuel_finish_data', data)
        self.assertIsNone(data['relative_data']['cars'][0]['gap'])

    def test_missing_and_invalid_timing_never_fabricates_seconds(self):
        for bad in (None, -1, float('nan'), float('inf'), 0, 100):
            with self.subTest(bad=bad):
                car = relative(observed_sample(CarIdxEstTime=[80.9, bad, 0]))['cars'][0]
                self.assertIsNone(car['gap'])
                self.assertAlmostEqual(car['track_delta_pct'], .015)
        for period in (None, 0, -1, float('nan')):
            sample = observed_sample()
            sample['DriverInfo']['Drivers'][0]['CarClassEstLapTime'] = period
            self.assertIsNone(relative(sample)['cars'][0]['gap'])
        self.assertAlmostEqual(relative(observed_sample(CarIdxLapDistPct=[.99, 0, -1],
                                                        CarIdxEstTime=[80.9, 0, 0]))['cars'][0]['gap'], .7658)

    def test_invalid_indices_and_track_coordinates(self):
        for idx in (-1, None, 100):
            self.assertEqual(relative(observed_sample(PlayerCarIdx=idx))['cars'], [])
        for pct in (-1, None, float('nan'), 1.1):
            self.assertEqual(relative(observed_sample(CarIdxLapDistPct=[pct, .1, -1]))['cars'], [])

    def test_short_arrays_missing_period_and_physical_selection(self):
        for times in ([], [80.9], None):
            self.assertIsNone(relative(observed_sample(CarIdxEstTime=times))['cars'][0]['gap'])
        sample = observed_sample()
        sample['DriverInfo']['Drivers'][1].pop('CarClassEstLapTime')
        self.assertIsNone(relative(sample)['cars'][0]['gap'])
        sample = observed_sample(CarIdxLapDistPct=[.5, .51, .6], CarIdxEstTime=[40, None, 42])
        data = relative(sample)
        self.assertEqual([c['car_idx'] for c in data['cars']], [1, 2])
        self.assertIsNone(data['cars'][0]['gap'])
        self.assertAlmostEqual(data['cars'][1]['gap'], 2)

    def test_ai_ratings_never_contribute_and_placeholder_guard_is_exact(self):
        sample = observed_sample()
        sample['DriverInfo']['Drivers'][1]['IRating'] = 9000
        data = make_provider(sample).get_telemetry_data()
        sof = data['relative_data']['player_class_sof']
        self.assertEqual((sof['value'], sof['rated']), (None, 0))
        for changes in ({'IRating': 2}, {'LicLevel': 2}, {'LicSubLevel': 2},
                        {'LicColor': 0xff0000}, {'LicString': 'R 0.02'}):
            sample = observed_sample()
            sample['DriverInfo']['Drivers'][0].update(changes)
            self.assertIsNone(relative(sample)['player']['profile_unavailable_reason'])

    def test_real_human_profiles_and_strict_bot_flag(self):
        sample = observed_sample()
        player = sample['DriverInfo']['Drivers'][0]
        player.update(IRating=1700, LicString='A 3.42', LicSubLevel=342, LicColor=0x0153db)
        data = relative(sample)
        self.assertEqual(data['player']['irating'], 1700)
        self.assertEqual(data['player']['license_color'], '#0153db')
        for marker in (None, '1', 2):
            sample['DriverInfo']['Drivers'][1]['CarIsAI'] = marker
            self.assertIsNone(relative(sample)['cars'][0]['is_ai'])
        sample = observed_sample()
        sample['DriverInfo']['Drivers'][1]['CarIsAI'] = 0
        sample['DriverInfo']['Drivers'][2]['CarIsAI'] = 0
        self.assertEqual(relative(sample)['player']['irating'], 1)
        self.assertEqual(relative(sample)['player']['license'], 'R')


if __name__ == '__main__':
    unittest.main()

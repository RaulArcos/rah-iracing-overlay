"""Public provider regressions: radar physical presence, never fabricated lanes."""
import unittest
from test_telemetry_accuracy import base_sample, make_provider


def radar(**changes):
    sample = base_sample(PlayerCarIdx=0, CarIdxLapDistPct=[.5, .51, .49],
                         CarIdxLapCompleted=[0, 0, 0], CarIdxTrackSurface=[3, 3, 3])
    sample.update(changes)
    return make_provider(sample).get_telemetry_data()['radar_data']


class RadarTraffic(unittest.TestCase):
    def test_invalid_player_indices_never_use_tail_or_default_zero(self):
        for idx in (-1, None, True, .5, '0'):
            with self.subTest(idx=idx):
                self.assertEqual(radar(PlayerCarIdx=idx)['nearby'], [])

    def test_offtrack_and_invalid_physical_positions_never_wrap(self):
        for pct in (-1, 1.001, float('nan'), float('inf'), None):
            with self.subTest(pct=pct):
                result = radar(CarIdxLapDistPct=[0, pct, .01])
                self.assertEqual([c['car_idx'] for c in result['nearby']], [2])
        self.assertEqual(radar(CarIdxTrackSurface=[3, -1, 3])['nearby'][0]['car_idx'], 2)

    def test_practice_unknown_lap_counters_and_short_surface_arrays(self):
        for laps in ([], [None], [-1, -1, -1], [float('nan')]):
            result = radar(CarIdxLapCompleted=laps, CarIdxTrackSurface=[3])
            self.assertEqual([c['car_idx'] for c in result['nearby']], [1, 2])
            self.assertEqual(result['player_car_idx'], 0)

    def test_wrap_lapped_and_coincident_keep_physical_distance(self):
        result = radar(CarIdxLapDistPct=[1, .005, 1], CarIdxLapCompleted=[2, 0, 6])
        self.assertAlmostEqual(result['nearby'][0]['distance_pct'], .005)
        self.assertEqual(result['nearby'][1]['distance_pct'], 0)
        self.assertEqual(result['nearby'][1]['relation'], 'coincident')

    def test_absent_player_surface_clears_only_traffic(self):
        result = radar(CarIdxTrackSurface=[-1, 3, 3], CarLeftRight=4)
        self.assertEqual(result['nearby'], [])
        self.assertTrue(result['left_alert'])
        self.assertTrue(result['right_alert'])


if __name__ == '__main__':
    unittest.main()

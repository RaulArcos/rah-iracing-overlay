"""F1-style sector timing: interpolated splits, purple/green/yellow, resets."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from lap_delta import DeltaTracker, classify, sector_starts  # noqa: E402


class Sim:
    """Two cars at constant per-lap pace, polled at 30 Hz."""

    def __init__(self, player_laps, rival_lap=95.0, starts=(0.0, .3, .7)):
        self.t = 0.0
        self.player_laps = list(player_laps) + [(999.0, 999.0, 999.0)]  # keep driving after the last lap
        self.rival_lap = rival_lap
        self.split = {'Sectors': [{'SectorNum': i, 'SectorStartPct': s} for i, s in enumerate(starts)]}
        self.starts = starts
        self.on_pit = False

    def player_pct(self):
        elapsed = self.t
        for sectors in self.player_laps:
            lap = sum(sectors)
            if elapsed < lap:
                bounds = list(self.starts) + [1.0]
                for k, dur in enumerate(sectors):
                    if elapsed < dur:
                        return bounds[k] + elapsed / dur * (bounds[k + 1] - bounds[k])
                    elapsed -= dur
            elapsed -= lap
        return None

    def _get_sdk_value(self, key, default=None):
        pct = self.player_pct()
        rival = (self.t / self.rival_lap) % 1
        values = {
            'SessionTime': self.t, 'SessionNum': 0, 'PlayerCarIdx': 0,
            'CarIdxLapDistPct': [-1 if pct is None else pct % 1, rival],
            'CarIdxOnPitRoad': [self.on_pit, False], 'CarIdxTrackSurface': [3, 3],
            'CarIdxBestLapTime': [0, 0], 'LapCurrentLapTime': 1.0,
            'LapDeltaToBestLap': -0.25, 'LapDeltaToBestLap_OK': True, 'Lap': 1, 'LapBestLapTime': 0,
        }
        return values.get(key, default)

    def _get_session_dict(self, key):
        return self.split if key == 'SplitTimeInfo' else {}


def run(sim, tracker, until):
    payload = None
    while sim.t < until:
        payload = tracker.update(sim)
        sim.t += 1 / 30
    return payload


class LapDeltaTests(unittest.TestCase):
    def test_sector_starts_validation(self):
        self.assertEqual(sector_starts({}), [0.0, 1 / 3, 2 / 3])
        self.assertEqual(sector_starts({'Sectors': [{'SectorStartPct': .5}, {'SectorStartPct': 0}]}), [0, .5])
        self.assertEqual(sector_starts({'Sectors': [{'SectorStartPct': .5}]}), [0.0, 1 / 3, 2 / 3])

    def test_classify(self):
        self.assertEqual(classify(30, None, None), 'purple')
        self.assertEqual(classify(30, 31, 29), 'green')
        self.assertEqual(classify(31.5, 31, 29), 'yellow')
        self.assertEqual(classify(28, 31, 29), 'purple')

    def test_splits_are_interpolated_and_coloured_like_f1(self):
        laps = [(30.0, 32.0, 28.0), (29.5, 32.5, 27.0), (29.8, 31.0, 28.5)]
        sim = Sim([(20.0, 20.0, 20.0)] + laps, rival_lap=400.0)    # first lap: pit exit / out lap
        tracker = DeltaTracker()
        sim.on_pit = True
        run(sim, tracker, 59.5)
        sim.on_pit = False
        run(sim, tracker, 60 + 90 - .2)        # end of first timed lap
        payload = run(sim, tracker, 60 + 90 + .5)
        last = payload['last']
        self.assertAlmostEqual(last['time_s'], 90.0, delta=.02)
        self.assertEqual([s['state'] for s in last['sectors']], ['purple'] * 3)
        run(sim, tracker, 60 + 90 + 89 + .5)
        last = tracker.last
        times = [s['time_s'] for s in last['sectors']]
        for got, want in zip(times, laps[1]):
            self.assertAlmostEqual(got, want, delta=.02)
        self.assertEqual([s['state'] for s in last['sectors']], ['purple', 'yellow', 'purple'])
        self.assertAlmostEqual(last['sectors'][1]['delta_pb_s'], .5, delta=.02)
        run(sim, tracker, 60 + 90 + 89 + 89.3 + .5)
        self.assertEqual([s['state'] for s in tracker.last['sectors']], ['yellow', 'purple', 'yellow'])
        self.assertEqual(payload['delta_s'], -0.25)

    def test_rival_sets_purple_bar(self):
        sim = Sim([(20.0, 20.0, 20.0), (40.0, 40.0, 40.0)], rival_lap=60.0)
        tracker = DeltaTracker()
        sim.on_pit = True
        run(sim, tracker, 59.5)
        sim.on_pit = False
        run(sim, tracker, 60 + 120 + .5)
        # The rival's ~18 s sectors are the session best: the player's are only green.
        self.assertEqual([s['state'] for s in tracker.last['sectors']], ['green'] * 3)

    def test_pit_road_makes_an_out_lap(self):
        sim = Sim([(20.0, 20.0, 20.0), (30.0, 30.0, 30.0)])
        tracker = DeltaTracker()
        run(sim, tracker, 61)
        sim.on_pit = True
        run(sim, tracker, 62)
        sim.on_pit = False
        payload = run(sim, tracker, 60 + 90 + .5)
        self.assertEqual(payload['last']['state'], 'out')
        # The out lap's slower sectors never become personal bests.
        self.assertEqual(payload['personal_sector_s'], [None, 20.0, 20.0])


if __name__ == '__main__':
    unittest.main()

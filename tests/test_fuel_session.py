"""Fuel & Finish and Session Strip tests (T3, S1-S5).

Exercises the public DataProvider.get_telemetry_data entry point with an
injected fake SDK, the dedicated Socket.IO namespaces/events through the
flask-socketio test client (the telemetry thread is stubbed, no simulator is
started), and the HTTP discovery/asset surface for both new overlays.
"""

import math
import os
import sys
import unittest
from unittest import mock

# Must be set before web_interface is imported (threading mode, no eventlet).
os.environ['FORCE_THREADING_MODE'] = 'true'

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from test_telemetry_accuracy import FakeSDK, base_sample, make_provider  # noqa: E402
from web_interface import WebInterface  # noqa: E402

NEW_OVERLAYS = ('fuel_finish', 'session_strip')


def fuel_sample(**overrides):
    """A clean, on-track, lap-limited sample with fuel telemetry."""
    sample = dict(
        Lap=1,
        LapLastLapTime=0.0,
        FuelLevel=50.0,
        FuelLevelPct=0.5,
        OnPitRoad=False,
        PlayerCarInPitStall=False,
        IsOnTrack=True,
        IsReplayPlaying=False,
        SessionLapsRemainEx=10,
        SessionLapsRemain=10,
        SessionTimeRemain=604800.0,
        SessionState=4,
        SessionFlags=4,
        SessionInfo={'Sessions': [{
            'SessionNum': 0, 'SessionType': 'Race',
            'SessionLaps': 10, 'SessionTime': 'unlimited'}]},
    )
    sample.update(overrides)
    return base_sample(**sample)


def poll(provider, lap, fuel, last=0.0, key='fuel_finish_data', **extra):
    provider.ir_sdk.update(Lap=lap, FuelLevel=fuel, LapLastLapTime=last, **extra)
    return provider.get_telemetry_data()[key]


def seeded_provider(laps=((2, 48.5, 90.0), (3, 47.0, 91.0), (4, 45.5, 90.5)), **overrides):
    """Baseline at lap 1 / 50 L, then consecutive clean boundaries.

    The first boundary (lap 2) closes the startup partial lap, so only the
    following ones produce burn samples: 1.5 L, 1.5 L here.
    """
    provider = make_provider(fuel_sample(**overrides))
    poll(provider, 1, 50.0)
    data = None
    for lap, fuel, last in laps:
        data = poll(provider, lap, fuel, last)
    return provider, data


class TestPayloadContract(unittest.TestCase):
    def test_connected_payload_adds_nullable_fuel_and_session_sections(self):
        result = make_provider(fuel_sample()).get_telemetry_data()
        self.assertIsInstance(result['fuel_finish_data'], dict)
        self.assertIsInstance(result['session_strip_data'], dict)
        # Legacy keys stay present.
        for key in ('relative_data', 'track_map_data', 'radar_data',
                    'blindspot_data', 'laptime_graph_data'):
            self.assertIn(key, result)

    def test_disconnected_provider_still_returns_empty_dict(self):
        provider = make_provider(fuel_sample())
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_everything_is_unavailable_not_zero_without_telemetry(self):
        provider = make_provider({'Lap': 1})
        result = provider.get_telemetry_data()
        fuel = result['fuel_finish_data']
        self.assertIsNone(fuel['fuel_level_l'])
        self.assertIsNone(fuel['fuel_level_pct'])
        self.assertIsNone(fuel['avg_burn_l_per_lap'])
        self.assertIsNone(fuel['laps_of_fuel'])
        self.assertIsNone(fuel['finish_laps_remaining'])
        self.assertIsNone(fuel['finish_fuel_needed_l'])
        self.assertIsNone(fuel['finish_fuel_to_add_l'])
        self.assertEqual(fuel['burn_sample_count'], 0)
        strip = result['session_strip_data']
        for key in ('session_type', 'limit', 'session_laps_total', 'session_time_total_s',
                    'laps_remaining', 'time_remaining_s', 'state', 'flags',
                    'position', 'class_position'):
            self.assertIsNone(strip[key], key)


class TestFuelLevel(unittest.TestCase):
    def test_reports_liters_and_percent(self):
        fuel = make_provider(fuel_sample(FuelLevel=42.5, FuelLevelPct=0.425)).get_telemetry_data()['fuel_finish_data']
        self.assertEqual(fuel['fuel_level_l'], 42.5)
        self.assertAlmostEqual(fuel['fuel_level_pct'], 42.5)

    def test_zero_fuel_is_a_real_zero(self):
        fuel = make_provider(fuel_sample(FuelLevel=0.0, FuelLevelPct=0.0)).get_telemetry_data()['fuel_finish_data']
        self.assertEqual(fuel['fuel_level_l'], 0.0)
        self.assertIsNotNone(fuel['fuel_level_l'])
        self.assertEqual(fuel['fuel_level_pct'], 0.0)
        self.assertIsNotNone(fuel['fuel_level_pct'])

    def test_missing_invalid_or_out_of_range_values_are_none(self):
        for bad in (None, float('nan'), float('inf'), -1.0, 'x'):
            with self.subTest(fuel=bad):
                fuel = make_provider(fuel_sample(FuelLevel=bad, FuelLevelPct=bad)).get_telemetry_data()['fuel_finish_data']
                self.assertIsNone(fuel['fuel_level_l'])
                self.assertIsNone(fuel['fuel_level_pct'])
        fuel = make_provider(fuel_sample(FuelLevelPct=1.7)).get_telemetry_data()['fuel_finish_data']
        self.assertEqual(fuel['fuel_level_l'], 50.0)
        self.assertIsNone(fuel['fuel_level_pct'])

    def test_payload_is_labelled_advisory_estimate(self):
        fuel = make_provider(fuel_sample()).get_telemetry_data()['fuel_finish_data']
        self.assertIs(fuel['advisory'], True)
        self.assertIs(fuel['is_estimate'], True)


class TestBurnSampling(unittest.TestCase):
    def test_samples_only_full_boundary_to_boundary_laps(self):
        provider = make_provider(fuel_sample())
        self.assertEqual(poll(provider, 1, 50.0)['burn_sample_count'], 0)
        self.assertEqual(poll(provider, 1, 49.2)['burn_sample_count'], 0)
        # Startup partial lap: the first boundary only starts a sample.
        data = poll(provider, 2, 48.5, 90.0)
        self.assertEqual(data['burn_sample_count'], 0)
        self.assertIsNone(data['avg_burn_l_per_lap'])
        poll(provider, 2, 47.8)
        data = poll(provider, 3, 47.0, 91.0)
        self.assertEqual(data['burn_sample_count'], 1)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.5)
        data = poll(provider, 4, 45.4, 92.0)
        self.assertEqual(data['burn_sample_count'], 2)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.55)
        self.assertEqual(data['burn_source'], 'observed_clean_laps')
        self.assertAlmostEqual(data['laps_of_fuel'], 45.4 / 1.55, places=2)

    def test_duplicate_polls_of_a_lap_add_no_sample(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        for fuel in (45.4, 45.3, 45.3):
            data = poll(provider, 4, fuel, 90.5)
        self.assertEqual(data['burn_sample_count'], 2)

    def test_no_samples_means_no_average_or_laps_of_fuel(self):
        data = make_provider(fuel_sample()).get_telemetry_data()['fuel_finish_data']
        self.assertEqual(data['burn_sample_count'], 0)
        self.assertIsNone(data['burn_source'])
        self.assertIsNone(data['avg_burn_l_per_lap'])
        self.assertIsNone(data['laps_of_fuel'])

    def test_pit_road_at_any_poll_rejects_the_lap(self):
        provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
        poll(provider, 2, 48.0)
        poll(provider, 2, 47.8, OnPitRoad=True)
        poll(provider, 2, 47.6, OnPitRoad=False)
        data = poll(provider, 3, 47.0, 95.0)
        self.assertEqual(data['burn_sample_count'], 0)
        # The following clean lap is sampled again.
        data = poll(provider, 4, 45.5, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.5)

    def test_pit_stall_replay_and_off_track_reject_the_lap(self):
        for field, value in (('PlayerCarInPitStall', True),
                             ('IsReplayPlaying', True),
                             ('IsOnTrack', False)):
            with self.subTest(field=field):
                provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
                poll(provider, 2, 48.0, **{field: value})
                poll(provider, 2, 47.5, **{field: not value})
                data = poll(provider, 3, 47.0, 90.0)
                self.assertEqual(data['burn_sample_count'], 0)

    def test_refuel_at_any_poll_rejects_the_lap_and_clears_old_samples(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        poll(provider, 4, 45.0)
        data = poll(provider, 4, 65.0)  # refuel mid-lap
        self.assertEqual(data['burn_sample_count'], 0)
        self.assertIsNone(data['avg_burn_l_per_lap'])
        data = poll(provider, 5, 63.5, 100.0)
        self.assertEqual(data['burn_sample_count'], 0)
        # Fresh samples accumulate afterwards.
        data = poll(provider, 6, 62.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.5)

    def assert_gradual_refuel_discards_everything(self, **flags):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        fuel = 45.5
        while fuel < 60.0:
            fuel = round(fuel + 0.05, 2)
            data = poll(provider, 4, fuel, 90.5, **flags)
        self.assertEqual(data['burn_sample_count'], 0)
        self.assertIsNone(data['avg_burn_l_per_lap'])
        self.assertIsNone(data['laps_of_fuel'])
        # The refuelled lap is never sampled, and a fresh stint starts clean.
        data = poll(provider, 5, 58.5, 90.0, **{k: False for k in flags})
        self.assertEqual(data['burn_sample_count'], 0)
        data = poll(provider, 6, 57.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.5)

    def test_gradual_refuel_in_the_pit_stall_discards_old_samples(self):
        self.assert_gradual_refuel_discards_everything(OnPitRoad=True, PlayerCarInPitStall=True)

    def test_gradual_refuel_outside_the_pit_is_cumulative_not_per_poll(self):
        self.assert_gradual_refuel_discards_everything()

    def test_tiny_non_cumulative_fuel_jitter_is_tolerated(self):
        provider, data = seeded_provider()
        for fuel in (45.5, 45.55, 45.5, 45.54, 45.51, 45.55, 45.5):
            data = poll(provider, 4, fuel, 90.5)
        self.assertEqual(data['burn_sample_count'], 2)
        data = poll(provider, 5, 44.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 3)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 1.5)

    def test_slow_normal_burn_does_not_invalidate_the_lap(self):
        provider, _ = seeded_provider()
        fuel = 45.5
        while fuel > 44.05:
            fuel = round(fuel - 0.05, 2)
            data = poll(provider, 4, fuel, 90.5)
        data = poll(provider, 5, 44.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 3)

    def test_refuel_on_the_boundary_poll_is_rejected(self):
        provider, _ = seeded_provider()
        poll(provider, 4, 45.0)
        data = poll(provider, 5, 70.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 0)

    def test_invalid_fuel_reading_at_any_poll_rejects_the_lap(self):
        for bad in (None, float('nan'), -2.0):
            with self.subTest(fuel=bad):
                provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
                poll(provider, 2, bad)
                data = poll(provider, 3, 47.0, 90.0)
                self.assertEqual(data['burn_sample_count'], 0)

    def test_invalid_fuel_on_the_boundary_poll_rejects_that_lap(self):
        provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
        data = poll(provider, 3, None, 90.0)
        self.assertEqual(data['burn_sample_count'], 0)
        self.assertIsNone(data['fuel_level_l'])
        # The lap that follows has no known starting level either.
        data = poll(provider, 4, 45.5, 90.0)
        self.assertEqual(data['burn_sample_count'], 0)
        data = poll(provider, 5, 44.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)

    def test_invalid_lap_times_reject_the_sample(self):
        for bad in (0.0, -3.0, float('nan'), float('inf'), None):
            with self.subTest(last=bad):
                provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
                data = poll(provider, 3, 47.0, bad)
                self.assertEqual(data['burn_sample_count'], 0)
                data = poll(provider, 4, 45.5, 90.0)
                self.assertEqual(data['burn_sample_count'], 1)

    def test_non_positive_burn_is_rejected(self):
        provider, _ = seeded_provider(laps=((2, 48.5, 90.0),))
        data = poll(provider, 3, 48.5, 90.0)  # no fuel used
        self.assertEqual(data['burn_sample_count'], 0)

    def test_skipped_lap_polls_are_never_sampled(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        data = poll(provider, 6, 41.0, 90.0)  # laps 4 and 5 were not observed
        self.assertEqual(data['burn_sample_count'], 2)
        # Lap 6 did not start on an observed boundary: rejected too.
        data = poll(provider, 7, 39.5, 90.0)
        self.assertEqual(data['burn_sample_count'], 2)
        data = poll(provider, 8, 38.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 3)

    def test_samples_reset_on_session_change(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        data = poll(provider, 1, 60.0, SessionNum=1)
        self.assertEqual(data['burn_sample_count'], 0)
        poll(provider, 2, 58.5, 90.0)
        data = poll(provider, 3, 57.0, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)

    def test_samples_reset_on_reconnect(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        provider.disconnect()
        self.assertTrue(provider.connect())
        data = provider.get_telemetry_data()['fuel_finish_data']
        self.assertEqual(data['burn_sample_count'], 0)
        data = poll(provider, 5, 44.0, 90.0)  # closes the startup partial lap
        self.assertEqual(data['burn_sample_count'], 0)
        data = poll(provider, 6, 42.5, 90.0)
        self.assertEqual(data['burn_sample_count'], 1)

    def test_samples_reset_on_lap_rollback(self):
        provider, data = seeded_provider()
        self.assertEqual(data['burn_sample_count'], 2)
        data = poll(provider, 1, 50.0)
        self.assertEqual(data['burn_sample_count'], 0)

    def test_rolling_window_keeps_the_latest_ten_samples(self):
        provider = make_provider(fuel_sample(FuelLevel=100.0))
        poll(provider, 1, 100.0)
        fuel = 100.0
        data = None
        for lap in range(2, 16):
            fuel -= 1.0 if lap < 6 else 2.0
            data = poll(provider, lap, fuel, 90.0)
        self.assertEqual(data['burn_sample_count'], 10)
        self.assertAlmostEqual(data['avg_burn_l_per_lap'], 2.0)


class TestFinishEstimate(unittest.TestCase):
    def test_lap_limited_finish_uses_laps_remaining_and_average_burn(self):
        _, data = seeded_provider(SessionLapsRemainEx=5)
        self.assertEqual(data['finish_basis'], 'laps_remaining')
        self.assertEqual(data['finish_laps_remaining'], 5)
        self.assertAlmostEqual(data['finish_fuel_needed_l'], 7.5)
        self.assertEqual(data['finish_fuel_to_add_l'], 0.0)
        self.assertIsNotNone(data['finish_fuel_to_add_l'])

    def test_fuel_to_add_when_short(self):
        provider, _ = seeded_provider(SessionLapsRemainEx=5)
        data = poll(provider, 4, 4.0, 90.0)
        self.assertAlmostEqual(data['finish_fuel_needed_l'], 7.5)
        self.assertAlmostEqual(data['finish_fuel_to_add_l'], 3.5)

    def test_extended_laps_remaining_is_preferred_over_legacy(self):
        _, data = seeded_provider(SessionLapsRemainEx=3, SessionLapsRemain=9)
        self.assertEqual(data['finish_laps_remaining'], 3)
        _, data = seeded_provider(SessionLapsRemainEx=None, SessionLapsRemain=9)
        self.assertEqual(data['finish_laps_remaining'], 9)

    def test_confirmed_zero_laps_remaining_is_valid(self):
        _, data = seeded_provider(SessionLapsRemainEx=0)
        self.assertEqual(data['finish_laps_remaining'], 0)
        self.assertEqual(data['finish_fuel_needed_l'], 0.0)
        self.assertEqual(data['finish_fuel_to_add_l'], 0.0)

    def test_unlimited_and_invalid_laps_remaining_give_no_finish(self):
        for bad in (32767, 32000, -1, float('nan'), None):
            with self.subTest(remaining=bad):
                _, data = seeded_provider(SessionLapsRemainEx=bad, SessionLapsRemain=None,
                                          SessionInfo={'Sessions': [{
                                              'SessionNum': 0, 'SessionType': 'Race',
                                              'SessionLaps': 'unlimited', 'SessionTime': 'unlimited'}]})
                self.assertIsNone(data['finish_laps_remaining'])
                self.assertIsNone(data['finish_fuel_needed_l'])
                self.assertIsNone(data['finish_fuel_to_add_l'])
                self.assertIsNone(data['finish_basis'])

    def test_no_burn_sample_gives_no_fuel_amounts(self):
        data = make_provider(fuel_sample(SessionLapsRemainEx=5)).get_telemetry_data()['fuel_finish_data']
        self.assertEqual(data['finish_laps_remaining'], 5)
        self.assertIsNone(data['finish_fuel_needed_l'])
        self.assertIsNone(data['finish_fuel_to_add_l'])

    def test_timed_race_is_a_conservative_estimate_from_the_fastest_clean_lap(self):
        timed = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                               'SessionLaps': 'unlimited', 'SessionTime': '3600.0000 sec'}]}
        provider, _ = seeded_provider(
            SessionInfo=timed, SessionLapsRemainEx=32767, SessionLapsRemain=32767,
            SessionTimeRemain=600.0)
        data = poll(provider, 4, 45.5, 90.5, SessionTimeRemain=600.0)
        # clean lap times so far: 91.0 and 90.5 -> fastest 90.5 s.
        expected_laps = 600.0 / 90.5 + 1.0
        self.assertEqual(data['finish_basis'], 'timed_conservative_estimate')
        self.assertAlmostEqual(data['finish_laps_remaining'], expected_laps, places=2)
        self.assertAlmostEqual(data['finish_fuel_needed_l'], 1.5 * expected_laps, places=1)

    def test_timed_race_without_pace_or_with_sentinel_time_is_unavailable(self):
        timed = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                               'SessionLaps': 'unlimited', 'SessionTime': '3600.0000 sec'}]}
        data = make_provider(fuel_sample(
            SessionInfo=timed, SessionLapsRemainEx=32767, SessionTimeRemain=600.0)
        ).get_telemetry_data()['fuel_finish_data']
        self.assertIsNone(data['finish_fuel_needed_l'])
        self.assertIsNone(data['finish_laps_remaining'])
        for bad in (604800.0, -5.0, float('nan'), None):
            with self.subTest(time=bad):
                _, data = seeded_provider(SessionInfo=timed, SessionLapsRemainEx=32767,
                                          SessionTimeRemain=bad)
                self.assertIsNone(data['finish_fuel_needed_l'])
                self.assertIsNone(data['finish_basis'])

    def test_timed_estimate_requires_session_info_to_establish_a_time_limit(self):
        cases = {
            'metadata missing': None,
            'no sessions': {'Sessions': []},
            'other session only': {'Sessions': [{'SessionNum': 3, 'SessionType': 'Race',
                                                 'SessionLaps': 'unlimited', 'SessionTime': '3600.0000 sec'}]},
            'limits unknown': {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race'}]},
            'garbage limits': {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                                             'SessionLaps': 'soon', 'SessionTime': 'later'}]},
            'unlimited': {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                                        'SessionLaps': 'unlimited', 'SessionTime': 'unlimited'}]},
            'lap limit only': {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                                             'SessionLaps': 10, 'SessionTime': 'unlimited'}]},
        }
        for label, info in cases.items():
            with self.subTest(case=label):
                provider, _ = seeded_provider(SessionInfo=info, SessionLapsRemainEx=32767,
                                              SessionLapsRemain=32767, SessionTimeRemain=600.0)
                data = poll(provider, 5, 44.0, 90.5, SessionTimeRemain=600.0)
                self.assertGreater(data['burn_sample_count'], 0)
                self.assertIsNone(data['finish_basis'])
                self.assertIsNone(data['finish_laps_remaining'])
                self.assertIsNone(data['finish_fuel_needed_l'])
                self.assertIsNone(data['finish_fuel_to_add_l'])

    def test_timed_estimate_is_offered_for_time_limited_metadata(self):
        for label, laps in (('time', 'unlimited'), ('laps_and_time', 10)):
            with self.subTest(case=label):
                info = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                                      'SessionLaps': laps, 'SessionTime': '3600.0000 sec'}]}
                provider, _ = seeded_provider(SessionInfo=info, SessionLapsRemainEx=32767,
                                              SessionLapsRemain=32767, SessionTimeRemain=600.0)
                data = poll(provider, 5, 44.0, 90.5, SessionTimeRemain=600.0)
                self.assertEqual(data['finish_basis'], 'timed_conservative_estimate')
                self.assertIsNotNone(data['finish_fuel_needed_l'])

    def test_lap_limit_finish_is_kept_when_metadata_is_missing(self):
        _, data = seeded_provider(SessionInfo=None, SessionLapsRemainEx=5)
        self.assertEqual(data['finish_basis'], 'laps_remaining')
        self.assertAlmostEqual(data['finish_fuel_needed_l'], 7.5)

    def test_unlimited_session_has_no_finish_even_with_a_time_value(self):
        unlimited = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Practice',
                                   'SessionLaps': 'unlimited', 'SessionTime': 'unlimited'}]}
        _, data = seeded_provider(SessionInfo=unlimited, SessionLapsRemainEx=32767,
                                  SessionTimeRemain=600.0)
        self.assertIsNone(data['finish_fuel_needed_l'])
        self.assertIsNone(data['finish_basis'])


class TestSessionStrip(unittest.TestCase):
    def strip(self, **overrides):
        return make_provider(fuel_sample(**overrides)).get_telemetry_data()['session_strip_data']

    def test_session_type_comes_from_metadata_and_is_never_fabricated(self):
        info = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Qualify'}]}
        self.assertEqual(self.strip(SessionInfo=info)['session_type'], 'Qualify')
        self.assertIsNone(self.strip(SessionInfo=None)['session_type'])
        self.assertIsNone(self.strip(SessionInfo={'Sessions': []})['session_type'])
        self.assertIsNone(self.strip(SessionNum=4)['session_type'])

    def test_session_type_reads_yaml_string_metadata(self):
        yaml_text = "Sessions:\n- SessionNum: 0\n  SessionType: Practice\n  SessionLaps: unlimited\n  SessionTime: 1800.0000 sec\n"
        strip = self.strip(SessionInfo=yaml_text)
        self.assertEqual(strip['session_type'], 'Practice')
        self.assertEqual(strip['limit'], 'time')
        self.assertEqual(strip['session_time_total_s'], 1800.0)

    def test_limit_kinds_from_metadata(self):
        def info(laps, time):
            return {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                                  'SessionLaps': laps, 'SessionTime': time}]}
        strip = self.strip(SessionInfo=info(20, 'unlimited'))
        self.assertEqual((strip['limit'], strip['session_laps_total'], strip['session_time_total_s']),
                         ('laps', 20, None))
        strip = self.strip(SessionInfo=info('unlimited', '1800.0000 sec'))
        self.assertEqual((strip['limit'], strip['session_laps_total'], strip['session_time_total_s']),
                         ('time', None, 1800.0))
        strip = self.strip(SessionInfo=info('unlimited', 'unlimited'))
        self.assertEqual(strip['limit'], 'unlimited')
        strip = self.strip(SessionInfo=info(30, '2400.0000 sec'))
        self.assertEqual(strip['limit'], 'laps_and_time')
        self.assertIsNone(self.strip(SessionInfo=None)['limit'])

    def test_laps_remaining_prefers_extended_and_guards_sentinels(self):
        self.assertEqual(self.strip(SessionLapsRemainEx=7, SessionLapsRemain=9)['laps_remaining'], 7)
        self.assertEqual(self.strip(SessionLapsRemainEx=7)['laps_remaining_source'], 'SessionLapsRemainEx')
        legacy = self.strip(SessionLapsRemainEx=None, SessionLapsRemain=9)
        self.assertEqual((legacy['laps_remaining'], legacy['laps_remaining_source']), (9, 'SessionLapsRemain'))
        zero = self.strip(SessionLapsRemainEx=0)
        self.assertEqual(zero['laps_remaining'], 0)
        self.assertIsNotNone(zero['laps_remaining'])
        for bad in (32767, 32000, -1, float('nan')):
            with self.subTest(remaining=bad):
                strip = self.strip(SessionLapsRemainEx=bad, SessionLapsRemain=9)
                self.assertIsNone(strip['laps_remaining'])
        none_at_all = self.strip(SessionLapsRemainEx=None, SessionLapsRemain=None)
        self.assertIsNone(none_at_all['laps_remaining'])
        self.assertIsNone(none_at_all['laps_remaining_source'])

    def test_time_remaining_guards_unlimited_and_invalid_values(self):
        timed = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race',
                               'SessionLaps': 'unlimited', 'SessionTime': '3600.0000 sec'}]}
        self.assertEqual(self.strip(SessionInfo=timed, SessionTimeRemain=1234.5)['time_remaining_s'], 1234.5)
        zero = self.strip(SessionInfo=timed, SessionTimeRemain=0.0)
        self.assertEqual(zero['time_remaining_s'], 0.0)
        self.assertIsNotNone(zero['time_remaining_s'])
        for bad in (604800.0, -1.0, float('nan'), float('inf'), None):
            with self.subTest(time=bad):
                self.assertIsNone(self.strip(SessionInfo=timed, SessionTimeRemain=bad)['time_remaining_s'])
        unlimited = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Practice',
                                   'SessionLaps': 'unlimited', 'SessionTime': 'unlimited'}]}
        self.assertIsNone(self.strip(SessionInfo=unlimited, SessionTimeRemain=1234.5)['time_remaining_s'])

    def test_session_state_uses_the_installed_sdk_enum(self):
        self.assertEqual(self.strip(SessionState=4)['state'], 'racing')
        self.assertEqual(self.strip(SessionState=4)['state_code'], 4)
        self.assertEqual(self.strip(SessionState=5)['state'], 'checkered')
        for bad in (None, 0, 99, -1, 'x'):
            with self.subTest(state=bad):
                strip = self.strip(SessionState=bad)
                self.assertIsNone(strip['state'])
                self.assertIsNone(strip['state_code'])

    def test_session_flags_decode_known_bits_only(self):
        # 0x4 green, 0x20 blue (installed irsdk.Flags); 0x00200000 is not a known bit.
        self.assertEqual(self.strip(SessionFlags=0x4 | 0x20 | 0x00200000)['flags'], ['green', 'blue'])
        self.assertEqual(self.strip(SessionFlags=0x80000000 | 0x1)['flags'], ['checkered', 'start_go'])
        none_set = self.strip(SessionFlags=0)['flags']
        self.assertEqual(none_set, [])
        self.assertIsNotNone(none_set)
        for bad in (None, -1, 'x', float('nan'), 1.5):
            with self.subTest(flags=bad):
                self.assertIsNone(self.strip(SessionFlags=bad)['flags'])

    def test_player_position_and_class_position(self):
        strip = self.strip()
        self.assertEqual((strip['position'], strip['class_position']), (3, 3))
        strip = self.strip(CarIdxPosition=[0, 0, 1, 2], CarIdxClassPosition=[0, 0, 1, 2])
        self.assertIsNone(strip['position'])
        self.assertIsNone(strip['class_position'])
        strip = self.strip(PlayerCarIdx=9)
        self.assertIsNone(strip['position'])
        strip = self.strip(CarIdxPosition=None, CarIdxClassPosition=None)
        self.assertIsNone(strip['position'])
        self.assertIsNone(strip['class_position'])

    def test_lap_is_reported_when_numeric(self):
        self.assertEqual(self.strip(Lap=5)['lap'], 5)
        self.assertIsNone(self.strip(Lap=None)['lap'])


class TestLapHistoryPreserved(unittest.TestCase):
    def test_lap_graph_history_ignores_fuel_pit_and_refuel_state(self):
        provider = make_provider(fuel_sample())
        history = provider.get_telemetry_data()['laptime_graph_data']['history']
        self.assertEqual(history, [])
        laps = [(2, 48.0, 90.0, {}),
                (3, 46.5, 91.0, {'OnPitRoad': True}),
                (4, 70.0, 92.0, {'OnPitRoad': False}),
                (5, None, 93.0, {})]
        for lap, fuel, last, extra in laps:
            provider.ir_sdk.update(Lap=lap, FuelLevel=fuel, LapLastLapTime=last, **extra)
            history = provider.get_telemetry_data()['laptime_graph_data']['history']
        self.assertEqual(history, [90.0, 91.0, 92.0, 93.0])
        for lap in range(6, 20):
            provider.ir_sdk.update(Lap=lap, FuelLevel=40.0, LapLastLapTime=float(lap))
            history = provider.get_telemetry_data()['laptime_graph_data']['history']
        self.assertEqual(len(history), 10)
        self.assertEqual(history[-1], 19.0)


class SocketTestBase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(WebInterface, '_start_telemetry_thread')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.web = WebInterface()
        self.web.data_provider.ir_sdk = FakeSDK(fuel_sample())
        self.web.data_provider.is_connected = True

    def client(self, namespace, disconnect=True):
        client = self.web.socketio.test_client(self.web.app, namespace=namespace)
        if disconnect:
            # Pre-existing namespaces declare on_disconnect(self) and fail on
            # the reason argument newer flask-socketio passes; leave them be.
            self.addCleanup(client.disconnect, namespace)
        client.get_received(namespace)  # drop connect acknowledgement
        return client

    def events(self, client, namespace, name):
        # Socket.IO carries a None payload as an event without arguments.
        return [e['args'][0] if e['args'] else None
                for e in client.get_received(namespace) if e['name'] == name]


class TestSocketEvents(SocketTestBase):
    def test_fuel_finish_event_carries_the_provider_payload(self):
        client = self.client('/fuel_finish')
        self.web._process_telemetry_data()
        payloads = self.events(client, '/fuel_finish', 'fuel_finish_update')
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]['fuel_level_l'], 50.0)
        self.assertIsNone(payloads[0]['avg_burn_l_per_lap'])
        self.assertIsNone(payloads[0]['finish_fuel_needed_l'])

    def test_session_strip_event_keeps_nulls_and_real_zeroes(self):
        self.web.data_provider.ir_sdk.update(SessionLapsRemainEx=0, SessionFlags=0, SessionInfo=None)
        client = self.client('/session_strip')
        self.web._process_telemetry_data()
        payloads = self.events(client, '/session_strip', 'session_strip_update')
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]['laps_remaining'], 0)
        self.assertEqual(payloads[0]['flags'], [])
        self.assertIsNone(payloads[0]['session_type'])
        self.assertIsNone(payloads[0]['limit'])

    def test_missing_sections_emit_a_null_payload(self):
        client = self.client('/fuel_finish')
        strip_client = self.client('/session_strip')
        provider_data = {'speed': 1.0, 'gear': 2}
        with mock.patch.object(self.web.data_provider, 'get_telemetry_data', return_value=provider_data):
            self.web._process_telemetry_data()
        self.assertEqual(self.events(client, '/fuel_finish', 'fuel_finish_update'), [None])
        self.assertEqual(self.events(strip_client, '/session_strip', 'session_strip_update'), [None])

    def test_legacy_events_do_not_gain_the_new_sections(self):
        telemetry = self.client('/input_telemetry', disconnect=False)
        graph = self.client('/laptime_graph', disconnect=False)
        self.web._process_telemetry_data()
        payload = self.events(telemetry, '/input_telemetry', 'telemetry_update')[0]
        self.assertNotIn('fuel_finish_data', payload)
        self.assertNotIn('session_strip_data', payload)
        for key in ('speed', 'gear', 'throttle', 'brake', 'clutch', 'steering_wheel_angle',
                    'relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data'):
            self.assertIn(key, payload)
        self.assertEqual(self.events(graph, '/laptime_graph', 'laptime_graph_update')[0]['history'], [])


class TestHttpSurface(SocketTestBase):
    def test_both_overlays_are_discoverable_with_valid_properties(self):
        http = self.web.app.test_client()
        overlays = {o['folder_name']: o for o in http.get('/get_overlays').get_json()}
        for name in NEW_OVERLAYS:
            self.assertIn(name, overlays)
            self.assertTrue(overlays[name]['display_name'])
            self.assertTrue(overlays[name]['description'])
            self.assertNotIn('?', overlays[name]['url'])

    def test_pages_and_assets_serve_and_theme_assets_load_after_base_css(self):
        http = self.web.app.test_client()
        for name in NEW_OVERLAYS:
            with self.subTest(overlay=name):
                page = http.get(f'/overlay/{name}')
                self.addCleanup(page.close)
                self.assertEqual(page.status_code, 200)
                body = page.get_data(as_text=True)
                self.assertIn('overlay-theme.css', body)
                self.assertIn('overlay_theme.js', body)
                self.assertIn('socket.io.min.js', body)
                self.assertLess(body.index(f'{name}.css'), body.index('overlay-theme.css'))
                for asset in (f'{name}.css', f'{name}.js'):
                    response = http.get(f'/overlay/{name}/static/{asset}')
                    self.addCleanup(response.close)
                    self.assertEqual(response.status_code, 200, asset)
                for theme in ('glass', 'original', 'neon'):
                    themed = http.get(f'/overlay/{name}?theme={theme}')
                    self.addCleanup(themed.close)
                    self.assertEqual(themed.get_data(), page.get_data())


if __name__ == '__main__':
    unittest.main()

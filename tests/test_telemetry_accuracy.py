"""Accuracy regression tests for telemetry decoding (T1, S3-S5).

Exercises the public DataProvider.get_telemetry_data entry point with an
injected fake SDK (connected / disconnected / reset cases) plus the overlay
front-end scripts via the Node test runner (tests/test_accuracy_frontend.cjs).
"""

import copy
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from data_provider import DataProvider  # noqa: E402


class FakeSDK:
    """Minimal dict-backed stand-in for irsdk.IRSDK.

    Missing keys return None, mirroring irsdk's __getitem__ behaviour for
    unknown session-info sections.
    """

    def __init__(self, data):
        self._data = copy.deepcopy(data)
        self.freeze_calls = 0

    def __getitem__(self, key):
        value = self._data.get(key)
        return list(value) if isinstance(value, list) else value

    def freeze_var_buffer_latest(self):
        self.freeze_calls += 1

    def startup(self):
        return True

    def shutdown(self):
        pass

    def update(self, **changes):
        for key, value in changes.items():
            self._data[key] = copy.deepcopy(value)


def make_provider(data):
    provider = DataProvider()
    provider.ir_sdk = FakeSDK(data)
    provider.is_connected = True
    return provider


def base_sample(**overrides):
    """Frozen finite sample shared by the differential check and tests."""
    sample = {
        'Speed': 55.5,
        'Gear': 4,
        'Throttle': 0.62,
        'Brake': 0.11,
        'Clutch': 0.0,
        'SteeringWheelAngle': -0.07,
        'PlayerCarIdx': 1,
        'CarIdxPosition': [0, 3, 1, 2],
        'CarIdxClassPosition': [0, 3, 1, 2],
        'CarIdxLapDistPct': [-1.0, 0.50, 0.55, 0.10],
        'CarIdxLapCompleted': [0, 2, 2, 1],
        'CarIdxOnPitRoad': [False, False, False, False],
        'CarIdxTrackSurface': [-1, 1, 1, 1],
        'LapBestLapTime': 85.0,
        'LapLastLapTime': 0.0,
        'LapCurrentLapTime': 34.5,
        'LapDeltaToBestLap': -0.4,
        'LapDeltaToBestLap_OK': True,
        'CarIdxBestLapTime': [-1.0, 85.0, 84.0, 88.0],
        'CarIdxLastLapTime': [-1.0, 0.0, 0.0, 0.0],
        'CarIdxEstTime': [-1.0, -1.0, 500.0, 480.0],
        'SessionNum': 0,
        'SessionInfo': {'Sessions': [{'SessionNum': 0, 'SessionType': 'Race'}]},
        'WeekendInfo': {'TrackLength': '5.891 km'},
        'DriverInfo': {
            'Drivers': [
                {'CarIdx': 1, 'CarNumber': '21', 'UserName': 'Ada'},
                {'CarIdx': 2, 'CarNumber': '7', 'UserName': 'Bob'},
                {'CarIdx': 3, 'CarNumber': '44', 'UserName': 'Cyd'},
            ]
        },
        'Lap': 2,
        'CarLeftRight': 1,
        'SessionLapsRemain': 20,
        'SessionTimeRemain': 1800,
    }
    sample.update(copy.deepcopy(overrides))
    return sample


def relative_car(result, car_idx):
    return next((c for c in result['relative_data']['cars'] if c['car_idx'] == car_idx), None)


class TestConnectionContract(unittest.TestCase):
    def test_disconnected_returns_empty_dict(self):
        provider = make_provider(base_sample())
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_connected_returns_all_existing_payload_keys(self):
        result = make_provider(base_sample()).get_telemetry_data()
        for key in ('speed', 'gear', 'throttle', 'brake', 'clutch', 'steering_wheel_angle',
                    'relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data'):
            self.assertIn(key, result)
        self.assertAlmostEqual(result['speed'], 55.5 * 3.6, places=6)
        self.assertEqual(result['gear'], 4)
        self.assertAlmostEqual(result['throttle'], 0.62)
        self.assertAlmostEqual(result['brake'], 0.11)
        self.assertAlmostEqual(result['clutch'], 1.0)
        self.assertAlmostEqual(result['steering_wheel_angle'], -0.07)

    def test_front_metrics_defaults_before_first_lap(self):
        result = make_provider(base_sample()).get_telemetry_data()
        self.assertEqual(result['front_last_lap_time'], 0.0)
        self.assertEqual(result['lap_delta'], 0.0)
        self.assertEqual(result['target_pace'], 0.0)


class TestCarLeftRightEnum(unittest.TestCase):
    """irsdk.CarLeftRight: 0 off, 1 clear, 2 left, 3 right, 4 both, 5 two left, 6 two right."""

    CASES = {
        0: (False, False, 'CLEAR'),
        1: (False, False, 'CLEAR'),
        2: (True, False, 'CAR LEFT'),
        3: (False, True, 'CAR RIGHT'),
        4: (True, True, 'CARS BOTH SIDES'),
        5: (True, False, 'CAR LEFT'),
        6: (False, True, 'CAR RIGHT'),
    }

    def test_enum_values_decode_to_correct_sides(self):
        for value, (left, right, message) in self.CASES.items():
            with self.subTest(car_left_right=value):
                result = make_provider(base_sample(CarLeftRight=value)).get_telemetry_data()
                radar = result['radar_data']
                blindspot = result['blindspot_data']
                self.assertIs(radar['left_alert'], left, f'radar left for {value}')
                self.assertIs(radar['right_alert'], right, f'radar right for {value}')
                self.assertEqual(radar['both_alert'], left and right)
                self.assertIs(blindspot['left_alert'], left)
                self.assertIs(blindspot['right_alert'], right)
                self.assertEqual(blindspot['message'], message)
                self.assertEqual(blindspot['active'], left or right)


class TestCompletedLapHistory(unittest.TestCase):
    def poll(self, provider, lap, last_lap_time, session_num=0):
        provider.ir_sdk.update(Lap=lap, LapLastLapTime=last_lap_time, SessionNum=session_num)
        return provider.get_telemetry_data()['laptime_graph_data']['history']

    def test_records_lap_last_lap_time_on_completion(self):
        provider = make_provider(base_sample())
        self.assertEqual(self.poll(provider, 1, 0.0), [])
        history = self.poll(provider, 2, 91.234)
        self.assertEqual(history, [91.234])

    def test_rejects_startup_partial_lap(self):
        provider = make_provider(base_sample(Lap=3))
        provider.get_telemetry_data()
        history = self.poll(provider, 4, 88.8)
        self.assertEqual(history, [88.8])

    def test_rejects_duplicate_sampling_of_same_lap(self):
        provider = make_provider(base_sample(Lap=2))
        provider.get_telemetry_data()
        self.assertEqual(self.poll(provider, 2, 90.0), [])
        self.assertEqual(self.poll(provider, 2, 90.0), [])

    def test_rejects_invalid_completed_lap_times(self):
        provider = make_provider(base_sample(Lap=1))
        provider.get_telemetry_data()
        for invalid in (0.0, -5.0, float('nan'), float('inf')):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.poll(provider, 2, invalid), [])
        self.assertEqual(self.poll(provider, 3, 87.5), [87.5])

    def test_resets_on_session_change(self):
        provider = make_provider(base_sample(Lap=1))
        provider.get_telemetry_data()
        self.poll(provider, 2, 90.0)
        self.assertEqual(self.poll(provider, 1, 0.0, session_num=1), [])
        self.assertEqual(self.poll(provider, 2, 92.0, session_num=1), [92.0])

    def test_resets_on_reconnect(self):
        provider = make_provider(base_sample(Lap=1))
        provider.get_telemetry_data()
        self.poll(provider, 2, 90.0)
        provider.disconnect()
        self.assertTrue(provider.connect())
        self.assertEqual(provider.get_telemetry_data()['laptime_graph_data']['history'], [])
        self.assertEqual(self.poll(provider, 3, 95.0), [95.0])

    def test_resets_on_lap_rollback(self):
        provider = make_provider(base_sample(Lap=3))
        provider.get_telemetry_data()
        self.poll(provider, 4, 90.0)
        self.assertEqual(self.poll(provider, 1, 0.0), [])
        self.assertEqual(self.poll(provider, 2, 89.0), [89.0])

    def test_caps_history_at_ten_entries(self):
        provider = make_provider(base_sample(Lap=1))
        provider.get_telemetry_data()
        for lap in range(2, 14):
            history = self.poll(provider, lap, float(lap) * 10.0)
        self.assertEqual(len(history), 10)
        self.assertEqual(history[-1], 130.0)
        self.assertEqual(history[0], 40.0)


class TestRosterDriverInfo(unittest.TestCase):
    def test_reads_top_level_driver_info(self):
        result = make_provider(base_sample()).get_telemetry_data()
        car2 = relative_car(result, 2)
        car3 = relative_car(result, 3)
        self.assertEqual(car2['name'], 'Bob')
        self.assertEqual(car2['car_number'], '7')
        self.assertEqual(car3['name'], 'Cyd')
        self.assertEqual(car3['car_number'], '44')

    def test_legacy_nested_driver_info_still_supported(self):
        data = base_sample()
        del data['DriverInfo']
        data['SessionInfo'] = {
            'Sessions': [{'SessionNum': 0, 'SessionType': 'Race'}],
            'DriverInfo': {'Drivers': [{'CarIdx': 2, 'CarNumber': '9', 'UserName': 'Zoe'}]},
        }
        result = make_provider(data).get_telemetry_data()
        self.assertEqual(relative_car(result, 2)['name'], 'Zoe')

    def test_missing_driver_info_falls_back_to_generic_labels(self):
        data = base_sample()
        del data['DriverInfo']
        result = make_provider(data).get_telemetry_data()
        car2 = relative_car(result, 2)
        self.assertEqual(car2['name'], 'Car 2')
        self.assertEqual(car2['car_number'], '2')


class TestRelativeGaps(unittest.TestCase):
    def test_gap_is_explicitly_flagged_as_estimate(self):
        result = make_provider(base_sample()).get_telemetry_data()
        relative = result['relative_data']
        self.assertIs(relative['gap_is_estimate'], True)
        for car in relative['cars']:
            self.assertIs(car['gap_is_estimate'], True)

    def test_ahead_and_behind_sign_semantics(self):
        result = make_provider(base_sample()).get_telemetry_data()
        # Car 2 is 0.05 lap ahead of the player, car 3 is 0.40 lap behind.
        self.assertAlmostEqual(relative_car(result, 2)['gap'], 0.05 * 85.0, places=3)
        self.assertAlmostEqual(relative_car(result, 3)['gap'], -0.40 * 85.0, places=3)

    def test_wraps_lapped_cars_correctly(self):
        data = base_sample(
            CarIdxLapDistPct=[-1.0, 0.50, 0.55, 0.10],
            CarIdxLapCompleted=[0, 2, 4, 1],
        )
        result = make_provider(data).get_telemetry_data()
        car2 = relative_car(result, 2)
        # Raw delta 2.05 laps must wrap to 0.05 lap ahead, not 1.05.
        self.assertAlmostEqual(car2['gap'], 0.05 * 85.0, places=3)
        self.assertEqual(car2['lap_delta'], 2)

        data = base_sample(
            CarIdxLapDistPct=[-1.0, 0.90, 0.10, 0.10],
            CarIdxLapCompleted=[0, 3, 1, 1],
        )
        result = make_provider(data).get_telemetry_data()
        car2 = relative_car(result, 2)
        # Raw delta -2.80 laps must wrap to +0.20 lap (ahead on track).
        self.assertAlmostEqual(car2['gap'], 0.20 * 85.0, places=3)
        self.assertEqual(car2['lap_delta'], -2)

    def test_rejects_invalid_cars(self):
        data = base_sample(
            CarIdxPosition=[0, 3, 0, 2],
            CarIdxLapDistPct=[-1.0, 0.50, float('nan'), 0.10],
        )
        result = make_provider(data).get_telemetry_data()
        self.assertIsNone(relative_car(result, 2))

    def test_invalid_player_lap_pct_returns_empty_cars(self):
        data = base_sample(CarIdxLapDistPct=[-1.0, float('nan'), 0.55, 0.10])
        relative = make_provider(data).get_telemetry_data()['relative_data']
        self.assertEqual(relative['cars'], [])
        self.assertEqual(relative['player_car_idx'], 1)


class TestRadarTrackLength(unittest.TestCase):
    def test_derives_track_length_from_weekend_info_units(self):
        cases = {
            '5.891 km': 5891.0,
            '4.000 km': 4000.0,
            '850 m': 850.0,
            '2.5 mi': 4023.36,
        }
        for text, meters in cases.items():
            with self.subTest(track_length=text):
                result = make_provider(base_sample(WeekendInfo={'TrackLength': text})).get_telemetry_data()
                self.assertAlmostEqual(result['radar_data']['track_length_m'], meters, places=2)

    def test_no_invented_track_length_when_absent_or_unitless(self):
        for weekend in ({}, {'TrackLength': None}, {'TrackLength': '5500'}, {'TrackLength': 'unknown'}):
            with self.subTest(weekend=weekend):
                result = make_provider(base_sample(WeekendInfo=weekend)).get_telemetry_data()
                self.assertIsNone(result['radar_data']['track_length_m'])

    def test_nearby_list_and_clear_alerts_preserved(self):
        result = make_provider(base_sample(CarIdxLapDistPct=[-1.0, 0.50, 0.53, 0.10])).get_telemetry_data()
        radar = result['radar_data']
        self.assertFalse(radar['left_alert'])
        self.assertFalse(radar['right_alert'])
        self.assertFalse(radar['both_alert'])
        self.assertEqual(len(radar['nearby']), 1)
        self.assertEqual(radar['nearby'][0]['car_idx'], 2)
        self.assertAlmostEqual(radar['nearby'][0]['distance_pct'], 0.03, places=4)
        self.assertEqual(radar['nearby'][0]['relation'], 'ahead')


class TestNonfiniteHandling(unittest.TestCase):
    def test_nonfinite_inputs_do_not_leak_into_payload(self):
        data = base_sample(
            Speed=float('nan'),
            LapBestLapTime=float('inf'),
            CarIdxLapDistPct=[-1.0, 0.50, float('nan'), 0.10],
        )
        result = make_provider(data).get_telemetry_data()
        self.assertEqual(result['speed'], 0.0)
        # Relative gaps fall back to a sane base lap time instead of inf/nan.
        self.assertAlmostEqual(relative_car(result, 3)['gap'], -0.40 * 90.0, places=3)
        json.dumps(result, allow_nan=False)

    def test_payload_of_frozen_sample_is_strict_json(self):
        result = make_provider(base_sample()).get_telemetry_data()
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()

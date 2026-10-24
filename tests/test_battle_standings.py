"""Battle/Pace and Multiclass Standings tests (T4, S1-S5).

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

import test_fuel_session as fuel_tests  # noqa: E402
from test_telemetry_accuracy import FakeSDK, base_sample, make_provider  # noqa: E402

NEW_OVERLAYS = ('battle_pace', 'standings')

GT3 = {'CarClassID': 100, 'CarClassShortName': 'GT3'}
LMP2 = {'CarClassID': 200, 'CarClassShortName': 'LMP2'}

# idx: 0 pace car | 1 Ada (player, GT3) | 2 Bob (LMP2 leader) | 3 Cyd (GT3)
#      4 Dan (LMP2) | 5 Fay (GT3) | 6 Eve (GT3, one lap down)
DRIVERS = [
    {'CarIdx': 0, 'UserName': 'Pace Car', 'CarNumber': '0', 'CarIsPaceCar': 1, **LMP2},
    {'CarIdx': 1, 'UserName': 'Ada', 'CarNumber': '21', **GT3},
    {'CarIdx': 2, 'UserName': 'Bob', 'CarNumber': '7', **LMP2},
    {'CarIdx': 3, 'UserName': 'Cyd', 'CarNumber': '44', **GT3},
    {'CarIdx': 4, 'UserName': 'Dan', 'CarNumber': '9', **LMP2},
    {'CarIdx': 5, 'UserName': 'Fay', 'CarNumber': '3', **GT3},
    {'CarIdx': 6, 'UserName': 'Eve', 'CarNumber': '5', **GT3},
]


def session_info(session_type='Race', session_num=0):
    return {'Sessions': [{'SessionNum': session_num, 'SessionType': session_type,
                          'SessionLaps': 20, 'SessionTime': 'unlimited'}]}


def race_sample(**overrides):
    """A multiclass race in progress; every array has the same 7 slots."""
    sample = dict(
        PlayerCarIdx=1,
        SessionNum=0,
        SessionState=4,
        SessionInfo=session_info(),
        DriverInfo={'Drivers': DRIVERS},
        CarIdxPosition=[0, 4, 1, 5, 2, 3, 6],
        CarIdxClassPosition=[0, 2, 1, 3, 2, 1, 4],
        CarIdxLapCompleted=[-1, 4, 5, 4, 5, 4, 3],
        CarIdxLapDistPct=[-1.0, 0.60, 0.30, 0.40, 0.10, 0.95, 0.50],
        CarIdxF2Time=[0.0, 11.0, 0.0, 15.5, 3.2, 8.1, 40.0],
        CarIdxBestLapTime=[-1.0, 90.5, 80.0, 91.0, 80.4, 90.0, 92.0],
        CarIdxLastLapTime=[-1.0, 91.0, 80.5, 92.0, 81.0, 90.4, 93.0],
        CarIdxOnPitRoad=[False] * 7,
    )
    sample.update(overrides)
    return base_sample(**sample)


def standings_cars(result):
    return {c['car_idx']: c for g in result['standings_data']['classes'] for c in g['cars']}


def standings_group(result, class_id):
    return next(g for g in result['standings_data']['classes'] if g['class_id'] == class_id)


def step(provider, completed=None, last=None, **extra):
    """Advance chosen cars' completed-lap counters / last lap times by poll."""
    laps = list(provider.ir_sdk['CarIdxLapCompleted'])
    times = list(provider.ir_sdk['CarIdxLastLapTime'])
    for idx, value in (completed or {}).items():
        laps[idx] = value
    for idx, value in (last or {}).items():
        times[idx] = value
    provider.ir_sdk.update(CarIdxLapCompleted=laps, CarIdxLastLapTime=times, **extra)
    return provider.get_telemetry_data()


def player_pace(result):
    return result['battle_pace_data']['player']['pace']


class TestPayloadContract(unittest.TestCase):
    def test_connected_payload_adds_sections_and_keeps_legacy_keys(self):
        result = make_provider(race_sample()).get_telemetry_data()
        self.assertIsInstance(result['standings_data'], dict)
        self.assertIsInstance(result['battle_pace_data'], dict)
        for key in ('relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data', 'fuel_finish_data', 'session_strip_data'):
            self.assertIn(key, result)

    def test_disconnected_provider_still_returns_empty_dict(self):
        provider = make_provider(race_sample())
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_nothing_is_invented_without_telemetry(self):
        result = make_provider({'Lap': 1}).get_telemetry_data()
        self.assertEqual(result['standings_data']['classes'], [])
        self.assertIsNone(result['standings_data']['gap_basis'])
        battle = result['battle_pace_data']
        self.assertEqual(battle['context'], 'player_unavailable')
        self.assertIsNone(battle['player'])
        self.assertIsNone(battle['ahead'])
        self.assertIsNone(battle['behind'])


class TestStandingsRanking(unittest.TestCase):
    def setUp(self):
        self.result = make_provider(race_sample()).get_telemetry_data()

    def test_classes_are_grouped_and_ordered_by_their_best_overall_position(self):
        classes = self.result['standings_data']['classes']
        self.assertEqual([(g['class_id'], g['class_name'], g['known']) for g in classes],
                         [(200, 'LMP2', True), (100, 'GT3', True)])
        self.assertEqual([c['name'] for c in classes[0]['cars']], ['Bob', 'Dan'])
        self.assertEqual([c['name'] for c in classes[1]['cars']], ['Fay', 'Ada', 'Cyd', 'Eve'])

    def test_overall_and_class_rank_identity_and_player_flag(self):
        cars = standings_cars(self.result)
        ada = cars[1]
        self.assertEqual((ada['position'], ada['class_position']), (4, 2))
        self.assertEqual((ada['name'], ada['car_number']), ('Ada', '21'))
        self.assertIs(ada['is_player'], True)
        self.assertEqual(ada['laps_completed'], 4)
        self.assertEqual((ada['best_lap_s'], ada['last_lap_s']), (90.5, 91.0))
        self.assertIs(ada['on_pit_road'], False)
        self.assertEqual([i for i, c in cars.items() if c['is_player']], [1])
        self.assertEqual(self.result['standings_data']['player_car_idx'], 1)
        self.assertEqual(self.result['standings_data']['session_type'], 'Race')

    def test_pace_car_and_cars_without_a_rank_are_left_out(self):
        self.assertNotIn(0, standings_cars(self.result))
        data = race_sample(CarIdxPosition=[0, 4, 1, 5, 2, 3, 0])
        self.assertNotIn(6, standings_cars(make_provider(data).get_telemetry_data()))

    def test_spectators_are_left_out(self):
        drivers = [dict(d, IsSpectator=1) if d['CarIdx'] == 3 else d for d in DRIVERS]
        result = make_provider(race_sample(DriverInfo={'Drivers': drivers})).get_telemetry_data()
        self.assertNotIn(3, standings_cars(result))

    def test_car_index_zero_is_a_valid_car(self):
        # Ada and the pace car trade slots, so every array is swapped too.
        swapped = {key: [value[1], value[0]] + value[2:] for key, value in race_sample().items()
                   if key.startswith('CarIdx') and isinstance(value, list)}
        drivers = [dict(DRIVERS[1], CarIdx=0), dict(DRIVERS[0], CarIdx=1)] + DRIVERS[2:]
        data = race_sample(PlayerCarIdx=0, DriverInfo={'Drivers': drivers}, **swapped)
        result = make_provider(data).get_telemetry_data()
        car = standings_cars(result)[0]
        self.assertEqual((car['name'], car['is_player'], car['position']), ('Ada', True, 4))
        self.assertEqual(result['battle_pace_data']['player']['car_idx'], 0)
        self.assertEqual(result['battle_pace_data']['ahead']['name'], 'Fay')
        self.assertNotIn(1, standings_cars(result))

    def test_lap_times_use_none_for_sentinels_and_nonfinite_values(self):
        data = race_sample(
            CarIdxBestLapTime=[-1.0, -1.0, 0.0, float('nan'), float('inf'), 'x', 92.0],
            CarIdxLastLapTime=[-1.0, 0.0, -1.0, None, float('-inf'), 90.4, 93.0])
        cars = standings_cars(make_provider(data).get_telemetry_data())
        for idx in (1, 2, 3, 4):
            self.assertIsNone(cars[idx]['best_lap_s'], idx)
        for idx in (1, 2, 3, 4):
            self.assertIsNone(cars[idx]['last_lap_s'], idx)
        self.assertIsNone(cars[5]['best_lap_s'])
        self.assertEqual((cars[5]['last_lap_s'], cars[6]['best_lap_s']), (90.4, 92.0))

    def test_best_lap_delta_is_against_the_fastest_best_lap_of_the_same_class(self):
        cars = standings_cars(self.result)
        self.assertEqual(cars[2]['best_lap_delta_s'], 0.0)
        self.assertAlmostEqual(cars[4]['best_lap_delta_s'], 0.4, places=3)
        self.assertEqual(cars[5]['best_lap_delta_s'], 0.0)
        self.assertAlmostEqual(cars[1]['best_lap_delta_s'], 0.5, places=3)


class TestMismatchedMetadata(unittest.TestCase):
    def test_short_and_missing_arrays_do_not_crash_or_invent_values(self):
        data = race_sample(CarIdxClassPosition=[0, 2], CarIdxBestLapTime=[-1.0, 90.5],
                           CarIdxLastLapTime=None, CarIdxOnPitRoad=None, CarIdxF2Time=[0.0])
        result = make_provider(data).get_telemetry_data()
        cars = standings_cars(result)
        self.assertEqual(cars[1]['class_position'], 2)
        self.assertIsNone(cars[2]['class_position'])
        self.assertIsNone(cars[2]['best_lap_s'])
        self.assertIsNone(cars[1]['last_lap_s'])
        self.assertIsNone(cars[1]['on_pit_road'])
        self.assertIsNone(cars[1]['gap_to_leader_s'])
        self.assertIsInstance(result['battle_pace_data'], dict)

    def test_invalid_player_index_never_wraps_to_another_car(self):
        for bad in (-1, 99, None, 1.5):
            with self.subTest(player=bad):
                result = make_provider(race_sample(PlayerCarIdx=bad)).get_telemetry_data()
                self.assertFalse(any(c['is_player'] for c in standings_cars(result).values()))
                self.assertIsNone(result['standings_data']['player_car_idx'])
                self.assertEqual(result['battle_pace_data']['context'], 'player_unavailable')
                self.assertIsNone(result['battle_pace_data']['player'])

    def test_missing_driver_info_means_one_explicit_unknown_class_group(self):
        for drivers in (None, {'Drivers': []}, {'Drivers': 'x'}):
            with self.subTest(driver_info=drivers):
                result = make_provider(race_sample(DriverInfo=drivers)).get_telemetry_data()
                classes = result['standings_data']['classes']
                self.assertEqual(len(classes), 1)
                self.assertEqual((classes[0]['class_id'], classes[0]['class_name'], classes[0]['known']),
                                 (None, None, False))
                ada = standings_cars(result)[1]
                self.assertEqual(ada['position'], 4)
                self.assertIsNone(ada['name'])
                self.assertIsNone(ada['car_number'])

    def test_unknown_class_ranks_are_not_regrouped_or_trusted_across_classes(self):
        result = make_provider(race_sample(DriverInfo=None)).get_telemetry_data()
        cars = result['standings_data']['classes'][0]['cars']
        self.assertEqual([c['position'] for c in cars], [1, 2, 3, 4, 5, 6])
        # Class ranks collide across the unknown mix, so none is claimed.
        self.assertTrue(all(c['class_position'] is None for c in cars))
        self.assertTrue(all(c['interval_s'] is None for c in cars))
        self.assertTrue(all(c['best_lap_delta_s'] is None for c in cars))

    def test_one_car_without_class_metadata_is_listed_as_unknown_not_guessed(self):
        drivers = [{k: v for k, v in d.items() if not k.startswith('CarClass')} if d['CarIdx'] == 3 else d
                   for d in DRIVERS]
        result = make_provider(race_sample(DriverInfo={'Drivers': drivers})).get_telemetry_data()
        classes = result['standings_data']['classes']
        self.assertEqual([g['known'] for g in classes], [True, True, False])
        self.assertEqual([c['name'] for c in classes[2]['cars']], ['Cyd'])
        self.assertIsNone(classes[2]['cars'][0]['class_position'])

    def test_driver_info_inside_session_info_is_still_read(self):
        info = session_info()
        info['DriverInfo'] = {'Drivers': DRIVERS}
        result = make_provider(race_sample(DriverInfo=None, SessionInfo=info)).get_telemetry_data()
        self.assertEqual([g['class_name'] for g in result['standings_data']['classes']], ['LMP2', 'GT3'])


class TestRaceGapSemantics(unittest.TestCase):
    def setUp(self):
        self.result = make_provider(race_sample()).get_telemetry_data()
        self.cars = standings_cars(self.result)

    def test_gap_to_leader_is_the_race_f2time_when_on_the_leaders_lap(self):
        self.assertEqual(self.result['standings_data']['gap_basis'], 'race_f2time')
        self.assertEqual(self.cars[2]['gap_to_leader_s'], 0.0)
        self.assertEqual(self.cars[4]['gap_to_leader_s'], 3.2)
        self.assertEqual(self.cars[1]['gap_to_leader_s'], 11.0)
        for idx in (1, 2, 3, 4, 5):
            self.assertEqual(self.cars[idx]['laps_down'], 0)

    def test_lapped_car_reports_laps_down_and_no_time_gap(self):
        eve = self.cars[6]
        self.assertEqual(eve['laps_down'], 1)
        self.assertIsNone(eve['gap_to_leader_s'])
        # Eve (3.50) is 0.9 lap behind Cyd (4.40): a usable pair, not a lap apart.
        self.assertEqual(eve['interval_s'], 24.5)

    def test_lap_difference_uses_progress_not_a_modulo_of_it(self):
        # Two laps and a bit behind: still a lap count, never a negative time.
        data = race_sample(CarIdxLapCompleted=[-1, 2, 5, 4, 5, 4, 1])
        cars = standings_cars(make_provider(data).get_telemetry_data())
        self.assertEqual(cars[1]['laps_down'], 2)
        self.assertEqual(cars[6]['laps_down'], 3)
        for car in cars.values():
            for key in ('gap_to_leader_s', 'interval_s'):
                self.assertTrue(car[key] is None or car[key] >= 0, (car['car_idx'], key))

    def test_interval_is_the_f2time_difference_to_the_car_ahead_in_the_class(self):
        self.assertIsNone(self.cars[2]['interval_s'])
        self.assertEqual(self.cars[4]['interval_s'], 3.2)
        self.assertIsNone(self.cars[5]['interval_s'])
        self.assertEqual(self.cars[1]['interval_s'], 2.9)
        self.assertEqual(self.cars[3]['interval_s'], 4.5)

    def lapped_class_cars(self, **overrides):
        # The overall leader (LMP2 Bob) has lapped the GT3 cars 5, 1 and 3,
        # which still run on one lap together; Eve is two laps down.
        fields = dict(
            CarIdxLapCompleted=[-1, 5, 6, 5, 6, 5, 4],
            CarIdxLapDistPct=[-1.0, 0.60, 0.97, 0.40, 0.50, 0.95, 0.50],
            CarIdxF2Time=[0.0, 101.0, 0.0, 105.5, 3.2, 98.1, 190.0])
        fields.update(overrides)
        data = race_sample(**fields)
        result = make_provider(data).get_telemetry_data()
        return result, standings_cars(result)

    def test_same_lap_rivals_lapped_by_the_overall_leader_keep_their_pair_timing(self):
        result, cars = self.lapped_class_cars()
        for idx in (5, 1, 3):
            self.assertEqual(cars[idx]['laps_down'], 1)
            self.assertIsNone(cars[idx]['gap_to_leader_s'])  # not a time behind the leader
        self.assertIsNone(cars[5]['interval_s'])
        self.assertEqual(cars[1]['interval_s'], 2.9)
        self.assertEqual(cars[3]['interval_s'], 4.5)
        battle = result['battle_pace_data']
        self.assertEqual(battle['context'], 'ok')
        self.assertEqual((battle['ahead']['name'], battle['ahead']['gap_s']), ('Fay', 2.9))
        self.assertEqual((battle['behind']['name'], battle['behind']['gap_s']), ('Cyd', 4.5))

    def assertPairTimes(self, result, cars, label):
        self.assertEqual(cars[1]['interval_s'], 2.9, label)
        self.assertEqual(cars[3]['interval_s'], 4.5, label)
        self.assertIsNone(cars[5]['interval_s'], label)
        battle = result['battle_pace_data']
        self.assertEqual((battle['ahead']['name'], battle['ahead']['gap_s']), ('Fay', 2.9), label)
        self.assertEqual((battle['behind']['name'], battle['behind']['gap_s']), ('Cyd', 4.5), label)

    def test_pair_timing_does_not_depend_on_where_the_overall_leader_is_on_track(self):
        # The pair (Fay 5.95 / Ada 5.60 / Cyd 5.40) is always within a lap of
        # each other; only the leader's lap fraction, hence the floor of each
        # car's deficit to it, changes.
        for leader_pct in (0.97, 0.80, 0.50):
            with self.subTest(leader_pct=leader_pct):
                pcts = [-1.0, 0.60, leader_pct, 0.40, 0.50, 0.95, 0.50]
                self.assertPairTimes(*self.lapped_class_cars(CarIdxLapDistPct=pcts),
                                     f'leader at {leader_pct}')

    def test_verifier_b1_values_with_different_lap_counts_and_leader_position(self):
        # Leader 6.70; Fay 4.95, player 4.60, Cyd 4.40: floor deficits 1, 2, 2.
        result, cars = self.lapped_class_cars(
            CarIdxLapCompleted=[-1, 4, 6, 4, 5, 4, 3],
            CarIdxLapDistPct=[-1.0, 0.60, 0.70, 0.40, 0.10, 0.95, 0.50],
            CarIdxF2Time=[0.0, 101.0, 0.0, 105.5, 3.2, 98.1, 190.0])
        self.assertEqual([cars[i]['laps_down'] for i in (5, 1, 3)], [1, 2, 2])
        self.assertPairTimes(result, cars, 'verifier B1')

    def test_pair_less_than_a_lap_apart_is_usable_even_when_laps_down_differ(self):
        # Eve is 0.9 lap behind Cyd: a real pair, timed by their F2Time.
        _, cars = self.lapped_class_cars()
        self.assertEqual(cars[6]['laps_down'], 2)
        self.assertEqual(cars[6]['interval_s'], 84.5)

    def test_pair_a_full_lap_or_more_apart_has_no_time(self):
        for eve_laps in (4, 3):   # 4.50 vs Cyd 5.40 is 0.9 lap; 3.50 is 1.9 laps
            with self.subTest(eve_completed=eve_laps):
                result, cars = self.lapped_class_cars(
                    PlayerCarIdx=6, CarIdxLapCompleted=[-1, 5, 6, 5, 6, 5, eve_laps])
                ahead = result['battle_pace_data']['ahead']
                self.assertEqual(ahead['name'], 'Cyd')
                self.assertEqual(ahead['gap_s'], 84.5 if eve_laps == 4 else None)
                self.assertEqual(cars[6]['interval_s'], 84.5 if eve_laps == 4 else None)
        # Cyd 4.40 is 1.2 laps behind Ada 5.60: no pair time, but Ada/Fay keep theirs.
        result, cars = self.lapped_class_cars(
            CarIdxLapCompleted=[-1, 5, 6, 4, 6, 5, 4])
        self.assertIsNone(cars[3]['interval_s'])
        self.assertEqual(cars[1]['interval_s'], 2.9)
        self.assertIsNone(result['battle_pace_data']['behind']['gap_s'])

    def test_pair_timing_needs_the_class_order_to_match_progress(self):
        # Fay is classified ahead of Ada but has not covered more distance:
        # a negative difference is never turned into a time.
        result, cars = self.lapped_class_cars(
            CarIdxLapDistPct=[-1.0, 0.60, 0.97, 0.40, 0.50, 0.30, 0.50])
        self.assertIsNone(cars[1]['interval_s'])
        self.assertIsNone(result['battle_pace_data']['ahead']['gap_s'])
        self.assertEqual(result['battle_pace_data']['behind']['gap_s'], 4.5)

    def test_pair_timing_is_not_invented_across_laps_or_from_bad_times(self):
        for bad in (None, float('nan'), float('inf'), 0.0, -4.0, 'x'):
            with self.subTest(f2=bad):
                result, cars = self.lapped_class_cars(
                    CarIdxF2Time=[0.0, bad, 0.0, 105.5, 3.2, 98.1, 190.0])
                self.assertIsNone(cars[1]['interval_s'])
                self.assertIsNone(cars[3]['interval_s'])
                self.assertIsNone(result['battle_pace_data']['ahead']['gap_s'])
                self.assertIsNone(result['battle_pace_data']['behind']['gap_s'])
        # Progress unknown for a pair member: no same-lap claim.
        result, cars = self.lapped_class_cars(
            CarIdxLapDistPct=[-1.0, -1.0, 0.97, 0.40, 0.50, 0.95, 0.50])
        self.assertIsNone(cars[1]['interval_s'])
        self.assertIsNone(cars[3]['interval_s'])

    def test_lapped_pair_timing_still_needs_confirmed_race_metadata(self):
        for overrides in (dict(SessionInfo=session_info('Practice')), dict(SessionInfo=None),
                          dict(SessionState=2)):
            with self.subTest(overrides=sorted(overrides)):
                result, cars = self.lapped_class_cars(**overrides)
                self.assertIsNone(cars[1]['interval_s'])
                self.assertIsNone(result['battle_pace_data']['ahead']['gap_s'])

    def test_invalid_f2time_or_progress_leaves_the_timing_null(self):
        for bad in (None, float('nan'), float('inf'), -1.0, 0.0, 'x'):
            with self.subTest(f2=bad):
                data = race_sample(CarIdxF2Time=[0.0, bad, 0.0, 15.5, 3.2, 8.1, 40.0])
                cars = standings_cars(make_provider(data).get_telemetry_data())
                self.assertIsNone(cars[1]['gap_to_leader_s'])
                self.assertIsNone(cars[1]['interval_s'])
                self.assertIsNone(cars[3]['interval_s'])  # ahead car timing unknown
                self.assertEqual(cars[5]['gap_to_leader_s'], 8.1)
        data = race_sample(CarIdxLapDistPct=[-1.0, -1.0, 0.30, 0.20, 0.10, 0.95, 0.50])
        ada = standings_cars(make_provider(data).get_telemetry_data())[1]
        self.assertIsNone(ada['gap_to_leader_s'])
        self.assertIsNone(ada['laps_down'])

    def test_no_leader_means_no_time_gaps(self):
        data = race_sample(CarIdxPosition=[0, 4, 0, 5, 2, 3, 6])
        cars = standings_cars(make_provider(data).get_telemetry_data())
        self.assertTrue(all(c['gap_to_leader_s'] is None and c['laps_down'] is None
                            for c in cars.values()))


class TestTimingMeaningBySession(unittest.TestCase):
    def assertNoRaceTiming(self, result):
        self.assertIsNone(result['standings_data']['gap_basis'])
        for car in standings_cars(result).values():
            self.assertIsNone(car['gap_to_leader_s'], car['car_idx'])
            self.assertIsNone(car['laps_down'], car['car_idx'])
            self.assertIsNone(car['interval_s'], car['car_idx'])

    def test_practice_and_qualifying_never_read_f2time_as_a_race_gap(self):
        for session_type in ('Practice', 'Open Qualify', 'Lone Qualify', 'Warmup'):
            with self.subTest(session=session_type):
                data = race_sample(SessionInfo=session_info(session_type))
                result = make_provider(data).get_telemetry_data()
                self.assertNoRaceTiming(result)
                self.assertIsNone(result['battle_pace_data']['gap_basis'])
                for role in ('ahead', 'behind'):
                    self.assertIsNone(result['battle_pace_data'][role]['gap_s'])

    def test_unconfirmed_race_metadata_or_state_leaves_gaps_null(self):
        cases = {
            'no session info': dict(SessionInfo=None),
            'other session number': dict(SessionNum=3),
            'unknown type': dict(SessionInfo={'Sessions': [{'SessionNum': 0}]}),
            'state missing': dict(SessionState=None),
            'gridding': dict(SessionState=2),
        }
        for label, overrides in cases.items():
            with self.subTest(case=label):
                self.assertNoRaceTiming(make_provider(race_sample(**overrides)).get_telemetry_data())

    def test_checkered_race_state_keeps_race_timing(self):
        result = make_provider(race_sample(SessionState=5)).get_telemetry_data()
        self.assertEqual(standings_cars(result)[1]['gap_to_leader_s'], 11.0)

    def test_practice_orders_by_best_lap_when_there_is_no_rank(self):
        data = race_sample(SessionInfo=session_info('Practice'), CarIdxPosition=[0] * 7,
                           CarIdxClassPosition=[0] * 7)
        result = make_provider(data).get_telemetry_data()
        self.assertEqual([c['name'] for c in standings_group(result, 200)['cars']], ['Bob', 'Dan'])
        self.assertEqual([c['name'] for c in standings_group(result, 100)['cars']],
                         ['Fay', 'Ada', 'Cyd', 'Eve'])
        for car in standings_cars(result).values():
            self.assertIsNone(car['position'])
            self.assertIsNone(car['class_position'])
        self.assertAlmostEqual(standings_cars(result)[1]['best_lap_delta_s'], 0.5, places=3)

    def test_practice_without_rank_or_best_lap_lists_no_car(self):
        data = race_sample(SessionInfo=session_info('Practice'), CarIdxPosition=[0] * 7,
                           CarIdxBestLapTime=[-1.0] * 7)
        self.assertEqual(standings_cars(make_provider(data).get_telemetry_data()), {})


class TestBattleContext(unittest.TestCase):
    def setUp(self):
        self.result = make_provider(race_sample()).get_telemetry_data()
        self.battle = self.result['battle_pace_data']

    def test_same_class_neighbours_ignore_faster_class_cars(self):
        self.assertEqual(self.battle['context'], 'ok')
        self.assertEqual((self.battle['class_id'], self.battle['class_name']), (100, 'GT3'))
        self.assertEqual(self.battle['player']['car_idx'], 1)
        self.assertEqual(self.battle['ahead']['name'], 'Fay')
        self.assertEqual(self.battle['behind']['name'], 'Cyd')
        self.assertEqual((self.battle['ahead']['class_position'], self.battle['behind']['class_position']),
                         (1, 3))

    def test_gap_is_a_positive_race_time_with_provenance(self):
        self.assertEqual(self.battle['gap_basis'], 'race_f2time')
        self.assertEqual(self.battle['ahead']['gap_s'], 2.9)
        self.assertEqual(self.battle['behind']['gap_s'], 4.5)
        self.assertNotIn('gap_s', self.battle['player'])

    def test_lap_deltas_are_opponent_minus_player_with_a_named_source(self):
        self.assertEqual(self.battle['lap_time_source'], 'CarIdxLastLapTime/CarIdxBestLapTime')
        ahead, behind = self.battle['ahead'], self.battle['behind']
        self.assertAlmostEqual(ahead['last_lap_delta_s'], -0.6, places=3)
        self.assertAlmostEqual(behind['last_lap_delta_s'], 1.0, places=3)
        self.assertAlmostEqual(ahead['best_lap_delta_s'], -0.5, places=3)
        self.assertAlmostEqual(behind['best_lap_delta_s'], 0.5, places=3)
        self.assertEqual((ahead['last_lap_s'], self.battle['player']['last_lap_s']), (90.4, 91.0))

    def test_class_leader_has_no_car_ahead_and_class_last_has_none_behind(self):
        leader = make_provider(race_sample(PlayerCarIdx=5)).get_telemetry_data()['battle_pace_data']
        self.assertEqual(leader['context'], 'ok')
        self.assertIsNone(leader['ahead'])
        self.assertEqual(leader['behind']['name'], 'Ada')
        last = make_provider(race_sample(PlayerCarIdx=6)).get_telemetry_data()['battle_pace_data']
        self.assertIsNone(last['behind'])
        self.assertEqual(last['ahead']['name'], 'Cyd')
        self.assertEqual(last['ahead']['gap_s'], 24.5)  # 0.9 lap apart: still a pair
        self.assertEqual(last['player']['laps_down'], 1)

    def test_unknown_class_gives_no_same_class_comparison(self):
        for overrides in (dict(DriverInfo=None),
                          dict(DriverInfo={'Drivers': [d for d in DRIVERS if d['CarIdx'] != 1]})):
            battle = make_provider(race_sample(**overrides)).get_telemetry_data()['battle_pace_data']
            self.assertEqual(battle['context'], 'class_unknown')
            self.assertIsNone(battle['ahead'])
            self.assertIsNone(battle['behind'])
            self.assertIsNone(battle['class_id'])
            self.assertEqual(battle['player']['position'], 4)

    def test_missing_class_position_gives_no_neighbours(self):
        battle = make_provider(race_sample(CarIdxClassPosition=[0, 0, 1, 3, 2, 1, 4])
                               ).get_telemetry_data()['battle_pace_data']
        self.assertEqual(battle['context'], 'class_position_unavailable')
        self.assertIsNone(battle['ahead'])
        self.assertIsNone(battle['behind'])

    def test_ambiguous_class_positions_are_not_guessed(self):
        battle = make_provider(race_sample(CarIdxClassPosition=[0, 2, 1, 3, 2, 1, 1])
                               ).get_telemetry_data()['battle_pace_data']
        self.assertIsNone(battle['ahead'])
        self.assertEqual(battle['behind']['name'], 'Cyd')

    def test_missing_timing_stays_null_rather_than_zero(self):
        data = race_sample(CarIdxBestLapTime=[-1.0, 90.5, 80.0, 91.0, 80.4, -1.0, 92.0],
                           CarIdxLastLapTime=[-1.0, 0.0, 80.5, float('nan'), 81.0, 90.4, 93.0],
                           CarIdxF2Time=[0.0, 11.0, 0.0, 15.5, 3.2, None, 40.0])
        battle = make_provider(data).get_telemetry_data()['battle_pace_data']
        for role in ('ahead', 'behind'):
            self.assertIsNone(battle[role]['last_lap_delta_s'], role)
            self.assertIsNone(battle[role]['pace_delta_s'], role)
        self.assertIsNone(battle['ahead']['best_lap_delta_s'])
        self.assertIsNone(battle['ahead']['gap_s'])
        self.assertAlmostEqual(battle['behind']['best_lap_delta_s'], 0.5, places=3)
        self.assertIsNone(battle['behind']['last_lap_s'])

    def test_pit_road_flags_are_reported(self):
        data = race_sample(CarIdxOnPitRoad=[False, False, False, True, False, False, False])
        battle = make_provider(data).get_telemetry_data()['battle_pace_data']
        self.assertIs(battle['behind']['on_pit_road'], True)
        self.assertIs(battle['ahead']['on_pit_road'], False)


class TestObservedPace(unittest.TestCase):
    def setUp(self):
        self.provider = make_provider(race_sample())
        self.baseline = self.provider.get_telemetry_data()

    def three_laps(self):
        step(self.provider, {1: 5}, {1: 91.0})
        step(self.provider, {1: 6}, {1: 90.8})
        return step(self.provider, {1: 7}, {1: 90.6})

    def test_startup_baseline_is_not_a_sample(self):
        self.assertEqual(player_pace(self.baseline),
                         {'laps': 0, 'avg_lap_s': None, 'trend_s_per_lap': None, 'trend': None})
        self.assertEqual(player_pace(step(self.provider, last={1: 91.5}))['laps'], 0)

    def test_consecutive_completed_laps_build_pace_then_trend(self):
        first = step(self.provider, {1: 5}, {1: 91.0})
        self.assertEqual(player_pace(first), {'laps': 1, 'avg_lap_s': None,
                                              'trend_s_per_lap': None, 'trend': None})
        second = step(self.provider, {1: 6}, {1: 90.8})
        self.assertEqual(player_pace(second), {'laps': 2, 'avg_lap_s': 90.9,
                                               'trend_s_per_lap': None, 'trend': None})
        third = step(self.provider, {1: 7}, {1: 90.6})
        self.assertEqual(player_pace(third), {'laps': 3, 'avg_lap_s': 90.8,
                                              'trend_s_per_lap': -0.2, 'trend': 'improving'})

    def test_repeated_polls_of_a_lap_add_no_sample(self):
        step(self.provider, {1: 5}, {1: 91.0})
        for _ in range(5):
            result = step(self.provider, {1: 5}, {1: 91.0})
        self.assertEqual(player_pace(result)['laps'], 1)

    def test_trend_labels_follow_the_sign_and_a_steady_band(self):
        for times, label, slope in (((90.0, 90.3, 90.6), 'worsening', 0.3),
                                    ((90.0, 90.01, 90.02), 'steady', 0.01)):
            provider = make_provider(race_sample())
            provider.get_telemetry_data()
            for lap, lap_time in zip((5, 6, 7), times):
                result = step(provider, {1: lap}, {1: lap_time})
            self.assertEqual(player_pace(result)['trend'], label)
            self.assertAlmostEqual(player_pace(result)['trend_s_per_lap'], slope, places=3)

    def test_window_keeps_only_the_latest_five_laps(self):
        for lap in range(5, 13):
            result = step(self.provider, {1: lap}, {1: 90.0 + lap})
        pace = player_pace(result)
        self.assertEqual(pace['laps'], 5)
        self.assertEqual(pace['avg_lap_s'], 100.0)  # laps 8..12 -> 98..102
        self.assertEqual(pace['trend_s_per_lap'], 1.0)

    def test_skipped_polls_never_fabricate_laps(self):
        step(self.provider, {1: 5}, {1: 91.0})
        result = step(self.provider, {1: 7}, {1: 90.5})  # lap 6 was never observed
        self.assertEqual(player_pace(result)['laps'], 0)
        result = step(self.provider, {1: 8}, {1: 90.4})
        self.assertEqual(player_pace(result)['laps'], 1)

    def test_invalid_lap_time_breaks_the_consecutive_run(self):
        for bad in (0.0, -1.0, float('nan'), None):
            with self.subTest(last=bad):
                provider = make_provider(race_sample())
                provider.get_telemetry_data()
                step(provider, {1: 5}, {1: 91.0})
                result = step(provider, {1: 6}, {1: bad})
                self.assertEqual(player_pace(result)['laps'], 0)
                result = step(provider, {1: 7}, {1: 90.5})
                self.assertEqual(player_pace(result)['laps'], 1)

    def test_pit_laps_are_not_samples_and_split_the_run(self):
        step(self.provider, {1: 5}, {1: 91.0})
        pit = [False] * 7
        pit[1] = True
        step(self.provider, CarIdxOnPitRoad=pit)           # in the pits mid-lap
        step(self.provider, CarIdxOnPitRoad=[False] * 7)
        result = step(self.provider, {1: 6}, {1: 120.0})   # in/out lap, discarded
        self.assertEqual(player_pace(result)['laps'], 0)
        result = step(self.provider, {1: 7}, {1: 90.7})
        self.assertEqual(player_pace(result)['laps'], 1)

    def test_session_change_reconnect_and_rollback_reset_the_trend(self):
        self.assertEqual(player_pace(self.three_laps())['laps'], 3)
        changed = step(self.provider, SessionNum=1, SessionInfo=session_info('Race', 1))
        self.assertEqual(player_pace(changed)['laps'], 0)
        self.assertEqual(player_pace(step(self.provider, {1: 8}, {1: 90.5}))['laps'], 1)
        self.provider.is_connected = False
        self.assertTrue(self.provider.connect())
        self.assertEqual(player_pace(self.provider.get_telemetry_data())['laps'], 0)
        self.assertEqual(player_pace(step(self.provider, {1: 9}, {1: 90.4}))['laps'], 1)
        self.assertEqual(player_pace(step(self.provider, {1: 3}))['laps'], 0)   # rollback
        self.assertEqual(player_pace(step(self.provider, {1: 4}, {1: 90.3}))['laps'], 1)

    def test_opponent_pace_is_observed_the_same_way_and_compared(self):
        for lap, mine, theirs in ((5, 91.0, 90.4), (6, 90.8, 90.3), (7, 90.6, 90.2)):
            result = step(self.provider, {1: lap, 5: lap}, {1: mine, 5: theirs})
        battle = result['battle_pace_data']
        self.assertEqual(battle['ahead']['pace'], {'laps': 3, 'avg_lap_s': 90.3,
                                                   'trend_s_per_lap': -0.1, 'trend': 'improving'})
        self.assertAlmostEqual(battle['ahead']['pace_delta_s'], -0.5, places=3)
        # Cyd was never observed completing a lap: no pace, no comparison.
        self.assertEqual(battle['behind']['pace']['laps'], 0)
        self.assertIsNone(battle['behind']['pace_delta_s'])

    def test_pace_delta_needs_two_observed_laps_on_both_sides(self):
        step(self.provider, {1: 5, 5: 5}, {1: 91.0, 5: 90.4})
        result = step(self.provider, {1: 6}, {1: 90.8})
        self.assertIsNone(result['battle_pace_data']['ahead']['pace_delta_s'])


class TestLegacyBehaviourPreserved(unittest.TestCase):
    def test_lap_history_and_fuel_sampling_are_unaffected_by_field_tracking(self):
        provider = make_provider(fuel_tests.fuel_sample())
        fuel_tests.poll(provider, 1, 50.0)
        for lap, fuel, last in ((2, 48.5, 90.0), (3, 47.0, 91.0), (4, 45.5, 90.5)):
            fuel_tests.poll(provider, lap, fuel, last, CarIdxLapCompleted=[-1, lap, 2, 1])
        result = provider.get_telemetry_data()
        self.assertEqual(result['laptime_graph_data']['history'], [90.0, 91.0, 90.5])
        self.assertEqual(result['fuel_finish_data']['burn_sample_count'], 2)
        self.assertAlmostEqual(result['fuel_finish_data']['avg_burn_l_per_lap'], 1.5)

    def test_reconnect_still_clears_the_player_lap_history(self):
        provider = make_provider(race_sample())
        provider.get_telemetry_data()
        for lap, last in ((3, 90.0), (4, 91.0)):
            provider.ir_sdk.update(Lap=lap, LapLastLapTime=last)
            result = provider.get_telemetry_data()
        self.assertEqual(result['laptime_graph_data']['history'], [90.0, 91.0])
        provider.is_connected = False
        provider.connect()
        self.assertEqual(provider.get_telemetry_data()['laptime_graph_data']['history'], [])

    def test_relative_data_keeps_its_legacy_placeholder_identity(self):
        # The legacy relative overlay labels unknown drivers "Car N"; the new
        # standings must never copy that invented identity.
        data = race_sample(DriverInfo={'Drivers': [d for d in DRIVERS if d['CarIdx'] != 5]})
        result = make_provider(data).get_telemetry_data()
        relative_fay = next(c for c in result['relative_data']['cars'] if c['car_idx'] == 5)
        self.assertEqual((relative_fay['name'], relative_fay['car_number']), ('Car 5', '5'))
        self.assertIsNone(standings_cars(result)[5]['name'])
        self.assertIsNone(standings_cars(result)[5]['car_number'])
        self.assertEqual(relative_fay['position'], 3)


class SocketTestBase(fuel_tests.SocketTestBase):
    def setUp(self):
        super().setUp()
        self.web.data_provider.ir_sdk = FakeSDK(race_sample())


class TestSocketEvents(SocketTestBase):
    def test_dedicated_events_carry_the_provider_payloads(self):
        battle = self.client('/battle_pace')
        standings = self.client('/standings')
        self.web._process_telemetry_data()
        battle_payloads = self.events(battle, '/battle_pace', 'battle_pace_update')
        standings_payloads = self.events(standings, '/standings', 'standings_update')
        self.assertEqual(len(battle_payloads), 1)
        self.assertEqual(len(standings_payloads), 1)
        self.assertEqual(battle_payloads[0]['ahead']['name'], 'Fay')
        self.assertEqual(battle_payloads[0]['ahead']['gap_s'], 2.9)
        self.assertEqual([g['class_name'] for g in standings_payloads[0]['classes']], ['LMP2', 'GT3'])
        self.assertEqual(standings_payloads[0]['classes'][1]['cars'][1]['gap_to_leader_s'], 11.0)

    def test_missing_sections_emit_a_null_payload(self):
        battle = self.client('/battle_pace')
        standings = self.client('/standings')
        with mock.patch.object(self.web.data_provider, 'get_telemetry_data',
                               return_value={'speed': 1.0, 'gear': 2}):
            self.web._process_telemetry_data()
        self.assertEqual(self.events(battle, '/battle_pace', 'battle_pace_update'), [None])
        self.assertEqual(self.events(standings, '/standings', 'standings_update'), [None])

    def test_one_failing_emit_does_not_block_the_other_overlay(self):
        standings = self.client('/standings')
        real_emit = self.web.socketio.emit

        def flaky(event, *args, **kwargs):
            if kwargs.get('namespace') == '/battle_pace':
                raise RuntimeError('boom')
            return real_emit(event, *args, **kwargs)

        with mock.patch.object(self.web.socketio, 'emit', side_effect=flaky):
            self.web._process_telemetry_data()
        self.assertEqual(len(self.events(standings, '/standings', 'standings_update')), 1)

    def test_legacy_events_are_unchanged_and_do_not_gain_the_new_sections(self):
        telemetry = self.client('/input_telemetry', disconnect=False)
        fuel = self.client('/fuel_finish')
        strip = self.client('/session_strip')
        graph = self.client('/laptime_graph', disconnect=False)
        self.web._process_telemetry_data()
        payload = self.events(telemetry, '/input_telemetry', 'telemetry_update')[0]
        self.assertNotIn('battle_pace_data', payload)
        self.assertNotIn('standings_data', payload)
        self.assertAlmostEqual(payload['speed'], 55.5 * 3.6, places=6)
        self.assertEqual(payload['gear'], 4)
        self.assertEqual(len(self.events(fuel, '/fuel_finish', 'fuel_finish_update')), 1)
        self.assertEqual(len(self.events(strip, '/session_strip', 'session_strip_update')), 1)
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

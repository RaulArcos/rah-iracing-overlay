"""Broadcast Driver Card tests (T6, S1-S5).

Exercises the public DataProvider.get_telemetry_data entry point with an
injected fake SDK, the dedicated Socket.IO namespace/event through the
flask-socketio test client (the telemetry thread is stubbed, no simulator is
started) and the HTTP discovery/asset surface of the new overlay.
"""

import json
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

PAYLOAD_KEYS = {
    'available', 'reason', 'camera_car_idx', 'identity_available',
    'name', 'car_number', 'class_id', 'class_name',
    'position', 'class_position', 'laps_completed', 'last_lap_s', 'best_lap_s', 'on_pit_road',
    'session_type', 'source',
}
STAT_KEYS = ('position', 'class_position', 'laps_completed', 'last_lap_s', 'best_lap_s', 'on_pit_road')
IDENTITY_KEYS = ('name', 'car_number', 'class_id', 'class_name')
# Player-only SDK values set to distinctive numbers: none may reach the card.
PLAYER_ONLY = dict(Speed=88.8, Gear=6, Throttle=0.4321, Brake=0.8765, Clutch=0.2468,
                   SteeringWheelAngle=1.2345, RPM=7777.7, FuelLevel=42.42, FuelLevelPct=0.6543)
LEAK_TEXT = ('319.68', '0.4321', '0.8765', '0.2468', '1.2345', '7777.7', '42.42', '0.6543')


def driver(idx, name, number, class_id, class_name, **extra):
    return dict(CarIdx=idx, UserName=name, CarNumber=number, CarClassID=class_id,
                CarClassShortName=class_name, **extra)


def broadcast_sample(**overrides):
    """Four cars, player is car 1, the camera follows car 2."""
    sample = dict(
        PlayerCarIdx=1, CamCarIdx=2, **PLAYER_ONLY,
        CarIdxPosition=[4, 3, 1, 2], CarIdxClassPosition=[2, 1, 1, 2],
        CarIdxLapCompleted=[5, 6, 7, 7],
        CarIdxLastLapTime=[91.234, 90.5, 88.25, 88.4],
        CarIdxBestLapTime=[90.9, 90.1, 87.5, 87.9],
        CarIdxOnPitRoad=[False, False, False, True],
        DriverInfo={'Drivers': [
            driver(0, 'Zed', '99', 11, 'GT3'), driver(1, 'Ada', '21', 11, 'GT3'),
            driver(2, 'Bob', '7', 12, 'LMP2'), driver(3, 'Cyd', '44', 12, 'LMP2')]},
    )
    sample.update(overrides)
    return base_sample(**sample)


def card(**overrides):
    return make_provider(broadcast_sample(**overrides)).get_telemetry_data()['broadcast_driver_data']


def assert_unavailable(test, payload, reason='camera_unavailable'):
    test.assertEqual(set(payload), PAYLOAD_KEYS)
    test.assertIs(payload['available'], False)
    test.assertEqual(payload['reason'], reason)
    test.assertIsNone(payload['camera_car_idx'])
    test.assertIs(payload['identity_available'], False)
    for key in IDENTITY_KEYS + STAT_KEYS + ('session_type',):
        test.assertIsNone(payload[key], key)


class TestPayloadContract(unittest.TestCase):
    def test_connected_payload_adds_the_section_and_keeps_legacy_keys(self):
        result = make_provider(broadcast_sample()).get_telemetry_data()
        self.assertEqual(set(result['broadcast_driver_data']), PAYLOAD_KEYS)
        for key in ('speed', 'gear', 'throttle', 'brake', 'clutch', 'steering_wheel_angle',
                    'relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data', 'fuel_finish_data', 'session_strip_data',
                    'standings_data', 'battle_pace_data', 'pit_assistant_data', 'weather_data'):
            self.assertIn(key, result)

    def test_disconnected_provider_still_returns_empty_dict(self):
        provider = make_provider(broadcast_sample())
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_the_new_section_does_not_change_any_other_payload_key(self):
        with_camera = make_provider(broadcast_sample()).get_telemetry_data()
        without = make_provider({k: v for k, v in broadcast_sample().items()
                                 if k != 'CamCarIdx'}).get_telemetry_data()
        del with_camera['broadcast_driver_data'], without['broadcast_driver_data']
        self.assertEqual(with_camera, without)

    def test_a_failing_builder_yields_none_and_cannot_break_the_rest(self):
        provider = make_provider(broadcast_sample())
        with mock.patch.object(type(provider), '_get_standings_roster', side_effect=RuntimeError('boom')):
            result = provider.get_telemetry_data()
        self.assertIsNone(result['broadcast_driver_data'])
        for key in ('speed', 'fuel_finish_data', 'pit_assistant_data', 'weather_data'):
            self.assertIn(key, result)

    def test_payload_is_json_safe_with_non_finite_inputs(self):
        payload = card(CarIdxLastLapTime=[0, 0, math.inf, 0], CarIdxBestLapTime=[0, 0, math.nan, 0])
        json.dumps(payload, allow_nan=False)


class TestCameraTarget(unittest.TestCase):
    def test_opponent_camera_reports_that_cars_identity_and_stats(self):
        self.assertEqual(card(CamCarIdx=2), {
            'available': True, 'reason': None, 'camera_car_idx': 2, 'identity_available': True,
            'name': 'Bob', 'car_number': '7', 'class_id': 12, 'class_name': 'LMP2',
            'position': 1, 'class_position': 1, 'laps_completed': 7,
            'last_lap_s': 88.25, 'best_lap_s': 87.5, 'on_pit_road': False,
            'session_type': 'Race', 'source': 'CamCarIdx',
        })

    def test_camera_on_the_player_uses_the_same_uniform_schema(self):
        payload = card(CamCarIdx=1)
        self.assertEqual(set(payload), PAYLOAD_KEYS)
        self.assertEqual((payload['camera_car_idx'], payload['name'], payload['position'],
                          payload['last_lap_s']), (1, 'Ada', 3, 90.5))

    def test_car_index_zero_is_a_valid_camera_target(self):
        payload = card(CamCarIdx=0)
        self.assertIs(payload['available'], True)
        self.assertEqual((payload['camera_car_idx'], payload['name'], payload['car_number'],
                          payload['position'], payload['laps_completed']), (0, 'Zed', '99', 4, 5))

    def test_integral_float_camera_index_is_accepted(self):
        self.assertEqual(card(CamCarIdx=3.0)['name'], 'Cyd')
        self.assertIs(card(CamCarIdx=3.0)['on_pit_road'], True)

    def test_invalid_camera_values_are_unavailable_and_never_fall_back_to_the_player(self):
        # The player is car 1 with a full roster entry: any fallback would show Ada.
        for bad in (None, -1, True, False, 1.5, math.nan, math.inf, '2', 'x', [2], {}, 4, 99, 255):
            with self.subTest(camera=bad):
                assert_unavailable(self, card(CamCarIdx=bad))

    def test_missing_camera_variable_is_unavailable(self):
        sample = broadcast_sample()
        del sample['CamCarIdx']
        assert_unavailable(self, make_provider(sample).get_telemetry_data()['broadcast_driver_data'])

    def test_pace_car_and_spectator_cameras_are_unavailable_with_their_own_reason(self):
        for flag in ('CarIsPaceCar', 'IsSpectator'):
            with self.subTest(flag=flag):
                roster = {'Drivers': [driver(1, 'Ada', '21', 11, 'GT3'),
                                      driver(2, 'Safety', '0', 11, 'GT3', **{flag: 1})]}
                assert_unavailable(self, card(CamCarIdx=2, DriverInfo=roster), 'camera_target_excluded')

    def test_camera_switch_replaces_the_whole_card(self):
        provider = make_provider(broadcast_sample(CamCarIdx=2))
        first = provider.get_telemetry_data()['broadcast_driver_data']
        self.assertEqual(first['name'], 'Bob')
        # Car 3 has no roster entry and only the SDK's empty-slot values.
        provider.ir_sdk.update(CamCarIdx=3, CarIdxPosition=[4, 3, 1, 0], CarIdxClassPosition=[2, 1, 1, 0],
                               CarIdxLapCompleted=[5, 6, 7, -1], CarIdxLastLapTime=[1.0, 2.0, 3.0, -1.0],
                               CarIdxBestLapTime=[1.0, 2.0, 3.0, -1.0],
                               CarIdxOnPitRoad=[False, False, False, None],
                               DriverInfo={'Drivers': [driver(2, 'Bob', '7', 12, 'LMP2')]})
        second = provider.get_telemetry_data()['broadcast_driver_data']
        self.assertEqual(second['camera_car_idx'], 3)
        self.assertIs(second['identity_available'], False)
        for key in IDENTITY_KEYS + STAT_KEYS:
            self.assertIsNone(second[key], key)
        provider.ir_sdk.update(CamCarIdx=-1)
        assert_unavailable(self, provider.get_telemetry_data()['broadcast_driver_data'])
        provider.ir_sdk.update(CamCarIdx=2)
        third = provider.get_telemetry_data()['broadcast_driver_data']
        self.assertEqual((third['name'], third['last_lap_s']), ('Bob', 3.0))


class TestIdentityAndRoster(unittest.TestCase):
    def test_camera_car_present_but_roster_absent_has_explicit_unavailable_identity(self):
        for roster in (None, {}, {'Drivers': []}, {'Drivers': 'bad'}):
            with self.subTest(roster=roster):
                sample = broadcast_sample()
                del sample['DriverInfo']
                if roster is not None:
                    sample['DriverInfo'] = roster
                payload = make_provider(sample).get_telemetry_data()['broadcast_driver_data']
                self.assertIs(payload['available'], True)
                self.assertIs(payload['identity_available'], False)
                self.assertEqual(payload['camera_car_idx'], 2)
                for key in IDENTITY_KEYS:
                    self.assertIsNone(payload[key], key)
                # Never a default name such as "Car 2"; class rank needs a class.
                self.assertIsNone(payload['class_position'])
                self.assertEqual((payload['position'], payload['last_lap_s'], payload['laps_completed']),
                                 (1, 88.25, 7))

    def test_roster_holes_leave_identity_unavailable_but_keep_guarded_stats(self):
        roster = {'Drivers': [driver(1, 'Ada', '21', 11, 'GT3'), driver(3, 'Cyd', '44', 12, 'LMP2')]}
        payload = card(CamCarIdx=2, DriverInfo=roster)
        self.assertIs(payload['identity_available'], False)
        self.assertEqual([payload[k] for k in IDENTITY_KEYS], [None] * 4)
        self.assertEqual(payload['position'], 1)

    def test_missing_or_unusable_fields_are_null_not_invented(self):
        bad = {'Drivers': [driver(2, None, '', None, None)]}
        payload = card(CamCarIdx=2, DriverInfo=bad)
        self.assertIs(payload['identity_available'], True)
        self.assertEqual([payload[k] for k in IDENTITY_KEYS], [None] * 4)
        self.assertIsNone(payload['class_position'])
        for car_class in (-3, True, 2.5, 'x'):
            with self.subTest(class_id=car_class):
                payload = card(DriverInfo={'Drivers': [driver(2, 'Bob', '7', car_class, 'LMP2')]})
                self.assertIsNone(payload['class_id'])
                self.assertIsNone(payload['class_position'])
                self.assertEqual(payload['class_name'], 'LMP2')

    def test_numeric_driver_fields_are_text_and_zero_class_is_real(self):
        payload = card(DriverInfo={'Drivers': [driver(2, 'Bob', 7, 0, 'Solo')]})
        self.assertEqual((payload['car_number'], payload['class_id'], payload['class_position']), ('7', 0, 1))

    def test_personal_account_identifiers_are_never_published(self):
        roster = {'Drivers': [driver(2, 'Bob', '7', 12, 'LMP2', UserID=424242, TeamName='Secret Team',
                                     AbbrevName='B', Initials='B.', IRating=4321)]}
        text = json.dumps(card(DriverInfo=roster))
        for private in ('424242', 'Secret Team', '4321'):
            self.assertNotIn(private, text)


class TestStats(unittest.TestCase):
    def test_zero_is_real_and_unranked_or_invalid_values_are_null(self):
        payload = card(CarIdxLapCompleted=[0, 0, 0, 0], CarIdxPosition=[0, 0, 0, 0],
                       CarIdxClassPosition=[0, 0, 0, 0])
        self.assertEqual(payload['laps_completed'], 0)
        self.assertIsNone(payload['position'])
        self.assertIsNone(payload['class_position'])
        for bad in (-1, True, 1.5, math.nan, 'x', None):
            with self.subTest(laps=bad):
                self.assertIsNone(card(CarIdxLapCompleted=[1, 1, bad, 1])['laps_completed'])
        # NaN and text positions already abort the pre-existing relative builder
        # (no payload at all), so only values that pipeline survives are probed.
        for bad in (-1, True, 1.5, None):
            with self.subTest(position=bad):
                self.assertIsNone(card(CarIdxPosition=[1, 1, bad, 1])['position'])

    def test_negative_zero_and_non_finite_lap_times_are_null(self):
        for bad in (-1.0, 0.0, 0, math.nan, math.inf, -math.inf, True, 'x', None):
            with self.subTest(time=bad):
                payload = card(CarIdxLastLapTime=[1, 1, bad, 1], CarIdxBestLapTime=[1, 1, bad, 1])
                self.assertIsNone(payload['last_lap_s'])
                self.assertIsNone(payload['best_lap_s'])
        self.assertEqual(card(CarIdxLastLapTime=[1, 1, 12.3456, 1])['last_lap_s'], 12.346)

    def test_pit_road_is_a_real_boolean_or_unknown(self):
        self.assertIs(card(CarIdxOnPitRoad=[0, 0, True, 0])['on_pit_road'], True)
        self.assertIs(card(CarIdxOnPitRoad=[0, 0, False, 0])['on_pit_road'], False)
        for bad in (None, 1, 0, 'yes'):
            with self.subTest(value=bad):
                self.assertIsNone(card(CarIdxOnPitRoad=[False, False, bad, False])['on_pit_road'])

    def test_missing_short_or_mistyped_arrays_leave_stats_null(self):
        for value in (None, [], [1], 'bad'):
            with self.subTest(arrays=value):
                payload = card(CarIdxPosition=value, CarIdxClassPosition=value, CarIdxLapCompleted=value,
                               CarIdxLastLapTime=value, CarIdxBestLapTime=value, CarIdxOnPitRoad=value)
                self.assertIs(payload['available'], True)
                self.assertEqual(payload['name'], 'Bob')
                for key in STAT_KEYS:
                    self.assertIsNone(payload[key], key)

    def test_values_come_from_the_camera_car_not_the_player(self):
        # Make the player's own entries obviously different from the camera car's.
        payload = card(CamCarIdx=3, PlayerCarIdx=1, LapLastLapTime=11.1, LapBestLapTime=10.1)
        self.assertEqual((payload['name'], payload['last_lap_s'], payload['best_lap_s']), ('Cyd', 88.4, 87.9))
        self.assertNotIn('11.1', json.dumps(payload))

    def test_session_type_comes_only_from_confirmed_session_metadata(self):
        self.assertEqual(card()['session_type'], 'Race')
        practice = {'Sessions': [{'SessionNum': 0, 'SessionType': 'Practice'}]}
        self.assertEqual(card(SessionInfo=practice)['session_type'], 'Practice')
        for session in (None, {}, {'Sessions': []}, {'Sessions': [{'SessionNum': 5, 'SessionType': 'Race'}]},
                        {'Sessions': [{'SessionNum': 0, 'SessionType': '  '}]}):
            with self.subTest(session=session):
                sample = broadcast_sample()
                del sample['SessionInfo']
                if session is not None:
                    sample['SessionInfo'] = session
                payload = make_provider(sample).get_telemetry_data()['broadcast_driver_data']
                self.assertIsNone(payload['session_type'])
                self.assertIs(payload['available'], True)


class TestNoPlayerMetricLeak(unittest.TestCase):
    def test_player_only_values_never_appear_whoever_the_camera_follows(self):
        for camera in (0, 1, 2, 3, None, -1, 99):
            with self.subTest(camera=camera):
                payload = card(CamCarIdx=camera)
                self.assertEqual(set(payload), PAYLOAD_KEYS)
                text = json.dumps(payload)
                for leak in LEAK_TEXT:
                    self.assertNotIn(leak, text)

    def test_changing_player_only_telemetry_does_not_change_the_card(self):
        a = card(CamCarIdx=2)
        b = card(CamCarIdx=2, Speed=1.0, Gear=1, Throttle=0.0, Brake=1.0, RPM=900.0, FuelLevel=1.0)
        self.assertEqual(a, b)

    def test_no_player_only_key_exists_in_the_schema(self):
        banned = ('speed', 'throttle', 'brake', 'clutch', 'steering', 'rpm', 'gear', 'fuel')
        for key in card(CamCarIdx=1):
            for word in banned:
                self.assertNotIn(word, key)


class SocketTestBase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(WebInterface, '_start_telemetry_thread')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.web = WebInterface()
        self.web.data_provider.ir_sdk = FakeSDK(broadcast_sample())
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
    def test_event_carries_the_provider_payload_on_its_own_namespace(self):
        client = self.client('/broadcast_driver')
        self.web._process_telemetry_data()
        payloads = self.events(client, '/broadcast_driver', 'broadcast_driver_update')
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]['name'], 'Bob')
        self.assertEqual(payloads[0]['position'], 1)
        self.assertEqual(payloads[0]['last_lap_s'], 88.25)
        self.assertIs(payloads[0]['on_pit_road'], False)

    def test_unavailable_card_and_nulls_survive_the_wire(self):
        self.web.data_provider.ir_sdk.update(CamCarIdx=0, CarIdxLapCompleted=[0, 0, 0, 0],
                                             CarIdxLastLapTime=[None, 0, 0, 0])
        client = self.client('/broadcast_driver')
        self.web._process_telemetry_data()
        payload = self.events(client, '/broadcast_driver', 'broadcast_driver_update')[0]
        self.assertEqual((payload['camera_car_idx'], payload['laps_completed']), (0, 0))
        self.assertIsNone(payload['last_lap_s'])
        self.web.data_provider.ir_sdk.update(CamCarIdx=-1)
        self.web._process_telemetry_data()
        payload = self.events(client, '/broadcast_driver', 'broadcast_driver_update')[0]
        assert_unavailable(self, payload)

    def test_missing_section_emits_a_null_payload(self):
        client = self.client('/broadcast_driver')
        with mock.patch.object(self.web.data_provider, 'get_telemetry_data',
                               return_value={'speed': 1.0, 'gear': 2}):
            self.web._process_telemetry_data()
        self.assertEqual(self.events(client, '/broadcast_driver', 'broadcast_driver_update'), [None])

    def test_a_failing_emit_does_not_block_other_overlays_and_vice_versa(self):
        weather_client = self.client('/weather')
        real_emit = self.web.socketio.emit

        def emit(event, *args, **kwargs):
            if event == 'broadcast_driver_update':
                raise RuntimeError('boom')
            return real_emit(event, *args, **kwargs)

        with mock.patch.object(self.web.socketio, 'emit', side_effect=emit):
            self.web._process_telemetry_data()
        self.assertEqual(len(self.events(weather_client, '/weather', 'weather_update')), 1)

        broadcast_client = self.client('/broadcast_driver')

        def emit_weather_fails(event, *args, **kwargs):
            if event == 'weather_update':
                raise RuntimeError('boom')
            return real_emit(event, *args, **kwargs)

        with mock.patch.object(self.web.socketio, 'emit', side_effect=emit_weather_fails):
            self.web._process_telemetry_data()
        self.assertEqual(len(self.events(broadcast_client, '/broadcast_driver', 'broadcast_driver_update')), 1)

    def test_legacy_events_do_not_gain_the_new_section(self):
        telemetry = self.client('/input_telemetry', disconnect=False)
        self.web._process_telemetry_data()
        payload = self.events(telemetry, '/input_telemetry', 'telemetry_update')[0]
        self.assertNotIn('broadcast_driver_data', payload)
        for key in ('speed', 'gear', 'throttle', 'brake', 'clutch', 'steering_wheel_angle',
                    'relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data'):
            self.assertIn(key, payload)


class TestHttpSurface(SocketTestBase):
    def test_overlay_is_discoverable_with_valid_properties(self):
        http = self.web.app.test_client()
        overlays = {o['folder_name']: o for o in http.get('/get_overlays').get_json()}
        self.assertIn('broadcast_driver', overlays)
        self.assertTrue(overlays['broadcast_driver']['display_name'])
        self.assertTrue(overlays['broadcast_driver']['description'])
        self.assertNotIn('?', overlays['broadcast_driver']['url'])

    def test_page_and_assets_serve_and_both_themes_get_the_same_page(self):
        http = self.web.app.test_client()
        page = http.get('/overlay/broadcast_driver')
        self.addCleanup(page.close)
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn('overlay-theme.css', body)
        self.assertIn('overlay_theme.js', body)
        self.assertIn('socket.io.min.js', body)
        self.assertLess(body.index('broadcast_driver.css'), body.index('overlay-theme.css'))
        for asset in ('broadcast_driver.css', 'broadcast_driver.js'):
            response = http.get(f'/overlay/broadcast_driver/static/{asset}')
            self.addCleanup(response.close)
            self.assertEqual(response.status_code, 200, asset)
        for theme in ('glass', 'original'):
            themed = http.get(f'/overlay/broadcast_driver?theme={theme}')
            self.addCleanup(themed.close)
            self.assertEqual(themed.get_data(), page.get_data())


if __name__ == '__main__':
    unittest.main()

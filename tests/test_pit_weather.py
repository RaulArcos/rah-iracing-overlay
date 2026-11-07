"""Pit Assistant and Weather tests (T5, S1-S5).

Exercises the public DataProvider.get_telemetry_data entry point with an
injected fake SDK, the dedicated Socket.IO namespaces/events through the
flask-socketio test client (the telemetry thread is stubbed, no simulator is
started), and the HTTP discovery/asset surface for both new overlays.
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

NEW_OVERLAYS = ('pit_assistant', 'weather')
PIT_KEYS = ('speed_kmh', 'on_pit_road', 'in_pit_stall', 'pits_open', 'service_active',
            'pit_speed_limit_kmh', 'pit_speed_limit_source', 'pit_speed_margin_kmh',
            'pit_speed_state', 'repair_left_s', 'optional_repair_left_s', 'tow_time_s',
            'service_flags', 'service_flags_raw', 'service_status', 'service_status_code',
            'service_fuel_amount', 'service_fuel_requested')
WEATHER_KEYS = ('air_temp_c', 'track_temp_c', 'humidity_pct', 'wind_speed_ms',
                'wind_speed_kmh', 'wind_dir_deg', 'precipitation_pct', 'track_wetness',
                'track_wetness_code', 'declared_wet')
BAD_NUMBERS = (None, float('nan'), float('inf'), -1.0, 'x', True)


def pit_sample(**overrides):
    """A connected sample on pit road at 57.6 km/h with a 60 kph limit."""
    sample = dict(
        Speed=16.0,
        OnPitRoad=True, PlayerCarInPitStall=False, PitsOpen=True, PitstopActive=False,
        PitRepairLeft=0.0, PitOptRepairLeft=0.0, PlayerCarTowTime=0.0,
        PitSvFlags=0, PlayerCarPitSvStatus=0, PitSvFuel=0.0,
        WeekendInfo={'TrackLength': '5.891 km', 'TrackPitSpeedLimit': '60.00 kph'},
        AirTemp=21.5, TrackTempCrew=33.5, RelativeHumidity=0.55, WindVel=3.0,
        WindDir=math.pi / 2, Precipitation=0.0, TrackWetness=1, WeatherDeclaredWet=False,
    )
    sample.update(overrides)
    return base_sample(**sample)


def pit(**overrides):
    return make_provider(pit_sample(**overrides)).get_telemetry_data()['pit_assistant_data']


def weather(**overrides):
    return make_provider(pit_sample(**overrides)).get_telemetry_data()['weather_data']


def limit(text):
    return pit(WeekendInfo={'TrackPitSpeedLimit': text})['pit_speed_limit_kmh']


class TestPayloadContract(unittest.TestCase):
    def test_connected_payload_adds_both_sections_and_keeps_legacy_keys(self):
        result = make_provider(pit_sample()).get_telemetry_data()
        self.assertEqual(set(PIT_KEYS) - set(result['pit_assistant_data']), set())
        self.assertEqual(set(WEATHER_KEYS) - set(result['weather_data']), set())
        for key in ('speed', 'relative_data', 'track_map_data', 'radar_data',
                    'blindspot_data', 'laptime_graph_data', 'fuel_finish_data',
                    'session_strip_data', 'standings_data', 'battle_pace_data'):
            self.assertIn(key, result)

    def test_disconnected_provider_still_returns_empty_dict(self):
        provider = make_provider(pit_sample())
        provider.is_connected = False
        self.assertEqual(provider.get_telemetry_data(), {})

    def test_nothing_is_invented_without_telemetry(self):
        result = make_provider({'Lap': 1}).get_telemetry_data()
        for key in PIT_KEYS:
            self.assertIsNone(result['pit_assistant_data'][key], key)
        for key in WEATHER_KEYS:
            self.assertIsNone(result['weather_data'][key], key)

    def test_new_sections_do_not_change_any_other_payload_key(self):
        sample = pit_sample()
        stripped = {key: value for key, value in sample.items()
                    if key not in ('PitsOpen', 'PitstopActive', 'PitRepairLeft', 'PitOptRepairLeft',
                                   'PlayerCarTowTime', 'PitSvFlags', 'PlayerCarPitSvStatus',
                                   'PitSvFuel', 'AirTemp', 'TrackTempCrew', 'RelativeHumidity',
                                   'WindVel', 'WindDir', 'Precipitation', 'TrackWetness',
                                   'WeatherDeclaredWet')}
        with_vars = make_provider(sample).get_telemetry_data()
        without = make_provider(stripped).get_telemetry_data()
        for key in ('pit_assistant_data', 'weather_data'):
            del with_vars[key], without[key]
        # R2 intentionally also exposes TrackTempCrew in these additive
        # summaries. Pin that one new leaf, then compare every other value.
        for key in ('relative_data', 'standings_data'):
            self.assertEqual(with_vars[key]['session_summary'].pop('track_temp_c'), 33.5)
            self.assertIsNone(without[key]['session_summary'].pop('track_temp_c'))
        self.assertEqual(with_vars, without)

    def test_overflowing_values_never_leave_a_non_finite_number_in_either_payload(self):
        huge = 1e308
        result = make_provider(pit_sample(Speed=huge, WindVel=huge, WindDir=huge, AirTemp=huge,
                                          PitRepairLeft=huge)).get_telemetry_data()
        for key in ('pit_assistant_data', 'weather_data'):
            json.dumps(result[key], allow_nan=False)
        self.assertIsNone(result['pit_assistant_data']['speed_kmh'])
        self.assertIsNone(result['weather_data']['wind_speed_kmh'])
        self.assertIsNone(result['weather_data']['wind_dir_deg'])

    def test_a_failing_builder_cannot_break_the_rest_of_the_payload(self):
        provider = make_provider(pit_sample())
        with mock.patch.object(type(provider), '_pit_speed_limit_kmh', side_effect=RuntimeError('boom')), \
                mock.patch.object(type(provider), '_percent_from_fraction', side_effect=RuntimeError('boom')):
            result = provider.get_telemetry_data()
        self.assertAlmostEqual(result['pit_assistant_data']['speed_kmh'], 57.6, places=3)
        self.assertIsNone(result['pit_assistant_data']['pit_speed_limit_kmh'])
        self.assertEqual(result['weather_data']['air_temp_c'], 21.5)
        self.assertIsNone(result['weather_data']['humidity_pct'])
        for key in ('speed', 'fuel_finish_data', 'standings_data'):
            self.assertIn(key, result)


class TestPitStatus(unittest.TestCase):
    STATUS_KEYS = ('on_pit_road', 'in_pit_stall', 'pits_open', 'service_active')

    def test_status_flags_report_real_booleans(self):
        data = pit(OnPitRoad=True, PlayerCarInPitStall=True, PitsOpen=True, PitstopActive=True)
        self.assertEqual([data[k] for k in self.STATUS_KEYS], [True] * 4)
        data = pit(OnPitRoad=False, PlayerCarInPitStall=False, PitsOpen=False, PitstopActive=False)
        self.assertEqual([data[k] for k in self.STATUS_KEYS], [False] * 4)

    def test_missing_or_corrupt_flags_are_unknown_not_false(self):
        for bad in (None, 1, 0, 'yes', 'False', 1.0):
            with self.subTest(value=bad):
                data = pit(OnPitRoad=bad, PlayerCarInPitStall=bad, PitsOpen=bad, PitstopActive=bad)
                self.assertEqual([data[k] for k in self.STATUS_KEYS], [None] * 4)

    def test_speed_is_converted_from_meters_per_second(self):
        self.assertAlmostEqual(pit(Speed=16.0)['speed_kmh'], 57.6, places=3)
        self.assertEqual(pit(Speed=0.0)['speed_kmh'], 0.0)
        for bad in BAD_NUMBERS:
            with self.subTest(speed=bad):
                self.assertIsNone(pit(Speed=bad)['speed_kmh'])

    def test_repair_and_tow_times_are_seconds_and_zero_is_real(self):
        data = pit(PitRepairLeft=12.5, PitOptRepairLeft=0.0, PlayerCarTowTime=30.25)
        self.assertEqual((data['repair_left_s'], data['optional_repair_left_s'], data['tow_time_s']),
                         (12.5, 0.0, 30.25))
        for bad in BAD_NUMBERS:
            with self.subTest(value=bad):
                data = pit(PitRepairLeft=bad, PitOptRepairLeft=bad, PlayerCarTowTime=bad)
                self.assertEqual((data['repair_left_s'], data['optional_repair_left_s'], data['tow_time_s']),
                                 (None, None, None))


class TestPitSpeedLimit(unittest.TestCase):
    def test_limit_needs_explicit_units_and_is_converted_to_kmh(self):
        self.assertEqual(limit('60.00 kph'), 60.0)
        self.assertEqual(limit('80 km/h'), 80.0)
        self.assertAlmostEqual(limit('45.00 mph'), 72.42, places=2)
        self.assertAlmostEqual(limit('16.5 m/s'), 59.4, places=3)
        self.assertEqual(pit()['pit_speed_limit_source'], 'WeekendInfo.TrackPitSpeedLimit')

    def test_limit_from_yaml_string_metadata(self):
        data = pit(WeekendInfo='TrackPitSpeedLimit: 50.00 kph\n')
        self.assertEqual(data['pit_speed_limit_kmh'], 50.0)

    def test_unitless_short_or_hostile_metadata_is_not_a_limit(self):
        for bad in ('60', '60.00', 'kph', '', '60 furlongs', 'kph 60', '-60 kph', '0 kph',
                    'nan kph', 'inf kph', '1e3 kph', '60 kph; DROP', None, 60, 60.0, True, ['60 kph']):
            with self.subTest(metadata=bad):
                data = pit(WeekendInfo={'TrackPitSpeedLimit': bad})
                self.assertIsNone(data['pit_speed_limit_kmh'])
                self.assertIsNone(data['pit_speed_limit_source'])
        for bad in (None, 'not: [valid', 42):
            self.assertIsNone(pit(WeekendInfo=bad)['pit_speed_limit_kmh'])

    def test_margin_and_state_come_from_real_speed_and_limit_on_pit_road(self):
        data = pit(Speed=16.0)
        self.assertAlmostEqual(data['pit_speed_margin_kmh'], 2.4, places=3)
        self.assertEqual(data['pit_speed_state'], 'within_limit')
        data = pit(Speed=20.0)
        self.assertAlmostEqual(data['pit_speed_margin_kmh'], -12.0, places=3)
        self.assertEqual(data['pit_speed_state'], 'over_limit')

    def test_exactly_at_the_limit_is_within_with_a_real_zero_margin(self):
        data = pit(Speed=60.0 / 3.6)
        self.assertEqual(data['pit_speed_margin_kmh'], 0.0)
        self.assertEqual(data['pit_speed_state'], 'within_limit')

    def test_no_margin_without_pit_road_valid_speed_or_known_limit(self):
        cases = {
            'off pit road': dict(OnPitRoad=False),
            'pit road unknown': dict(OnPitRoad=None),
            'speed missing': dict(Speed=None),
            'speed invalid': dict(Speed=float('nan')),
            'limit missing': dict(WeekendInfo={}),
            'limit unitless': dict(WeekendInfo={'TrackPitSpeedLimit': '60'}),
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                data = pit(**overrides)
                self.assertIsNone(data['pit_speed_margin_kmh'])
                self.assertIsNone(data['pit_speed_state'])

    def test_no_pit_limiter_state_is_claimed(self):
        self.assertFalse([key for key in pit() if 'limiter' in key])


class TestPitService(unittest.TestCase):
    def test_service_flags_use_the_installed_irsdk_names(self):
        import irsdk
        data = pit(PitSvFlags=irsdk.PitSvFlags.lf_tire_change | irsdk.PitSvFlags.fuel_fill)
        self.assertEqual(data['service_flags'], ['lf_tire_change', 'fuel_fill'])
        self.assertIs(data['service_fuel_requested'], True)
        data = pit(PitSvFlags=0)
        self.assertEqual((data['service_flags'], data['service_flags_raw']), ([], 0))
        self.assertIs(data['service_fuel_requested'], False)

    def test_unknown_flag_bits_stay_raw_and_are_not_named(self):
        data = pit(PitSvFlags=128 | 16)
        self.assertEqual(data['service_flags'], ['fuel_fill'])
        self.assertEqual(data['service_flags_raw'], 144)

    def test_invalid_flags_are_unknown(self):
        for bad in (None, -1, True, 'x', 1.5, float('nan')):
            with self.subTest(flags=bad):
                data = pit(PitSvFlags=bad)
                self.assertEqual((data['service_flags'], data['service_flags_raw'],
                                  data['service_fuel_requested']), (None, None, None))

    def test_service_status_uses_the_installed_enum_and_keeps_unknown_codes(self):
        self.assertEqual(pit(PlayerCarPitSvStatus=0)['service_status'], 'none')
        self.assertEqual(pit(PlayerCarPitSvStatus=2)['service_status'], 'complete')
        data = pit(PlayerCarPitSvStatus=101)
        self.assertEqual((data['service_status'], data['service_status_code']), ('too_far_right', 101))
        data = pit(PlayerCarPitSvStatus=55)
        self.assertEqual((data['service_status'], data['service_status_code']), (None, 55))
        for bad in (None, True, 'x', 1.5):
            data = pit(PlayerCarPitSvStatus=bad)
            self.assertEqual((data['service_status'], data['service_status_code']), (None, None))

    def test_service_fuel_is_an_sdk_amount_with_an_ambiguous_unit_never_liters(self):
        data = pit(PitSvFuel=25.5, PitSvFlags=16)
        self.assertEqual(data['service_fuel_amount'], 25.5)
        self.assertEqual(data['service_fuel_unit'], 'L/kWh')
        self.assertFalse([key for key in data if key.endswith('_l') or 'added' in key])
        self.assertEqual(pit(PitSvFuel=0.0)['service_fuel_amount'], 0.0)
        for bad in BAD_NUMBERS:
            with self.subTest(fuel=bad):
                self.assertIsNone(pit(PitSvFuel=bad)['service_fuel_amount'])

    def test_requested_fuel_is_not_reused_as_a_finish_estimate(self):
        fuel = make_provider(pit_sample(PitSvFuel=25.5, PitSvFlags=16)).get_telemetry_data()['fuel_finish_data']
        self.assertIsNone(fuel['finish_fuel_to_add_l'])
        self.assertNotIn(25.5, [v for v in fuel.values() if isinstance(v, float)])


class TestWeather(unittest.TestCase):
    def test_reports_observed_values_with_explicit_units(self):
        data = weather()
        self.assertEqual(data['air_temp_c'], 21.5)
        self.assertEqual(data['track_temp_c'], 33.5)
        self.assertAlmostEqual(data['humidity_pct'], 55.0)
        self.assertEqual(data['wind_speed_ms'], 3.0)
        self.assertAlmostEqual(data['wind_speed_kmh'], 10.8)
        self.assertAlmostEqual(data['wind_dir_deg'], 90.0)
        self.assertEqual(data['precipitation_pct'], 0.0)
        self.assertEqual((data['track_wetness'], data['track_wetness_code']), ('dry', 1))
        self.assertIs(data['declared_wet'], False)
        self.assertIs(data['observed'], True)

    def test_negative_and_zero_temperatures_are_real(self):
        data = weather(AirTemp=-4.5, TrackTempCrew=0.0)
        self.assertEqual((data['air_temp_c'], data['track_temp_c']), (-4.5, 0.0))

    def test_temperature_rejects_non_finite_text_and_bools(self):
        for bad in (None, float('nan'), float('inf'), 'x', True):
            with self.subTest(value=bad):
                data = weather(AirTemp=bad, TrackTempCrew=bad)
                self.assertEqual((data['air_temp_c'], data['track_temp_c']), (None, None))

    def test_deprecated_track_temp_is_not_used_as_a_fallback(self):
        self.assertIsNone(weather(TrackTempCrew=None, TrackTemp=30.0)['track_temp_c'])

    def test_fractions_become_percent_with_inclusive_bounds(self):
        for key, var in (('humidity_pct', 'RelativeHumidity'), ('precipitation_pct', 'Precipitation')):
            with self.subTest(var=var):
                self.assertEqual(weather(**{var: 0.0})[key], 0.0)
                self.assertEqual(weather(**{var: 1.0})[key], 100.0)
                self.assertAlmostEqual(weather(**{var: 0.375})[key], 37.5)
                for bad in (1.01, -0.01, 55.0, float('nan'), float('inf'), None, 'x', True):
                    self.assertIsNone(weather(**{var: bad})[key], bad)

    def test_wind_speed_is_non_negative_and_zero_is_real(self):
        data = weather(WindVel=0.0)
        self.assertEqual((data['wind_speed_ms'], data['wind_speed_kmh']), (0.0, 0.0))
        for bad in BAD_NUMBERS:
            data = weather(WindVel=bad)
            self.assertEqual((data['wind_speed_ms'], data['wind_speed_kmh']), (None, None), bad)

    def test_wind_direction_is_normalised_to_degrees(self):
        for radians, degrees in ((0.0, 0.0), (math.pi, 180.0), (-math.pi / 2, 270.0),
                                 (2 * math.pi, 0.0), (3 * math.pi, 180.0)):
            with self.subTest(radians=radians):
                self.assertAlmostEqual(weather(WindDir=radians)['wind_dir_deg'], degrees, places=1)
        self.assertLess(weather(WindDir=-1e-9)['wind_dir_deg'], 360.0)
        for bad in (None, float('nan'), float('inf'), 'x', True):
            self.assertIsNone(weather(WindDir=bad)['wind_dir_deg'])

    def test_wetness_uses_the_installed_enum_and_keeps_unknown_codes(self):
        self.assertEqual(weather(TrackWetness=7)['track_wetness'], 'extremely_wet')
        data = weather(TrackWetness=0)
        self.assertEqual((data['track_wetness'], data['track_wetness_code']), ('unknown', 0))
        data = weather(TrackWetness=99)
        self.assertEqual((data['track_wetness'], data['track_wetness_code']), (None, 99))
        for bad in (None, True, 'x', 1.5, float('nan')):
            data = weather(TrackWetness=bad)
            self.assertEqual((data['track_wetness'], data['track_wetness_code']), (None, None))

    def test_declared_wet_distinguishes_false_from_unknown(self):
        self.assertIs(weather(WeatherDeclaredWet=True)['declared_wet'], True)
        self.assertIs(weather(WeatherDeclaredWet=False)['declared_wet'], False)
        for bad in (None, 1, 0, 'yes'):
            self.assertIsNone(weather(WeatherDeclaredWet=bad)['declared_wet'])

    def test_payload_has_no_forecast_trend_or_direction_claim(self):
        for key in weather():
            for banned in ('forecast', 'trend', 'probab', 'from', 'toward', 'sunny', 'rain_'):
                self.assertNotIn(banned, key)


class SocketTestBase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(WebInterface, '_start_telemetry_thread')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.web = WebInterface()
        self.web.data_provider.ir_sdk = FakeSDK(pit_sample())
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
    def test_events_carry_the_provider_payloads_on_their_own_namespaces(self):
        pit_client = self.client('/pit_assistant')
        weather_client = self.client('/weather')
        self.web._process_telemetry_data()
        pits = self.events(pit_client, '/pit_assistant', 'pit_assistant_update')
        weathers = self.events(weather_client, '/weather', 'weather_update')
        self.assertEqual((len(pits), len(weathers)), (1, 1))
        self.assertAlmostEqual(pits[0]['speed_kmh'], 57.6, places=3)
        self.assertEqual(pits[0]['pit_speed_state'], 'within_limit')
        self.assertEqual(weathers[0]['air_temp_c'], 21.5)
        self.assertEqual(weathers[0]['precipitation_pct'], 0.0)
        self.assertAlmostEqual(weathers[0]['wind_dir_deg'], 90.0)

    def test_nulls_and_real_zeroes_survive_the_wire(self):
        self.web.data_provider.ir_sdk.update(PitRepairLeft=0.0, PitSvFuel=None, WindVel=0.0, AirTemp=None)
        pit_client = self.client('/pit_assistant')
        weather_client = self.client('/weather')
        self.web._process_telemetry_data()
        pit_payload = self.events(pit_client, '/pit_assistant', 'pit_assistant_update')[0]
        weather_payload = self.events(weather_client, '/weather', 'weather_update')[0]
        self.assertEqual(pit_payload['repair_left_s'], 0.0)
        self.assertIsNone(pit_payload['service_fuel_amount'])
        self.assertEqual(weather_payload['wind_speed_ms'], 0.0)
        self.assertIsNone(weather_payload['air_temp_c'])

    def test_missing_sections_emit_a_null_payload(self):
        pit_client = self.client('/pit_assistant')
        weather_client = self.client('/weather')
        with mock.patch.object(self.web.data_provider, 'get_telemetry_data',
                               return_value={'speed': 1.0, 'gear': 2}):
            self.web._process_telemetry_data()
        self.assertEqual(self.events(pit_client, '/pit_assistant', 'pit_assistant_update'), [None])
        self.assertEqual(self.events(weather_client, '/weather', 'weather_update'), [None])

    def test_a_failing_emit_does_not_block_the_other_overlays(self):
        weather_client = self.client('/weather')
        real_emit = self.web.socketio.emit

        def emit(event, *args, **kwargs):
            if event == 'pit_assistant_update':
                raise RuntimeError('boom')
            return real_emit(event, *args, **kwargs)

        with mock.patch.object(self.web.socketio, 'emit', side_effect=emit):
            self.web._process_telemetry_data()
        self.assertEqual(len(self.events(weather_client, '/weather', 'weather_update')), 1)

    def test_legacy_events_do_not_gain_the_new_sections(self):
        telemetry = self.client('/input_telemetry', disconnect=False)
        self.web._process_telemetry_data()
        payload = self.events(telemetry, '/input_telemetry', 'telemetry_update')[0]
        self.assertNotIn('pit_assistant_data', payload)
        self.assertNotIn('weather_data', payload)
        for key in ('speed', 'gear', 'throttle', 'brake', 'clutch', 'steering_wheel_angle',
                    'relative_data', 'track_map_data', 'radar_data', 'blindspot_data',
                    'laptime_graph_data'):
            self.assertIn(key, payload)


class TestHttpSurface(SocketTestBase):
    def test_both_overlays_are_discoverable_with_valid_properties(self):
        http = self.web.app.test_client()
        overlays = {o['folder_name']: o for o in http.get('/get_overlays').get_json()}
        for name in NEW_OVERLAYS:
            self.assertIn(name, overlays)
            self.assertTrue(overlays[name]['display_name'])
            self.assertTrue(overlays[name]['description'])
            self.assertNotIn('?', overlays[name]['url'])

    def test_pages_and_assets_serve_and_both_themes_get_the_same_page(self):
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
                for theme in ('glass', 'original'):
                    themed = http.get(f'/overlay/{name}?theme={theme}')
                    self.addCleanup(themed.close)
                    self.assertEqual(themed.get_data(), page.get_data())


if __name__ == '__main__':
    unittest.main()

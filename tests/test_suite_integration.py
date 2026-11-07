"""Suite integration tests (T7, S1-S5).

Drives all 14 overlays through the public surface only: the HTTP discovery and
asset routes, the Socket.IO namespaces/events (flask-socketio test client, the
telemetry thread stubbed) and one frozen FakeSDK tick built from the existing
per-unit fixtures. No simulator, server, or browser is started.

The new tests pin existing behaviour from T1-T6, so they were GREEN on first
run (structural coverage); there is no RED to observe.

`python tests/test_suite_integration.py --dump-wire` prints the wire payloads
as JSON for the Node integration test, which renders them with the real
overlay scripts.
"""

import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import unittest
from unittest import mock

# Must be set before web_interface is imported (threading mode, no eventlet).
os.environ['FORCE_THREADING_MODE'] = 'true'

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import test_battle_standings as battle  # noqa: E402
import test_fuel_session as fuel  # noqa: E402
import test_pit_weather as pit_weather  # noqa: E402
import test_theme_routes as theme_routes  # noqa: E402
from test_telemetry_accuracy import FakeSDK, base_sample  # noqa: E402
from web_interface import WebInterface  # noqa: E402

OVERLAYS = theme_routes.OVERLAYS
SRC_ROOT = theme_routes.SRC_ROOT
EVENTS = {
    'input_telemetry': 'telemetry_update',
    'relative': 'relative_update',
    'radar': 'radar_update',
    'blindspot': 'blindspot_update',
    'track_map': 'track_map_update',
    'laptime_graph': 'laptime_graph_update',
    'fuel_finish': 'fuel_finish_update',
    'session_strip': 'session_strip_update',
    'battle_pace': 'battle_pace_update',
    'standings': 'standings_update',
    'pit_assistant': 'pit_assistant_update',
    'weather': 'weather_update',
    'broadcast_driver': 'broadcast_driver_update',
    'delta': 'delta_update',
}
# Namespaces that predate the suite declare on_disconnect(self), which fails
# on the reason argument newer flask-socketio passes; leave them connected.
LEGACY = OVERLAYS[:6]
DEDICATED = OVERLAYS[6:]


def suite_sample(**overrides):
    """One race tick every dedicated builder can read.

    Starts from the multiclass race fixture and adds only the scalar fields
    the fuel and pit/weather fixtures introduce, so each existing helper stays
    the single owner of its own telemetry shape. The player is car 1 (Ada)
    and the broadcast camera follows car 2 (Bob).
    """
    plain = base_sample()
    extra = {}
    for source in (fuel.fuel_sample(), pit_weather.pit_sample()):
        extra.update({key: value for key, value in source.items() if key not in plain})
    extra.update(Speed=16.0, WeekendInfo=pit_weather.pit_sample()['WeekendInfo'], CamCarIdx=2)
    extra.update(overrides)
    return battle.race_sample(**extra)


def make_web():
    with mock.patch.object(WebInterface, '_start_telemetry_thread'), \
            contextlib.redirect_stdout(io.StringIO()):  # WebInterface prints namespace names
        return WebInterface()


def use_sdk(web, sample, connected=True):
    web.data_provider.ir_sdk = FakeSDK(sample)
    web.data_provider.is_connected = connected


def connect_all(web):
    clients = {}
    for name in OVERLAYS:
        client = web.socketio.test_client(web.app, namespace=f'/{name}')
        client.get_received(f'/{name}')  # drop connect acknowledgement
        clients[name] = client
    return clients


def drain(clients):
    """Events received per overlay since the last drain, as (name, payload)."""
    return {name: [(event['name'], event['args'][0] if event['args'] else None)
                   for event in client.get_received(f'/{name}')]
            for name, client in clients.items()}


def payloads(received):
    return {name: events[0][1] for name, events in received.items() if events}


def strict_json(value):
    return json.dumps(value, allow_nan=False)


def non_finite(value):
    if isinstance(value, float):
        return [value] if not math.isfinite(value) else []
    if isinstance(value, dict):
        return [bad for item in value.values() for bad in non_finite(item)]
    if isinstance(value, (list, tuple)):
        return [bad for item in value for bad in non_finite(item)]
    return []


class WireTestBase(unittest.TestCase):
    def setUp(self):
        self.web = make_web()
        self.provider = self.web.data_provider
        self.clients = connect_all(self.web)
        for name in DEDICATED:
            self.addCleanup(self.clients[name].disconnect, f'/{name}')

    def tick(self):
        self.web._process_telemetry_data()
        return drain(self.clients)


class TestDiscoveryAndRouting(WireTestBase):
    def test_all_thirteen_overlays_are_discovered_with_unique_names_and_plain_urls(self):
        overlays = self.web.app.test_client().get('/get_overlays').get_json()
        self.assertEqual(len(overlays), 14)
        self.assertEqual({o['folder_name'] for o in overlays}, set(OVERLAYS))
        self.assertEqual(len({o['display_name'] for o in overlays}), 14)
        for overlay in overlays:
            self.assertTrue(overlay['display_name'] and overlay['description'])
            self.assertTrue(overlay['url'].endswith(f"/overlay/{overlay['folder_name']}"))
            self.assertNotIn('?', overlay['url'])

    def test_every_overlay_connects_to_its_own_namespace(self):
        for name, client in self.clients.items():
            with self.subTest(overlay=name):
                self.assertTrue(client.is_connected(f'/{name}'))

    def test_one_tick_reaches_every_overlay_on_its_own_event_only(self):
        use_sdk(self.web, suite_sample())
        received = self.tick()
        for name in OVERLAYS:
            with self.subTest(overlay=name):
                self.assertEqual([event for event, _ in received[name]], [EVENTS[name]])

    def test_dedicated_events_carry_the_frozen_sample_values(self):
        use_sdk(self.web, suite_sample())
        data = payloads(self.tick())
        self.assertEqual(data['fuel_finish']['fuel_level_l'], 50.0)
        self.assertEqual((data['session_strip']['session_type'], data['session_strip']['laps_remaining']),
                         ('Race', 10))
        self.assertEqual((data['battle_pace']['context'], data['battle_pace']['player']['name'],
                          data['battle_pace']['ahead']['name']), ('ok', 'Ada', 'Fay'))
        self.assertEqual([g['class_name'] for g in data['standings']['classes']], ['LMP2', 'GT3'])
        self.assertEqual((data['pit_assistant']['on_pit_road'], data['pit_assistant']['pit_speed_limit_kmh'],
                          data['pit_assistant']['read_only']), (True, 60.0, True))
        self.assertEqual((data['weather']['air_temp_c'], data['weather']['track_wetness']), (21.5, 'dry'))
        self.assertEqual((data['broadcast_driver']['name'], data['broadcast_driver']['source']),
                         ('Bob', 'CamCarIdx'))

    def test_legacy_input_event_keeps_its_flat_shape_without_dedicated_sections(self):
        use_sdk(self.web, suite_sample())
        telemetry = payloads(self.tick())['input_telemetry']
        self.assertEqual((telemetry['gear'], telemetry['throttle']), (4, 0.62))
        self.assertAlmostEqual(telemetry['speed'], 57.6)
        for key in ('fuel_finish_data', 'session_strip_data', 'battle_pace_data', 'standings_data',
                    'pit_assistant_data', 'weather_data', 'broadcast_driver_data'):
            self.assertNotIn(key, telemetry)


class TestNativeJsonRules(WireTestBase):
    def test_ordinary_missing_telemetry_is_null_never_a_fabricated_zero(self):
        # A connected SDK that exposes nothing yet (menu / loading screen).
        use_sdk(self.web, {})
        data = payloads(self.tick())
        for name, payload in data.items():
            with self.subTest(overlay=name):
                strict_json(payload)
        self.assertIsNone(data['fuel_finish']['fuel_level_l'])
        self.assertIsNone(data['session_strip']['session_type'])
        self.assertEqual((data['battle_pace']['context'], data['battle_pace']['player']), ('player_unavailable', None))
        self.assertEqual(data['standings']['classes'], [])
        self.assertIsNone(data['pit_assistant']['pit_speed_limit_kmh'])
        self.assertIsNone(data['weather']['air_temp_c'])
        self.assertIs(data['broadcast_driver']['available'], False)
        self.assertIsNone(data['broadcast_driver']['name'])

    def test_real_non_finite_telemetry_never_reaches_the_wire(self):
        lap_times = list(suite_sample()['CarIdxLastLapTime'])
        lap_times[2] = math.inf
        use_sdk(self.web, suite_sample(FuelLevel=math.nan, AirTemp=math.inf, TrackTempCrew=-math.inf,
                                       Throttle=math.nan, CarIdxLastLapTime=lap_times))
        received = self.tick()
        for name, events in received.items():
            with self.subTest(overlay=name):
                self.assertEqual(len(events), 1)
                strict_json(events[0][1])
                self.assertEqual(non_finite(events[0][1]), [])
        data = payloads(received)
        self.assertIsNone(data['fuel_finish']['fuel_level_l'])
        self.assertIsNone(data['weather']['air_temp_c'])
        self.assertIsNone(data['weather']['track_temp_c'])
        self.assertIsNone(data['broadcast_driver']['last_lap_s'])

    def test_a_missing_section_is_sent_as_null_to_its_own_overlay_only(self):
        use_sdk(self.web, suite_sample())
        with mock.patch.object(self.provider, 'get_telemetry_data', return_value={'speed': 1.0, 'gear': 2}):
            received = self.tick()
        for name in DEDICATED:
            with self.subTest(overlay=name):
                self.assertEqual(received[name], [(EVENTS[name], None)])
        self.assertEqual(payloads(received)['input_telemetry']['gear'], 2)


class TestViewIsolation(WireTestBase):
    def dedicated_except(self, data, *skip):
        return {name: data[name] for name in DEDICATED if name not in skip}

    def test_camera_switch_only_changes_the_broadcast_card(self):
        use_sdk(self.web, suite_sample())
        before = payloads(self.tick())
        self.assertEqual(before['broadcast_driver']['name'], 'Bob')
        self.provider.ir_sdk.update(CamCarIdx=3)
        after = payloads(self.tick())
        self.assertEqual((after['broadcast_driver']['name'], after['broadcast_driver']['car_number']),
                         ('Cyd', '44'))
        self.assertEqual(self.dedicated_except(after, 'broadcast_driver'),
                         self.dedicated_except(before, 'broadcast_driver'))
        self.assertEqual(after['input_telemetry'], before['input_telemetry'])
        self.provider.ir_sdk.update(CamCarIdx=-1)
        gone = payloads(self.tick())
        self.assertEqual((gone['broadcast_driver']['available'], gone['broadcast_driver']['name']), (False, None))
        self.assertEqual(self.dedicated_except(gone, 'broadcast_driver'),
                         self.dedicated_except(before, 'broadcast_driver'))

    def test_session_change_resets_fuel_sampling_and_relabels_every_session_view(self):
        use_sdk(self.web, suite_sample(OnPitRoad=False, Lap=1))
        self.tick()
        for lap, level, last in ((2, 48.5, 90.0), (3, 47.0, 91.0), (4, 45.5, 90.5)):
            self.provider.ir_sdk.update(Lap=lap, FuelLevel=level, LapLastLapTime=last)
            seeded = payloads(self.tick())
        self.assertEqual(seeded['fuel_finish']['burn_sample_count'], 2)
        self.assertEqual(seeded['fuel_finish']['avg_burn_l_per_lap'], 1.5)
        self.assertEqual(seeded['standings']['session_type'], 'Race')

        self.provider.ir_sdk.update(SessionNum=1, Lap=1, SessionInfo={'Sessions': [
            {'SessionNum': 1, 'SessionType': 'Lone Qualify', 'SessionLaps': 'unlimited', 'SessionTime': '600.0 sec'}]})
        after = payloads(self.tick())
        self.assertEqual(after['fuel_finish']['burn_sample_count'], 0)
        self.assertIsNone(after['fuel_finish']['avg_burn_l_per_lap'])
        for name in ('session_strip', 'battle_pace', 'standings', 'broadcast_driver'):
            self.assertEqual(after[name]['session_type'], 'Lone Qualify', name)
        # Unrelated views keep describing the same car, track and weather.
        self.assertEqual(after['broadcast_driver']['name'], 'Bob')
        self.assertEqual(after['weather'], seeded['weather'])
        self.assertEqual(after['pit_assistant']['pit_speed_limit_kmh'], 60.0)

    def test_dedicated_payloads_do_not_borrow_each_others_telemetry(self):
        use_sdk(self.web, suite_sample())
        data = payloads(self.tick())
        for name in ('weather', 'pit_assistant', 'broadcast_driver'):
            with self.subTest(overlay=name):
                self.assertNotIn('fuel_level_l', data[name])
        for name in ('fuel_finish', 'weather', 'broadcast_driver', 'standings'):
            with self.subTest(overlay=name):
                self.assertNotIn('speed_kmh', data[name])


class TestNoSimulatorDefaults(WireTestBase):
    def test_default_provider_is_disconnected_and_emits_nothing(self):
        # Fresh WebInterface: real irsdk object, never started, no sim data.
        self.assertIs(self.provider.is_connected, False)
        self.assertEqual(self.provider.get_telemetry_data(), {})
        received = self.tick()
        self.assertEqual({name: events for name, events in received.items() if events}, {})

    def test_losing_the_sim_stops_the_stream_instead_of_replaying_the_last_frame(self):
        use_sdk(self.web, suite_sample())
        self.assertEqual(len(payloads(self.tick())), 14)
        self.provider.disconnect()
        self.assertEqual(self.provider.get_telemetry_data(), {})
        self.assertEqual({name: events for name, events in self.tick().items() if events}, {})


class TestPagesAndThemes(theme_routes.ThemeRouteTestBase):
    def get(self, url):
        response = self.client.get(url)
        self.addCleanup(response.close)
        return response

    def test_every_page_serves_with_all_of_its_local_assets(self):
        for name in OVERLAYS:
            with self.subTest(overlay=name):
                page = self.get(f'/overlay/{name}')
                self.assertEqual(page.status_code, 200)
                body = page.get_data(as_text=True)
                assets = set(re.findall(r'(?:href|src)="(/[^"]+)"', body))
                self.assertTrue(any(a.endswith('overlay-theme.css') for a in assets))
                self.assertTrue(any(a.endswith('overlay_theme.js') for a in assets))
                for asset in assets:
                    self.assertEqual(self.get(asset).status_code, 200, asset)

    def test_default_and_explicit_theme_urls_share_one_page_per_overlay(self):
        # The theme is resolved client-side (Original by default, Glass on
        # ?theme=glass), so the server must not fork the page by query.
        for name in OVERLAYS:
            with self.subTest(overlay=name):
                plain = self.get(f'/overlay/{name}').get_data()
                for query in ('?theme=glass', '?theme=original', '?theme=unknown'):
                    self.assertEqual(self.get(f'/overlay/{name}{query}').get_data(), plain, query)

    def test_launch_defaults_to_the_plain_original_url_and_pins_glass_on_request(self):
        digests = self.properties_digests()
        for name in OVERLAYS:
            with self.subTest(overlay=name):
                for theme, suffix in ((None, ''), ('glass', '?theme=glass')):
                    theme_routes.FakeOverlayProcess.launched = []
                    payload = {'overlay': self.display_name(name), 'transparent': True}
                    if theme:
                        payload['theme'] = theme
                    response = self.client.post('/launch', json=payload, follow_redirects=True)
                    self.assertEqual(response.get_json()['status'], 'success')
                    self.assertEqual(theme_routes.FakeOverlayProcess.launched[0].args[0],
                                     f'{self.overlay_url(name)}{suffix}')
                    self.client.post('/close_overlay', json={'overlay': self.display_name(name)})
        self.assertEqual(digests, self.properties_digests())

    def properties_digests(self):
        digests = {}
        for name in OVERLAYS:
            with open(os.path.join(SRC_ROOT, 'overlays', name, 'properties.json'), 'rb') as handle:
                digests[name] = hashlib.sha256(handle.read()).hexdigest()
        return digests


def dump_wire():
    """Wire payloads for the Node integration test (stdout: one JSON object)."""
    with contextlib.redirect_stdout(sys.stderr):  # namespaces print on connect
        web = make_web()
        clients = connect_all(web)
        out = {}
        use_sdk(web, suite_sample())
        web._process_telemetry_data()
        out['live'] = payloads(drain(clients))
        use_sdk(web, {})
        web._process_telemetry_data()
        out['sdk_empty'] = payloads(drain(clients))
        with mock.patch.object(web.data_provider, 'get_telemetry_data', return_value={'speed': 1.0}):
            web._process_telemetry_data()
        out['missing_sections'] = {name: events[0][1] for name, events in drain(clients).items()
                                   if name in DEDICATED and events}
    sys.__stdout__.write(strict_json(out))


if __name__ == '__main__':
    if '--dump-wire' in sys.argv:
        dump_wire()
    else:
        unittest.main()

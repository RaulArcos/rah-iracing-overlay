"""R3 observations through the public provider; legacy boundaries remain owner."""
import unittest
from test_telemetry_accuracy import make_provider
from test_battle_standings import race_sample, step


class TestLapObservations(unittest.TestCase):
    def setUp(self):
        self.p = make_provider(race_sample(Lap=5, LapCompleted=4,
            PlayerCarMyIncidentCount=0, TrackTempCrew=28.0))
        self.p.get_telemetry_data()

    def poll(self, **changes):
        self.p.ir_sdk.update(**changes)
        return self.p.get_telemetry_data()['laptime_graph_data']

    def close(self, lap=6, **changes):
        return self.poll(Lap=lap, LapCompleted=lap-1, LapLastLapTime=91.25, **changes)

    def test_first_partial_unknown_then_completion_temperature_and_incident(self):
        first = self.close()['records'][0]
        self.assertIsNone(first['incident'])
        self.assertEqual(first['lap_number'], 5)
        self.assertEqual(first['track_temp_c'], 28)
        self.poll(PlayerCarMyIncidentCount=2, TrackTempCrew=29)
        data = self.close(7, TrackTempCrew=30)
        self.assertEqual(data['records'][-1], dict(lap_number=6, time_s=91.25,
            track_temp_c=30.0, incident=True, observation='observed'))
        self.poll(TrackTempCrew=40)
        self.assertEqual(self.poll()['records'][-1]['track_temp_c'], 30)
        self.assertEqual(data['history'], [91.25, 91.25])

    def test_duplicate_skip_and_delayed_values_never_enrich_old_laps(self):
        self.close()
        data = self.close(9, TrackTempCrew=35, PlayerCarMyIncidentCount=4)
        self.assertEqual(len(data['records']), 2)
        self.assertEqual(data['records'][-1], dict(lap_number=None, time_s=91.25,
            track_temp_c=None, incident=None, observation='unavailable'))
        self.assertEqual(self.poll()['records'], data['records'])
        self.poll(Lap=10, LapCompleted=9, LapLastLapTime=None)
        self.poll(LapLastLapTime=92, TrackTempCrew=50)
        self.assertEqual(len(self.poll()['records']), 2)

    def test_incident_missing_reset_and_boundary_ordering(self):
        self.close()
        self.assertIs(self.close(7, PlayerCarMyIncidentCount=1)['records'][-1]['incident'], True)
        self.poll(PlayerCarMyIncidentCount=None)
        self.poll(PlayerCarMyIncidentCount=1)
        self.assertIsNone(self.close(8)['records'][-1]['incident'])
        self.poll(PlayerCarMyIncidentCount=0)
        self.assertIsNone(self.close(9)['records'][-1]['incident'])
        self.assertIs(self.close(10)['records'][-1]['incident'], False)

    def test_missing_negative_nan_values_and_missing_lap_taint_incidents(self):
        self.close()
        for i, bad in enumerate((None, -1, float('nan'), True)):
            self.poll(PlayerCarMyIncidentCount=bad)
            data = self.close(7+i, PlayerCarMyIncidentCount=0, TrackTempCrew=bad)
            self.assertIsNone(data['records'][-1]['incident'])
            # Negative finite Celsius is legitimate; booleans/NaN are not.
            self.assertEqual(data['records'][-1]['track_temp_c'], -1 if bad == -1 else None)
        self.poll(Lap=None)
        self.assertIsNone(self.close(11)['records'][-1]['incident'])

    def test_session_reconnect_rollback_and_bounded_alignment(self):
        for lap in range(6, 20):
            data = self.close(lap)
        self.assertEqual(len(data['records']), 10)
        self.assertEqual([r['time_s'] for r in data['records']], data['history'])
        self.assertEqual(self.poll(SessionNum=2)['records'], [])
        self.close(20)
        self.assertEqual(self.poll(Lap=1)['records'], [])
        self.close(2)
        self.p.disconnect()
        self.p.connect()
        self.assertEqual(self.poll()['records'], [])

    def test_recent_times_reuse_guarded_pace_and_null_pair_holes(self):
        result = step(self.p, {1: 5, 5: 5}, {1: 91, 5: 90})
        self.assertEqual(result['battle_pace_data']['player']['recent_laps_s'], [91])
        result = step(self.p, {1: 6}, {1: 92})
        battle = result['battle_pace_data']
        self.assertEqual(battle['ahead']['recent_laps_s'], [90])
        self.assertEqual(battle['ahead']['recent_deltas_s'], [None, -2])
        result = step(self.p, {1: 9}, {1: 80})
        self.assertEqual(result['battle_pace_data']['player']['recent_laps_s'], [])

    def test_new_metadata_does_not_change_legacy_graph_or_fuel_outputs(self):
        plain = make_provider(race_sample(Lap=5))
        plain.get_telemetry_data()
        for lap in (6, 6, 8, 9, 2):
            changes = dict(Lap=lap, LapLastLapTime=90+lap, FuelLevel=40-lap)
            self.p.ir_sdk.update(**changes)
            plain.ir_sdk.update(**changes)
            a, b = self.p.get_telemetry_data(), plain.get_telemetry_data()
            self.assertEqual(a['fuel_finish_data'], b['fuel_finish_data'])
            self.assertEqual({k:v for k,v in a['laptime_graph_data'].items() if k != 'records'},
                             {k:v for k,v in b['laptime_graph_data'].items() if k != 'records'})

    def test_nonfinite_lap_poll_never_claims_no_incidents(self):
        self.close()
        self.poll(Lap=float('nan'))
        self.assertIsNone(self.close(7)['records'][-1]['incident'])

    def test_invalid_times_never_append_and_missing_completed_label_is_unknown(self):
        for lap, bad in enumerate((None, -1, 0, float('nan'), float('inf')), start=6):
            self.assertEqual(self.poll(Lap=lap, LapLastLapTime=bad)['records'], [])
        data = self.poll(Lap=11, LapLastLapTime=92, LapCompleted=None)
        self.assertIsNone(data['records'][0]['lap_number'])
        self.assertEqual(data['history'], [92])

    def test_invalid_or_penalty_flags_do_not_invent_an_incident(self):
        self.close()
        data = self.close(7, LapDeltaToBestLap_OK=False, PlayerCarPenaltyCount=2, SessionFlags=0x4000)
        self.assertIs(data['records'][-1]['incident'], False)

    def test_recent_observations_duplicate_pit_invalid_reset_and_bound(self):
        for completed in range(5, 14):
            result = step(self.p, {1:completed, 5:completed}, {1:90+completed/10, 5:90})
        self.assertEqual(len(result['battle_pace_data']['player']['recent_laps_s']), 5)
        self.assertEqual(step(self.p)['battle_pace_data'], result['battle_pace_data'])
        pits = [False]*7
        pits[1] = True
        step(self.p, CarIdxOnPitRoad=pits)
        result = step(self.p, {1:14}, {1:91}, CarIdxOnPitRoad=[False]*7)
        self.assertEqual(result['battle_pace_data']['player']['recent_laps_s'], [])
        self.assertEqual(result['battle_pace_data']['ahead']['recent_deltas_s'], [None]*5)
        result = step(self.p, {1:15}, {1:float('nan')})
        self.assertEqual(result['battle_pace_data']['player']['recent_laps_s'], [])
        result = step(self.p, SessionNum=1)
        self.assertEqual(result['battle_pace_data']['player']['recent_laps_s'], [])

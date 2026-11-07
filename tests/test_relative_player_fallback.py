"""Relative shows the player's own iRating/licence before they are classified
(practice, AI and test sessions), and keeps unranked on-track cars."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from race_metadata import enrich_race_metadata  # noqa: E402

DRIVERS = [
    {'CarIdx': 0, 'UserName': 'Player', 'CarNumber': '7', 'IRating': 1834, 'LicString': 'A 3.42',
     'LicSubLevel': 342, 'LicColor': '0x0153db', 'CarClassID': 1, 'CarClassShortName': 'GT3'},
    {'CarIdx': 1, 'UserName': 'AI One', 'CarNumber': '9', 'IRating': 0, 'LicString': 'R 0.00',
     'LicSubLevel': 0, 'CarClassID': 1},
]


class FakeProvider:
    def _get_session_dict(self, key):
        return {'Drivers': DRIVERS} if key == 'DriverInfo' else {}

    def _get_sdk_value(self, key, default=None):
        return {'PlayerCarIdx': 0, 'CarIdxOnPitRoad': [False, False]}.get(key, default)

    def _text_or_none(self, value):
        return value

    def _get_driver_metadata(self):
        return {0: {'car_number': '7', 'name': 'Player', 'excluded': False},
                1: {'car_number': '9', 'name': 'AI One', 'excluded': False}}


class RelativePlayerFallbackTests(unittest.TestCase):
    def setUp(self):
        import player_profile
        self.addCleanup(os.environ.pop, 'RAH_PROFILE_CACHE', None)
        os.environ['RAH_PROFILE_CACHE'] = os.path.join(tempfile.mkdtemp(), 'profile.json')
        player_profile._memory = None

    def test_unclassified_player_keeps_rating_and_licence(self):
        data = {'relative_data': {'player_car_idx': 0, 'player_position': 0,
                                  'cars': [{'car_idx': 1, 'gap': 1.2}]},
                'standings_data': {'classes': []}, 'session_strip_data': {}}
        enrich_race_metadata(data, FakeProvider())
        player = data['relative_data']['player']
        self.assertTrue(player['is_player'])
        self.assertEqual(player['car_idx'], 0)
        self.assertEqual(player['irating'], 1834)
        self.assertEqual(player['license'], 'A')
        self.assertAlmostEqual(player['safety_rating'], 3.42)
        self.assertIsNone(player['position'])
        self.assertEqual(player['gap'], 0.0)
        # AI opponent without a rating stays honest: no invented values.
        self.assertIsNone(data['relative_data']['cars'][0]['irating'])


    def test_ai_session_placeholder_is_not_shown_as_a_rating(self):
        global DRIVERS
        saved = DRIVERS
        DRIVERS = [dict(saved[0], IRating=1, LicString='R 0.01', LicLevel=1, LicSubLevel=1,
                        LicColor=None, CarIsAI=0),
                   dict(saved[1], CarIsAI=1)]
        try:
            data = {'relative_data': {'player_car_idx': 0, 'player_position': 0, 'cars': []},
                    'standings_data': {'classes': []}, 'session_strip_data': {}}
            enrich_race_metadata(data, FakeProvider())
            player = data['relative_data']['player']
            self.assertTrue(player['is_player'])
            self.assertIsNone(player['irating'])
            self.assertIsNone(player['license'])
            self.assertEqual(player['profile_unavailable_reason'], 'ai_session_placeholder')
        finally:
            DRIVERS = saved


if __name__ == '__main__':
    unittest.main()

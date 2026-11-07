"""AI sessions show the player's last real online profile, marked as such."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import player_profile  # noqa: E402
from race_metadata import enrich_race_metadata  # noqa: E402


def drivers(ai_session):
    player = dict(CarIdx=0, UserID=4242, UserName='Player', CarNumber='7', CarIsAI=0,
                  CarClassID=1, CarClassShortName='GT3')
    if ai_session:
        player.update(IRating=1, LicString='R 0.01', LicLevel=1, LicSubLevel=1, LicColor=None)
    else:
        player.update(IRating=1834, LicString='A 3.42', LicLevel=19, LicSubLevel=342, LicColor='0x0153db')
    opponent = dict(CarIdx=1, UserID=99, UserName='Other', CarNumber='9', CarIsAI=int(ai_session),
                    IRating=0 if ai_session else 2100, LicString='R 0.00' if ai_session else 'B 2.10',
                    LicSubLevel=0 if ai_session else 210, CarClassID=1)
    return [player, opponent]


class Provider:
    def __init__(self, roster):
        self.roster = roster

    def _get_session_dict(self, key):
        return {'Drivers': self.roster} if key == 'DriverInfo' else {}

    def _get_sdk_value(self, key, default=None):
        return {'PlayerCarIdx': 0, 'CarIdxOnPitRoad': [False, False]}.get(key, default)

    def _text_or_none(self, value):
        return value

    def _get_driver_metadata(self):
        return {0: {'car_number': '7', 'name': 'Player'}, 1: {'car_number': '9', 'name': 'Other'}}


def poll(roster):
    data = {'relative_data': {'player_car_idx': 0, 'player_position': 0, 'cars': []},
            'standings_data': {'classes': []}, 'session_strip_data': {}}
    enrich_race_metadata(data, Provider(roster))
    return data['relative_data']['player']


class PlayerProfileMemoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ['RAH_PROFILE_CACHE'] = os.path.join(self.dir, 'profile.json')
        player_profile._memory = None

    def tearDown(self):
        os.environ.pop('RAH_PROFILE_CACHE', None)
        player_profile._memory = None

    def test_ai_session_without_history_stays_unavailable(self):
        player = poll(drivers(ai_session=True))
        self.assertIsNone(player['irating'])
        self.assertEqual(player['profile_unavailable_reason'], 'ai_session_placeholder')

    def test_online_profile_is_remembered_and_shown_in_ai_session(self):
        online = poll(drivers(ai_session=False))
        self.assertEqual(online['irating'], 1834)
        with open(os.environ['RAH_PROFILE_CACHE']) as handle:
            stored = json.load(handle)
        self.assertEqual(list(stored), ['id:4242'])  # only the player is stored
        player_profile._memory = None  # as after an app restart
        ai = poll(drivers(ai_session=True))
        self.assertEqual(ai['irating'], 1834)
        self.assertEqual(ai['license'], 'A')
        self.assertAlmostEqual(ai['safety_rating'], 3.42)
        self.assertEqual(ai['profile_source'], 'last_online')
        self.assertIsNone(ai['profile_unavailable_reason'])

    def test_unwritable_cache_never_breaks_the_poll(self):
        blocker = os.path.join(self.dir, 'blocker')
        open(blocker, 'w').close()  # a file where a folder is needed
        os.environ['RAH_PROFILE_CACHE'] = os.path.join(blocker, 'p.json')
        player_profile._memory = None
        self.assertEqual(poll(drivers(ai_session=False))['irating'], 1834)


if __name__ == '__main__':
    unittest.main()

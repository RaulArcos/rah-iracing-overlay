"""Remember the player's own online iRating / licence for AI sessions.

In AI (offline) sessions the SDK reports the player's profile as an
IRating 1 / "R 0.01" placeholder, so the real values are not available in
the sim. Whenever a real (online) profile is seen for the player it is kept
in a small local JSON file, and in AI sessions the Relative/Standings show
that last-known profile, clearly marked as such. Nothing is fetched from the
network and only the player's own record is stored.
"""
import json
import os
import sys
import threading
import time

_lock = threading.Lock()
_memory = None  # path -> dict, loaded lazily


def cache_path():
    override = os.environ.get('RAH_PROFILE_CACHE')
    if override:
        return override
    if 'unittest' in sys.modules and not getattr(sys, 'frozen', False):
        # Test fixtures must never touch the real player's profile file.
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.git', 'test-player-profile.json')
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RAH Telemetry Overlay', 'player_profile.json')


def _key(driver):
    uid = driver.get('UserID')
    if isinstance(uid, int) and not isinstance(uid, bool) and uid > 0:
        return f'id:{uid}'
    name = driver.get('UserName')
    return f'name:{name.strip()}' if isinstance(name, str) and name.strip() else None


def _load():
    global _memory
    path = cache_path()
    if _memory is None or _memory.get('__path') != path:
        data = {}
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                loaded = json.load(handle)
            data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            data = {}
        _memory = {'__path': path, 'profiles': data}
    return _memory['profiles']


PROFILE_KEYS = ('irating', 'license', 'safety_rating', 'license_color')


def remember(driver, member):
    """Store a real profile for the player; cheap no-op when unchanged."""
    key = _key(driver)
    if not key or member.get('is_ai') is True or member.get('profile_unavailable_reason'):
        return
    if not isinstance(member.get('irating'), int) or not member.get('license'):
        return
    record = {k: member.get(k) for k in PROFILE_KEYS}
    with _lock:
        profiles = _load()
        previous = profiles.get(key) or {}
        if all(previous.get(k) == record[k] for k in PROFILE_KEYS):
            return
        record['seen_at'] = int(time.time())
        profiles[key] = record
        path = cache_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump(profiles, handle, indent=2)
            os.replace(temporary, path)
        except OSError:
            pass  # memory is best-effort; the overlay keeps working


def recall(driver):
    """Last real profile seen for this player, or None."""
    key = _key(driver)
    if not key:
        return None
    with _lock:
        record = _load().get(key)
    if not isinstance(record, dict) or not isinstance(record.get('irating'), int):
        return None
    return dict(record)

"""Stateless, additive Relative/Standings metadata. SDK provenance in docs.

No timing, lap sampling or connection state is modified here.
"""
import math
import re

import player_profile


def integer(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value != int(value) or value < minimum:
        return None
    return int(value)


def number(value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if minimum is None or value >= minimum else None


def color(value):
    """SDK YAML hex strings may be parsed by PyYAML as integer RGB values."""
    if isinstance(value, str) and re.fullmatch(r'(?:0x|#)[0-9a-fA-F]{6}', value):
        return '#' + value[-6:].lower()
    rgb = integer(value)
    return f'#{rgb:06x}' if rgb is not None and rgb <= 0xffffff else None


def ai_flag(value):
    if isinstance(value, bool):
        return value
    return bool(value) if integer(value) in (0, 1) else None


def driver_metadata(driver, ai_session=False, is_player=False):
    raw = driver.get('LicString')
    match = re.fullmatch(r'(R|D|C|B|A|P|Pro|WC)(?:\s+[0-4]\.\d{1,2})?', raw.strip()) if isinstance(raw, str) else None
    license_class = match.group(1) if match else None
    sublevel = integer(driver.get('LicSubLevel'), 1)
    is_ai = ai_flag(driver.get('CarIsAI'))
    placeholder = (ai_session and is_player and is_ai is False and
                   driver.get('IRating') == 1 and isinstance(raw, str) and
                   re.fullmatch(r'R\s*0\.01', raw.strip()) and
                   driver.get('LicLevel') == 1 and sublevel == 1 and
                   color(driver.get('LicColor')) is None)
    unavailable = is_ai is True or placeholder
    return {
        'is_ai': is_ai,
        'profile_unavailable_reason': 'ai_driver' if is_ai is True else
            'ai_session_placeholder' if placeholder else None,
        'irating': None if unavailable else integer(driver.get('IRating'), 1),
        'license': None if unavailable else license_class,
        'safety_rating': sublevel / 100 if not unavailable and license_class and sublevel is not None and sublevel < 500 else None,
        'license_color': None if unavailable else color(driver.get('LicColor')),
        'class_color': color(driver.get('CarClassColor')),
        # Neither qualifying rank nor live classification confirms actual
        # race start position (custom grids, heats, reversed grids, pit starts).
        'positions_gained': None,
        'positions_gained_source': None,
    }


def strength(members):
    ratings = [m['irating'] for m in members if m['irating'] is not None]
    value = None
    if ratings:
        # Stable equivalent of -1600/log(2) * log(mean(exp(-r*log(2)/1600))).
        low = min(ratings)
        value = round(low - 1600 / math.log(2) * math.log(
            sum(math.exp(-(r - low) * math.log(2) / 1600) for r in ratings) / len(ratings)))
    return {'value': value, 'rated': len(ratings), 'total': len(members),
            'complete': bool(members) and len(ratings) == len(members)}


def _unclassified_player(provider, idx, relative):
    """Minimal player record from DriverInfo + per-car arrays (no timing)."""
    try:
        identity = provider._get_driver_metadata().get(idx, {})
    except Exception:
        identity = {}
    on_pit = provider._get_sdk_value('CarIdxOnPitRoad', None)
    pit = on_pit[idx] if isinstance(on_pit, (list, tuple)) and idx < len(on_pit) else None
    return {
        'car_idx': idx, 'position': integer(relative.get('player_position'), 1), 'class_position': None,
        'car_number': identity.get('car_number'), 'name': identity.get('name'),
        'on_pit_road': None if pit is None else bool(pit), 'is_player': True,
        'laps_completed': None, 'best_lap_s': None, 'last_lap_s': None,
    }


def enrich_race_metadata(data, provider):
    """One poll, both widgets; preserve every existing payload value."""
    info = provider._get_session_dict('DriverInfo')
    if not info:
        info = provider._get_session_dict('SessionInfo').get('DriverInfo') or {}
    drivers = info.get('Drivers') if isinstance(info, dict) else None
    drivers = drivers if isinstance(drivers, list) else []
    ai_session = any(isinstance(d, dict) and ai_flag(d.get('CarIsAI')) is True and
                     not any(d.get(k) for k in ('CarIsPaceCar', 'IsSpectator')) for d in drivers)
    player_idx = integer(provider._get_sdk_value('PlayerCarIdx', None))
    roster, classes = {}, {}
    for driver in drivers if isinstance(drivers, list) else []:
        if not isinstance(driver, dict):
            continue
        idx = integer(driver.get('CarIdx'))
        if idx is None or idx in roster:
            continue
        if any(driver.get(key) for key in ('CarIsPaceCar', 'IsSpectator')):
            continue
        member = driver_metadata(driver, ai_session, idx == player_idx)
        if idx == player_idx:
            if member['profile_unavailable_reason'] == 'ai_session_placeholder':
                # AI sessions only expose a placeholder: show the last real
                # profile seen online, marked as last-known.
                known = player_profile.recall(driver)
                if known:
                    member.update({k: known.get(k) for k in player_profile.PROFILE_KEYS},
                                  profile_source='last_online', profile_seen_at=known.get('seen_at'),
                                  profile_unavailable_reason=None)
            else:
                player_profile.remember(driver, member)
        member.update(class_id=integer(driver.get('CarClassID')),
                      class_name=provider._text_or_none(driver.get('CarClassShortName')))
        roster[idx] = member
        if member['class_id'] is not None:
            classes.setdefault(member['class_id'], []).append(member)

    empty = driver_metadata({})
    sofs = {key: strength(members) for key, members in classes.items()}
    if ai_session:
        for sof in sofs.values():
            sof.update(value=None, complete=False, is_ai_session=True)
    strip = data.get('session_strip_data') or {}
    summary = {
        'is_ai_session': ai_session,
        'session_type': strip.get('session_type'),
        'elapsed_s': number(provider._get_sdk_value('SessionTime', None), 0),
        'time_limit_s': strip.get('session_time_total_s'),
        'lap': strip.get('lap'), 'lap_limit': strip.get('session_laps_total'),
        'track_temp_c': number(provider._get_sdk_value('TrackTempCrew', None)),
        'field_size': len(roster) or None,
    }
    standings = data.get('standings_data')
    classified = {}
    if isinstance(standings, dict):
        standings['session_summary'] = dict(summary)
        for group in standings['classes']:
            group['sof'] = sofs.get(group['class_id'], strength([]))
            colors = {m['class_color'] for m in classes.get(group['class_id'], []) if m['class_color']}
            group['class_color'] = next(iter(colors)) if len(colors) == 1 else None
            for car in group['cars']:
                car.update(roster.get(car['car_idx'], empty))
                classified[car['car_idx']] = car

    relative = data.get('relative_data')
    if isinstance(relative, dict):
        relative['session_summary'] = dict(summary)
        idx = integer(provider._get_sdk_value('PlayerCarIdx', None))
        player = classified.get(idx)
        if player is None and idx is not None and idx in roster:
            # Not classified yet (practice/AI/test session before a timed lap,
            # or a grid with no positions): still show the player's own row
            # with identity and whatever licence/iRating DriverInfo provides.
            player = _unclassified_player(provider, idx, relative)
        relative['player'] = dict(player) if player else None
        relative['player_class_sof'] = sofs.get(roster.get(idx, {}).get('class_id'), strength([]))
        for car in relative['cars']:
            car.update(roster.get(car['car_idx'], empty))
            car['is_player'] = False
        if player:
            relative['player'].update(roster.get(idx, {}))
            relative['player'].update(gap=0.0, gap_is_estimate=False, track_delta_pct=0.0, is_player=True)

"""Physical Relative using SDK estimated track-location time profiles, not F2."""
from race_metadata import integer, number


def build_relative(provider):
    get = provider._get_sdk_value
    arrays = {key: provider._safe_list(get(key, [])) for key in (
        'CarIdxPosition', 'CarIdxClassPosition', 'CarIdxLapDistPct',
        'CarIdxLapCompleted', 'CarIdxOnPitRoad', 'CarIdxEstTime')}

    def at(key, idx):
        values = arrays[key]
        return values[idx] if idx is not None and 0 <= idx < len(values) else None

    def pct(idx):
        value = number(at('CarIdxLapDistPct', idx), 0)
        return value if value is not None and value <= 1 else None

    info = provider._get_session_dict('DriverInfo')
    if not info:
        info = provider._get_session_dict('SessionInfo').get('DriverInfo') or {}
    info = info if isinstance(info, dict) else {}
    drivers = info.get('Drivers')
    roster = {}
    for driver in drivers if isinstance(drivers, list) else []:
        if isinstance(driver, dict):
            idx = integer(driver.get('CarIdx'))
            if idx is not None:
                roster.setdefault(idx, driver)

    def period(idx):
        value = number(roster.get(idx, {}).get('CarClassEstLapTime'), 0)
        return value if value and value > 0 else None

    def coordinate(idx, duration):
        value = number(at('CarIdxEstTime', idx), 0)
        if duration is None or value is None or value > duration:
            return None
        # Zero is the SDK's unavailable sentinel away from the start line.
        if value == 0 and pct(idx) not in (0, 1):
            return None
        if pct(idx) == 1 and value == 0:
            return duration
        if pct(idx) == 0 and value == duration:
            return 0.0
        return value

    player_idx = integer(get('PlayerCarIdx', None))
    result = dict(player_car_idx=player_idx, player_position=0, cars=[], gap_is_estimate=True)
    player_pct = pct(player_idx)
    if player_idx is None or player_pct is None:
        return result
    result['player_position'] = integer(at('CarIdxPosition', player_idx)) or 0
    player_period = period(player_idx)
    player_time = coordinate(player_idx, player_period)
    identities = provider._get_driver_metadata()
    for idx in range(len(arrays['CarIdxLapDistPct'])):
        position = integer(at('CarIdxPosition', idx), 1)
        target_pct = pct(idx)
        if idx == player_idx or position is None or target_pct is None:
            continue
        raw_delta = target_pct - player_pct
        physical = raw_delta % 1
        if physical > .5:
            physical -= 1
        target_period = period(idx)
        target_time = coordinate(idx, target_period)
        gap, source = None, None
        if player_time is not None and target_time is not None:
            player_class = integer(roster.get(player_idx, {}).get('CarClassID'))
            target_class = integer(roster.get(idx, {}).get('CarClassID'))
            same_class = player_class is not None and player_class == target_class
            # A same-class profile must have a consistent reference period.
            if not same_class or abs(target_period - player_period) < 1e-6:
                target_coordinate = target_time if same_class else target_time / target_period * player_period
                # Choose the S/F branch from physical progress, never half-time:
                # nonuniform profiles may spend > half a lap's time in < half its distance.
                gap = target_coordinate - player_time + round(physical - raw_delta) * player_period
                if (physical > 0 and gap < 0) or (physical < 0 and gap > 0):
                    gap = None  # inconsistent SDK profile/track coordinates
                else:
                    source = 'sdk_class_profile' if same_class else 'sdk_normalized_class_profile'
        completed = number(at('CarIdxLapCompleted', idx), 0)
        player_completed = number(at('CarIdxLapCompleted', player_idx), 0)
        driver = identities.get(idx, dict(car_number=str(idx), name=f'Car {idx}'))
        result['cars'].append(dict(
            car_idx=idx, position=position,
            class_position=integer(at('CarIdxClassPosition', idx)) or 0,
            car_number=driver['car_number'], name=driver['name'], gap=gap,
            gap_source=source, gap_is_estimate=True, track_delta_pct=physical,
            lap_delta=int(completed - player_completed)
            if completed is not None and player_completed is not None else None,
            on_pit_road=bool(at('CarIdxOnPitRoad', idx))))
    result['cars'].sort(key=lambda car: abs(car['track_delta_pct']))
    result['cars'] = result['cars'][:12]
    return result

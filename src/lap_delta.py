"""F1-style qualifying timer: live delta plus purple/green/yellow sectors.

Sector boundaries come from SessionInfo ``SplitTimeInfo.Sectors`` (the
track's own timing sectors; equal thirds when the SDK gives none).

Every car's sector times are measured the same way: the moment a car's
``CarIdxLapDistPct`` crosses a boundary is linearly interpolated between two
polls on ``SessionTime`` (~30 Hz, so the error is a few milliseconds). That
gives the session-best time for each sector across the whole field, which is
what F1's purple means. A sector is only timed when the car drove all of it
on track (no pit road, no tow/reset, no telemetry gap).

Colours for the player's completed sector, exactly as on F1 timing screens:
  purple  fastest of anyone in the session so far
  green   the player's own personal best
  yellow  slower than the player's personal best
The live delta is iRacing's own ``LapDeltaToBestLap`` (to the player's best
lap this session), which the SDK computes continuously around the lap.
"""
import math

DEFAULT_STARTS = (0.0, 1 / 3, 2 / 3)
RESULT_HOLD_S = 7.0      # how long a finished lap stays on screen
MAX_POLL_GAP_S = 1.0     # longer telemetry gaps void the sector in progress


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _at(values, idx):
    try:
        return values[idx]
    except (IndexError, TypeError, KeyError):
        return None


def sector_starts(split_info):
    """Validated, sorted sector start percentages beginning at 0."""
    sectors = split_info.get('Sectors') if isinstance(split_info, dict) else None
    starts = []
    for sector in sectors if isinstance(sectors, list) else []:
        pct = _num(sector.get('SectorStartPct')) if isinstance(sector, dict) else None
        if pct is not None and 0 <= pct < 1:
            starts.append(round(pct, 6))
    starts = sorted(set(starts))
    if len(starts) < 2 or starts[0] != 0:
        return list(DEFAULT_STARTS)
    return starts


def classify(time_s, personal_best, overall_best):
    if overall_best is None or time_s < overall_best - 1e-6:
        return 'purple'
    if personal_best is None or time_s < personal_best - 1e-6:
        return 'green'
    return 'yellow'


class _Car:
    __slots__ = ('pct', 'time', 'sector', 'start', 'clean')

    def __init__(self):
        self.pct = None
        self.time = None
        self.sector = None
        self.start = None
        self.clean = False


class DeltaTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.session_key = None
        self.starts = list(DEFAULT_STARTS)
        self.cars = {}
        self.overall_sector = []    # best sector time by anyone
        self.personal_sector = []   # player's best sector times
        self.overall_lap = None         # player's tracked laps
        self.overall_lap_others = None  # best lap of every other car (SDK)
        self.personal_lap = None
        self.current = []           # player's current-lap sector results
        self.current_lap = None
        self.lap_dirty = False      # player used pit road / reset this lap
        self.last = None            # finished lap result
        self.last_at = None

    # -- per-car sector timing --------------------------------------------
    def _boundaries(self, p0, p1):
        """Boundary crossings between progress p0 < p1 (p1 may exceed 1)."""
        n = len(self.starts)
        out = []
        for lap in (0, 1):
            for k, start in enumerate(self.starts):
                b = start + lap
                if p0 < b <= p1:
                    out.append((b, k))
        return sorted(out)

    def _advance(self, idx, pct, now, on_pit):
        car = self.cars.setdefault(idx, _Car())
        events = []
        if pct is None:
            self.cars[idx] = _Car()
            return events
        if on_pit:
            car.clean = False
        if car.pct is not None and car.time is not None and 0 < now - car.time <= MAX_POLL_GAP_S:
            p0, p1 = car.pct, pct
            if p1 < p0 - .5:
                p1 += 1                      # crossed the start/finish line
            if p1 < p0 - 1e-6:
                car.sector = None            # went backwards: tow, reset, spin
                car.clean = False
            elif p1 > p0:
                for boundary, k in self._boundaries(p0, p1):
                    t = car.time + (boundary - p0) / (p1 - p0) * (now - car.time)
                    ended = (k - 1) % len(self.starts)
                    timed = car.sector == ended and car.start is not None and car.clean
                    events.append((k, ended, t - car.start if timed else None, t))
                    car.sector, car.start, car.clean = k, t, not on_pit
        else:
            car.sector = None
            car.clean = False
        car.pct, car.time = pct, now
        return events

    # -- main poll -----------------------------------------------------------
    def update(self, provider):
        get = provider._get_sdk_value
        now = _num(get('SessionTime', None))
        session_num = get('SessionNum', None)
        split_info = provider._get_session_dict('SplitTimeInfo')
        if not split_info:
            split_info = (provider._get_session_dict('SessionInfo') or {}).get('SplitTimeInfo') or {}
        starts = sector_starts(split_info)
        key = (session_num, tuple(starts))
        if key != self.session_key or (now is not None and self.cars and
                                       any(c.time is not None and now < c.time - 1 for c in self.cars.values())):
            self.reset()
            self.session_key = key
            self.starts = starts
        n = len(self.starts)
        if len(self.overall_sector) != n:
            self.overall_sector = [None] * n
            self.personal_sector = [None] * n

        player = get('PlayerCarIdx', None)
        player = player if isinstance(player, int) and not isinstance(player, bool) and player >= 0 else None
        pcts = get('CarIdxLapDistPct', None) or []
        pits = get('CarIdxOnPitRoad', None) or []
        surfaces = get('CarIdxTrackSurface', None) or []
        best_laps = get('CarIdxBestLapTime', None) or []

        for idx in range(len(pcts)):
            pct = _num(_at(pcts, idx))
            surface = _num(_at(surfaces, idx))
            if pct is None or pct < 0 or pct > 1 or (surface is not None and surface < 0):
                pct = None
            on_pit = bool(_at(pits, idx))
            if now is None:
                continue
            if idx == player and on_pit:
                self.lap_dirty = True
            for boundary, sector, time_s, at in self._advance(idx, pct, now, on_pit):
                timed = time_s is not None and time_s > 0
                if idx == player:
                    if timed:
                        self._player_sector(sector, time_s, at)
                    if boundary == 0:
                        if self.current:
                            self._finish_lap(at)      # lap with an untimed sector
                        self.current = []
                        self.lap_dirty = on_pit       # still in the pits: next is an out lap
                if timed:
                    best = self.overall_sector[sector]
                    self.overall_sector[sector] = time_s if best is None else min(best, time_s)

        # Overall best lap among everyone else (for the lap-time colour).
        others = [_num(_at(best_laps, i)) for i in range(len(best_laps)) if i != player]
        others = [t for t in others if t and t > 0]
        self.overall_lap_others = min(others) if others else None

        return self._payload(get, player, now)

    def _player_sector(self, sector, time_s, at):
        n = len(self.starts)
        delta = None if self.personal_sector[sector] is None else time_s - self.personal_sector[sector]
        state = 'out' if self.lap_dirty else classify(time_s, self.personal_sector[sector],
                                                      self.overall_sector[sector])
        self.current.append({'index': sector, 'time_s': round(time_s, 3), 'state': state,
                             'delta_pb_s': None if delta is None else round(delta, 3)})
        if not self.lap_dirty:
            pb = self.personal_sector[sector]
            self.personal_sector[sector] = time_s if pb is None else min(pb, time_s)
        if sector == n - 1:
            self._finish_lap(at)

    def _finish_lap(self, at):
        n = len(self.starts)
        sectors = self.current
        complete = len(sectors) == n and [s['index'] for s in sectors] == list(range(n))
        lap_time = sum(s['time_s'] for s in sectors) if complete else None
        state = None
        delta = None
        if lap_time is not None and not self.lap_dirty:
            known = [t for t in (self.overall_lap, self.overall_lap_others) if t]
            overall = min(known) if known else None
            state = classify(lap_time, self.personal_lap, overall)
            delta = None if self.personal_lap is None else round(lap_time - self.personal_lap, 3)
            self.personal_lap = lap_time if self.personal_lap is None else min(self.personal_lap, lap_time)
            self.overall_lap = lap_time if self.overall_lap is None else min(self.overall_lap, lap_time)
        self.last = {'time_s': None if lap_time is None else round(lap_time, 3),
                     'state': 'out' if self.lap_dirty else state, 'delta_pb_s': delta,
                     'sectors': sectors}
        self.last_at = at
        self.current = []
        self.lap_dirty = False

    def _payload(self, get, player, now):
        pcts = get('CarIdxLapDistPct', None) or []
        pct = _num(_at(pcts, player)) if player is not None else None
        lap_time = _num(get('LapCurrentLapTime', None))
        delta = _num(get('LapDeltaToBestLap', None))
        delta_ok = get('LapDeltaToBestLap_OK', None)
        current_sector = None
        if pct is not None and 0 <= pct <= 1:
            current_sector = max(i for i, s in enumerate(self.starts) if pct >= s)
        best_lap = _num(get('LapBestLapTime', None))
        age = None if self.last_at is None or now is None else max(0.0, now - self.last_at)
        return {
            'available': player is not None and pct is not None and pct >= 0,
            'lap': get('Lap', None) if isinstance(get('Lap', None), int) else None,
            'lap_time_s': lap_time if lap_time is not None and lap_time >= 0 else None,
            'lap_dist_pct': pct if pct is not None and 0 <= pct <= 1 else None,
            'sector_starts': self.starts,
            'current_sector': current_sector,
            'current': self.current,
            'last': self.last,
            'last_age_s': None if age is None else round(age, 3),
            'result_hold_s': RESULT_HOLD_S,
            'best_lap_s': best_lap if best_lap and best_lap > 0 else self.personal_lap,
            'delta_s': delta if delta is not None and delta_ok is True else None,
            'delta_ref': 'personal_best',
            'out_lap': self.lap_dirty,
            'personal_sector_s': [None if t is None else round(t, 3) for t in self.personal_sector],
            'overall_sector_s': [None if t is None else round(t, 3) for t in self.overall_sector],
        }

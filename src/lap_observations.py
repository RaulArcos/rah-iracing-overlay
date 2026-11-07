"""Additive completion observations; the provider owns every lap boundary."""
import math


def finite(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def counter(value):
    value = finite(value)
    return int(value) if value is not None and value >= 0 and value.is_integer() else None


class LapObservations:
    def __init__(self):
        self.records = []
        self.last_count = None
        self.known = False
        self.changed = False

    def begin(self, read, full=False):
        self.last_count = counter(read('PlayerCarMyIncidentCount', None))
        self.known = full and self.last_count is not None
        self.changed = False

    def poll(self, read):
        count = counter(read('PlayerCarMyIncidentCount', None))
        if count is None or self.last_count is None or count < self.last_count:
            self.known = False
        elif count > self.last_count:
            self.changed = True
        self.last_count = count

    def missing(self):
        self.known = False

    def close(self, read, consecutive, time_s):
        # The completion poll belongs to the closing lap, before re-baselining.
        self.poll(read)
        if time_s is not None:
            self.records.append(dict(
                lap_number=counter(read('LapCompleted', None)) if consecutive else None,
                time_s=round(time_s, 3),
                track_temp_c=finite(read('TrackTempCrew', None)) if consecutive else None,
                incident=self.changed if consecutive and self.known else None,
                observation='observed' if consecutive else 'unavailable'))
            del self.records[:-10]
        self.begin(read, full=True)


def recent_deltas(theirs, mine):
    """Latest observed lap vs latest, not matching race lap numbers or sectors."""
    size = max(len(theirs), len(mine))
    a = [None] * (size - len(theirs)) + theirs
    b = [None] * (size - len(mine)) + mine
    return [round(x-y, 3) if x is not None and y is not None else None
            for x, y in zip(a, b)]

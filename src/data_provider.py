import irsdk
import logging
import math
import os
import re
import yaml
from typing import Any, Dict, List, Optional, Union

# Recognized WeekendInfo.TrackLength formats, e.g. "5.891 km" or "2.5 miles".
_TRACK_LENGTH_RE = re.compile(
    r'^([0-9]*\.?[0-9]+)\s*(km|kilometers?|kilometres?|m|meters?|metres?|mi|miles?)$'
)

# SessionInfo limits are "unlimited" or a number; "<seconds>.<fraction> sec" for time.
_SESSION_TIME_RE = re.compile(r'^([0-9]*\.?[0-9]+)\s*(?:sec|s)?$')

# SessionLapsRemain[Ex] reports values >= 32000 (32767 in practice) when the
# session has no lap limit; the pre-existing driver-in-front logic already
# treats the same range as "unlimited".
_LAPS_UNLIMITED_FROM = 32000
# SessionTimeRemain reports one week in seconds when the session has no time
# limit. This heuristic only matters when SessionInfo metadata is missing.
_TIME_UNLIMITED_FROM_S = 604800.0

# A fuel level that climbs more than sensor noise above its running minimum
# is a refuel (pit service, tow or reset), never fuel burn. Measuring from
# the running minimum catches slow pit-flow refuelling that no single poll
# would reveal, while jitter below this amplitude never accumulates.
_REFUEL_RISE_L = 0.1
_FUEL_SAMPLE_WINDOW = 10

# CarIdxF2Time is read as seconds behind the leader only while a race is
# actually running (SessionInfo says Race and the state is one of these).
_RACE_TIMING_STATES = ('racing', 'checkered')

# Observed consecutive completed laps kept per car for pace and trend: a
# pace needs two laps, a trend three. A fitted slope inside the steady band
# (seconds per lap) is not called improving or worsening.
_PACE_WINDOW = 5
_PACE_MIN_LAPS = 2
_TREND_MIN_LAPS = 3
_TREND_STEADY_S = 0.05


def _enum_names(enum_class: Any) -> Dict[int, str]:
    """Map the integer members of an irsdk enum class to their names."""
    return {value: name for name, value in vars(enum_class).items()
            if isinstance(value, int) and not isinstance(value, bool) and not name.startswith('_')}


# Decoded only from the installed irsdk enums; unknown values stay unknown.
_SESSION_STATE_NAMES = {
    code: name for code, name in _enum_names(getattr(irsdk, 'SessionState', object)).items() if code != 0}
_SESSION_FLAG_NAMES = _enum_names(getattr(irsdk, 'Flags', object))
_PIT_SERVICE_FLAG_NAMES = _enum_names(getattr(irsdk, 'PitSvFlags', object))
_PIT_SERVICE_STATUS_NAMES = _enum_names(getattr(irsdk, 'PitSvStatus', object))
_TRACK_WETNESS_NAMES = _enum_names(getattr(irsdk, 'TrackWetness', object))

# WeekendInfo.TrackPitSpeedLimit is a string such as "60.00 kph" (typed string
# in IRSDKSharper IRacingSdkSessionInfo.cs). Only a value that states its own
# unit is trusted; the factor converts that unit to km/h.
_PIT_LIMIT_RE = re.compile(r'^([0-9]*\.?[0-9]+)\s*(kph|km/h|mph|m/s)$', re.IGNORECASE)
_TO_KMH = {'kph': 1.0, 'km/h': 1.0, 'mph': 1.609344, 'm/s': 3.6}

# Per-car SDK arrays the Broadcast Driver Card reads for the camera-followed car.
_BROADCAST_ARRAYS = ('CarIdxPosition', 'CarIdxClassPosition', 'CarIdxLapCompleted',
                     'CarIdxLastLapTime', 'CarIdxBestLapTime', 'CarIdxOnPitRoad')


class DataProvider:
    """
    Provides telemetry data from iRacing.
    
    This class manages the connection to the iRacing SDK and handles
    retrieval of telemetry data and lap times for overlays.
    """

    def __init__(self) -> None:
        """
        Initialize the DataProvider with default values.
        """
        self.ir_sdk = irsdk.IRSDK()
        self.is_connected = False
        self.lap_times: List[float] = []
        self._lap_tracking_session: Optional[int] = None
        self._last_lap_seen: Optional[int] = None
        self._reset_fuel_sampling()
        self._reset_pace_tracking()
        logging.debug(f"DataProvider initialized. Current working directory: {os.getcwd()}")

    def connect(self) -> bool:
        """
        Establish connection to iRacing.
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        if not self.is_connected:
            self.is_connected = self.ir_sdk.startup()
            if self.is_connected:
                # Completed-lap history does not survive a (re)connect.
                self._reset_lap_tracking()
                logging.info("Connected to iRacing")
            else:
                logging.warning("Failed to connect to iRacing")
        return self.is_connected

    def disconnect(self) -> None:
        """
        Disconnect from iRacing and clean up resources.
        """
        if self.is_connected:
            self.ir_sdk.shutdown()
            self.is_connected = False
            logging.info("Disconnected from iRacing")

    def get_telemetry_data(self) -> Dict[str, Any]:
        """
        Retrieve telemetry data from iRacing.
        
        Returns:
            Dict[str, Union[float, int]]: Dictionary containing telemetry values
                or empty dict if not connected or error occurs
        """
        if not self.is_connected:
            logging.debug("Not connected to iRacing")
            return {}
            
        try:
            self.ir_sdk.freeze_var_buffer_latest()
            return self._extract_data()
        except (TypeError, ValueError, KeyError) as e:
            logging.error(f"Error processing telemetry data: {e}")
            return self._get_default_telemetry()
        except Exception as e:
            logging.error(f"Unexpected error in get_telemetry_data: {e}")
            return {}
    
    def _extract_data(self) -> Dict[str, Any]:
        """
        Returns one dict that contains both the "live telemetry" numbers
        you were already broadcasting **and** the extra overlay metrics
        (front lap/best time, lap_delta, target pace or best‑gap).

        Keys that are *unused* for a particular session type are present
        with value 0.0, so the websocket payload is always predictable.
        """

        speed_kmh = self._safe_float(self.ir_sdk['Speed'] or 0.0) * 3.6
        gear      = self._safe_int(self.ir_sdk['Gear'] or 0)
        throttle  = self._safe_float(self.ir_sdk['Throttle'] or 0.0)
        brake     = self._safe_float(self.ir_sdk['Brake'] or 0.0)

        clutch_raw = self.ir_sdk['Clutch']       
        clutch     = 1.0 - self._safe_float(clutch_raw, 0.0) if clutch_raw is not None else 1.0

        steering = self._safe_float(self.ir_sdk['SteeringWheelAngle'] or 0.0)

        base = {
            "speed": speed_kmh,
            "gear": gear,
            "throttle": throttle,
            "brake": brake,
            "clutch": clutch,
            "steering_wheel_angle": steering,
        }
        
        data = {
            **base,
            **self._compute_overlay_metrics(),
            "relative_data": self._build_relative_data(),
            "track_map_data": self._build_track_map_data(),
            "radar_data": self._build_radar_data(),
            "blindspot_data": self._build_blindspot_data(),
            "laptime_graph_data": self._build_laptime_graph_data(),
            # Built after the lap graph: lap tracking (and with it fuel
            # sampling) advances inside _build_laptime_graph_data.
            "fuel_finish_data": self._build_fuel_finish_data(),
            "session_strip_data": self._build_session_strip_data(),
            "pit_assistant_data": self._build_pit_assistant_data(),
            "weather_data": self._build_weather_data(),
        }
        # Last: opponent lap observation must follow any lap-tracking reset
        # triggered while the player's lap graph was built above.
        data.update(self._build_race_overlay_data())
        data['broadcast_driver_data'] = self._build_broadcast_driver_data()
        return data

    def _get_sdk_value(self, key: str, default: Any) -> Any:
        try:
            value = self.ir_sdk[key]
            if value is None:
                return default
            return value
        except Exception:
            return default

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            try:
                result = float(value)
            except ValueError:
                return default
        else:
            return default
        return result if math.isfinite(result) else default

    def _safe_int(self, value: Any, default: int = 0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            try:
                return int(value)
            except (ValueError, OverflowError):
                return default
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def _safe_list(self, value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    def _finite_or_none(self, value: Any) -> Optional[float]:
        """Return value as a finite float, or None when missing/non-finite."""
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _get_session_dict(self, key: str) -> Dict[str, Any]:
        """Return an SDK session-info section as a dict, whatever its form.

        irsdk exposes sections like DriverInfo and WeekendInfo as parsed
        top-level dicts; YAML strings and missing sections are tolerated.
        """
        raw = self._get_sdk_value(key, None)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _decode_car_left_right(self, value: Any) -> tuple:
        """Decode irsdk.CarLeftRight into (left_alert, right_alert).

        Enum: 0 off, 1 clear, 2 car left, 3 car right, 4 cars each side,
        5 two cars left, 6 two cars right. Values are not bit flags.
        """
        state = self._safe_int(value, 0)
        left = state in (2, 4, 5)
        right = state in (3, 4, 6)
        return left, right

    def _get_driver_metadata(self) -> Dict[int, Dict[str, Any]]:
        metadata: Dict[int, Dict[str, Any]] = {}
        try:
            # irsdk exposes DriverInfo as a top-level parsed section next to
            # SessionInfo (which only holds the Sessions list). The nested
            # lookup below stays as a compatibility fallback for payloads
            # that embed DriverInfo inside SessionInfo.
            driver_info = self._get_session_dict('DriverInfo')
            if not driver_info:
                driver_info = self._get_session_dict('SessionInfo').get('DriverInfo') or {}
            drivers = driver_info.get('Drivers') or []
            if not isinstance(drivers, list):
                return {}
            for driver in drivers:
                if not isinstance(driver, dict):
                    continue
                car_idx = int(driver.get('CarIdx', -1))
                if car_idx < 0:
                    continue
                metadata[car_idx] = {
                    'car_number': str(driver.get('CarNumber', car_idx)),
                    'name': str(driver.get('UserName', f'Car {car_idx}')),
                }
        except Exception:
            return {}
        return metadata

    def _build_relative_data(self) -> Dict[str, Any]:
        player_idx = int(self._get_sdk_value('PlayerCarIdx', 0) or 0)
        positions = self._safe_list(self._get_sdk_value('CarIdxPosition', []))
        class_positions = self._safe_list(self._get_sdk_value('CarIdxClassPosition', []))
        lap_pct = self._safe_list(self._get_sdk_value('CarIdxLapDistPct', []))
        laps_completed = self._safe_list(self._get_sdk_value('CarIdxLapCompleted', []))
        on_pit_road = self._safe_list(self._get_sdk_value('CarIdxOnPitRoad', []))
        player_best = self._finite_or_none(self._get_sdk_value('LapBestLapTime', 90.0))
        base_lap_time = max(player_best if player_best and player_best > 0 else 90.0, 60.0)
        drivers = self._get_driver_metadata()

        player_pct = self._finite_or_none(lap_pct[player_idx]) if player_idx < len(lap_pct) else None
        player_completed = (self._finite_or_none(laps_completed[player_idx])
                            if player_idx < len(laps_completed) else None)
        if player_pct is None or player_completed is None:
            return {'player_car_idx': player_idx, 'player_position': 0,
                    'cars': [], 'gap_is_estimate': True}

        player_progress = player_completed + player_pct
        entries: List[Dict[str, Any]] = []

        for idx, pct in enumerate(lap_pct):
            if idx == player_idx:
                continue
            if idx >= len(positions) or not positions[idx] or positions[idx] <= 0:
                continue

            target_pct = self._finite_or_none(pct)
            target_completed = (self._finite_or_none(laps_completed[idx])
                                if idx < len(laps_completed) else None)
            if target_pct is None or target_completed is None:
                continue  # invalid car: no usable position on track

            # Wrap the full progress difference into (-0.5, 0.5] of a lap so
            # lapped cars (differences beyond one lap) compare on-track
            # proximity instead of a bogus unwrapped delta.
            progress_delta = (target_completed + target_pct - player_progress) % 1.0
            if progress_delta > 0.5:
                progress_delta -= 1.0

            gap_seconds = progress_delta * base_lap_time
            lap_delta = int(target_completed - player_completed)
            driver = drivers.get(idx, {'car_number': str(idx), 'name': f'Car {idx}'})

            entries.append({
                'car_idx': idx,
                'position': int(positions[idx]),
                'class_position': int((class_positions[idx] if idx < len(class_positions) else 0) or 0),
                'car_number': driver['car_number'],
                'name': driver['name'],
                # Progress-based gap: an estimate from lap distance and the
                # player's best lap time, never a measured time interval.
                'gap': round(gap_seconds, 3),
                'gap_is_estimate': True,
                'lap_delta': lap_delta,
                'on_pit_road': bool((on_pit_road[idx] if idx < len(on_pit_road) else False) or False),
            })

        entries.sort(key=lambda item: abs(item['gap']))
        player_position = int((positions[player_idx] if player_idx < len(positions) else 0) or 0)

        return {
            'player_car_idx': player_idx,
            'player_position': player_position,
            'cars': entries[:12],
            'gap_is_estimate': True,
        }

    def _build_track_map_data(self) -> Dict[str, Any]:
        player_idx = int(self._get_sdk_value('PlayerCarIdx', 0) or 0)
        lap_pct = self._get_sdk_value('CarIdxLapDistPct', []) or []
        positions = self._get_sdk_value('CarIdxPosition', []) or []
        class_positions = self._get_sdk_value('CarIdxClassPosition', []) or []
        track_surface = self._get_sdk_value('CarIdxTrackSurface', []) or []
        on_pit_road = self._get_sdk_value('CarIdxOnPitRoad', []) or []

        cars: List[Dict[str, Any]] = []
        for idx, pct in enumerate(lap_pct):
            surface_raw = track_surface[idx] if idx < len(track_surface) else -1
            surface = int(self._finite_or_none(surface_raw) or -1)
            if surface < 0:
                continue
            cars.append({
                'car_idx': idx,
                'lap_dist_pct': self._finite_or_none(pct) or 0.0,
                'position': self._safe_int(positions[idx] if idx < len(positions) else 0, 0),
                'class_position': self._safe_int(class_positions[idx] if idx < len(class_positions) else 0, 0),
                'is_player': idx == player_idx,
                'on_pit_road': bool((on_pit_road[idx] if idx < len(on_pit_road) else False) or False),
                'track_surface': surface,
            })

        player_pct_raw = lap_pct[player_idx] if player_idx < len(lap_pct) else 0.0
        player_pct = self._finite_or_none(player_pct_raw) or 0.0
        return {
            'player_car_idx': player_idx,
            'player_lap_dist_pct': player_pct,
            'cars': cars,
        }

    def _build_radar_data(self) -> Dict[str, Any]:
        player_idx = int(self._get_sdk_value('PlayerCarIdx', 0) or 0)
        lap_pct = self._safe_list(self._get_sdk_value('CarIdxLapDistPct', []))
        laps_completed = self._safe_list(self._get_sdk_value('CarIdxLapCompleted', []))
        left_alert, right_alert = self._decode_car_left_right(self._get_sdk_value('CarLeftRight', 0))
        track_length_m = self._get_track_length_m()

        player_pct = self._finite_or_none(lap_pct[player_idx]) if player_idx < len(lap_pct) else None
        player_completed = (self._finite_or_none(laps_completed[player_idx])
                            if player_idx < len(laps_completed) else None)

        nearby: List[Dict[str, Any]] = []
        if player_pct is not None and player_completed is not None:
            player_progress = player_completed + player_pct
            for idx, pct in enumerate(lap_pct):
                if idx == player_idx:
                    continue
                target_pct = self._finite_or_none(pct)
                target_completed = (self._finite_or_none(laps_completed[idx])
                                    if idx < len(laps_completed) else None)
                if target_pct is None or target_completed is None:
                    continue

                progress_delta = (target_completed + target_pct - player_progress) % 1.0
                if progress_delta > 0.5:
                    progress_delta -= 1.0

                if abs(progress_delta) <= 0.035:
                    nearby.append({
                        'car_idx': idx,
                        'distance_pct': round(progress_delta, 4),
                        'relation': 'ahead' if progress_delta > 0 else 'behind',
                    })

        return {
            'left_alert': left_alert,
            'right_alert': right_alert,
            'both_alert': left_alert and right_alert,
            'nearby': nearby,
            'track_length_m': track_length_m,
        }

    def _get_track_length_m(self) -> Optional[float]:
        """Derive the track length in meters from WeekendInfo.TrackLength.

        Returns None when the value is missing, non-numeric, unitless, or
        non-positive; overlays must never invent a length.
        """
        weekend_info = self._get_session_dict('WeekendInfo')
        raw = weekend_info.get('TrackLength') if isinstance(weekend_info, dict) else None
        if not isinstance(raw, str):
            return None
        match = _TRACK_LENGTH_RE.match(raw.strip().lower().replace(',', ''))
        if not match:
            return None
        value = float(match.group(1))
        if not math.isfinite(value) or value <= 0:
            return None
        unit = match.group(2)
        if unit.startswith('k'):
            meters = value * 1000.0
        elif unit.startswith('mi'):
            meters = value * 1609.344
        else:
            meters = value
        return round(meters, 3)

    def _build_blindspot_data(self) -> Dict[str, Any]:
        left_alert, right_alert = self._decode_car_left_right(self._get_sdk_value('CarLeftRight', 0))

        message = 'CLEAR'
        if left_alert and right_alert:
            message = 'CARS BOTH SIDES'
        elif left_alert:
            message = 'CAR LEFT'
        elif right_alert:
            message = 'CAR RIGHT'

        return {
            'left_alert': left_alert,
            'right_alert': right_alert,
            'both_alert': left_alert and right_alert,
            'active': left_alert or right_alert,
            'message': message,
        }

    def _build_laptime_graph_data(self) -> Dict[str, Any]:
        lap_history = [round(float(value), 3) for value in self.get_lap_times() if isinstance(value, (int, float)) and value > 0]
        best_lap = self._finite_or_none(self._get_sdk_value('LapBestLapTime', 0.0)) or 0.0
        last_lap = self._finite_or_none(self._get_sdk_value('LapLastLapTime', 0.0)) or 0.0
        current_lap = self._finite_or_none(self._get_sdk_value('LapCurrentLapTime', 0.0)) or 0.0
        delta_to_best = self._finite_or_none(self._get_sdk_value('LapDeltaToBestLap', 0.0)) or 0.0
        delta_valid = bool(self._get_sdk_value('LapDeltaToBestLap_OK', False) or False)

        return {
            'history': lap_history[-30:],
            'best_lap_time': round(best_lap, 3),
            'last_lap_time': round(last_lap, 3),
            'current_lap_time': round(current_lap, 3),
            'delta_to_best': round(delta_to_best, 3),
            'delta_valid': delta_valid,
        }

    def _compute_overlay_metrics(self) -> Dict[str, Any]:
        """
        Pulls together:
        • front_last_lap_time / front_best_lap_time
        • lap_delta
        • target_pace  (race)   OR   best‑lap delta  (practice/qualy)
        Always returns the three fields so the client has a fixed schema.
        """

        me_idx = self._safe_int(self.ir_sdk['PlayerCarIdx'])
        my_last = self._safe_float(self.ir_sdk['LapLastLapTime'] or -1.0, -1.0)
        car_best_laps = self._safe_list(self.ir_sdk['CarIdxBestLapTime'])
        my_best = self._safe_float(car_best_laps[me_idx] if me_idx < len(car_best_laps) else -1.0, -1.0)

        if my_last <= 0.0:
            return self._default_front_data()   # we haven't set a lap yet

        session_type = self._current_session_type().lower()

        if session_type == 'race':
            est = self._safe_list(self.ir_sdk['CarIdxEstTime'])
            if not est:
                return self._default_front_data()

            front_idx, gap_sec = None, None
            for idx, g in enumerate(est):
                if g and g > 0 and (gap_sec is None or g < gap_sec):
                    front_idx, gap_sec = idx, g

            if front_idx is None:
                return self._default_front_data()

            car_last_laps = self._safe_list(self.ir_sdk['CarIdxLastLapTime'])
            front_last = self._safe_float(car_last_laps[front_idx] if front_idx < len(car_last_laps) else -1.0, -1.0)
            if front_last <= 0.0:
                return self._default_front_data()

            lap_delta = front_last - my_last

            sess_laps_remain = self._safe_int(self.ir_sdk['SessionLapsRemain'])
            if 0 < sess_laps_remain < 32000:
                laps_left = max(sess_laps_remain, 1)
            else:
                secs_left = self._safe_float(self.ir_sdk['SessionTimeRemain'])
                laps_left = max(int(secs_left / max(my_last, 1e-9)), 1)

            target_pace = my_last - (gap_sec / laps_left) * 1.10

            return {
                "front_last_lap_time": round(front_last, 3),
                "lap_delta":           round(lap_delta, 3),
                "target_pace":         round(max(target_pace, 0.0), 3),
                "session_type":        session_type,
            }

        best_array = self._safe_list(self.ir_sdk['CarIdxBestLapTime'])
        if not best_array:
            return self._default_front_data()

        standings = sorted(
            [(idx, t) for idx, t in enumerate(best_array) if t and t > 0],
            key=lambda x: x[1]
        )

        my_pos = next((i for i, (idx, _) in enumerate(standings) if idx == me_idx), None)
        if my_pos is None or my_pos == 0:
            return self._default_front_data()   

        front_idx, front_best = standings[my_pos - 1]
        best_delta = my_best - front_best
        
        car_last_laps = self._safe_list(self.ir_sdk['CarIdxLastLapTime'])
        front_last = self._safe_float(car_last_laps[front_idx] if front_idx < len(car_last_laps) else -1.0, -1.0)
        lap_delta  = (front_last - my_last) if front_last > 0 else 0.0

        return {
            "front_best_lap_time": round(front_best, 3),
            "target_pace":          round(lap_delta, 3),
            "lap_delta":         round(best_delta, 3),
            "session_type":        "practice",
        }

    
    def _current_session_type(self) -> str:
        """
        Return the current session type ('Race', 'Qualify', 'Practice', …).

        Works whether irsdk delivers SessionInfo as:
        • a YAML string  **or**
        • an already‑parsed dict
        """
        try:
            sess_num = self._safe_int(self.ir_sdk['SessionNum'])

            raw = self.ir_sdk['SessionInfo']
            # iRacing 2024.4+ may give us a dict already
            if isinstance(raw, dict):
                info = raw
            else:
                info = yaml.safe_load(raw if isinstance(raw, str) else "") or {}

            for sess in info.get('Sessions', []):
                if int(sess.get('SessionNum', -1)) == sess_num:
                    return str(sess.get('SessionType', 'Race'))
        except Exception as e:
            logging.debug(f"Could not parse SessionInfo: {e}")

        # default so the overlay logic still works
        return 'Race'
    
    def _default_front_data(self) -> Dict[str, float]:
        """Return zeroed values when we can't compute the real ones."""
        return {"front_last_lap_time": 0.0, "lap_delta": 0.0, "target_pace": 0.0}
    
    def _get_default_telemetry(self) -> Dict[str, Union[float, int]]:
        """
        Provide default telemetry values when data cannot be retrieved.
        
        Returns:
            Dict[str, Union[float, int]]: Default telemetry values
        """
        return {
            'speed': 0.0,
            'gear': 0,
            'throttle': 0.0,
            'brake': 0.0,
            'clutch': 1.0,
            'steering_wheel_angle': 0.0
        }
    
    def get_lap_times(self) -> List[float]:
        """
        Retrieve the last 10 lap times from iRacing.
        
        Updates internal lap times list and returns all stored times.
        
        Returns:
            List[float]: List of up to 10 most recent lap times or empty list if not connected
        """
        if not self.is_connected:
            logging.debug("Not connected to iRacing")
            return []
        
        try:
            self._update_lap_times()
            return self.lap_times
        except (TypeError, ValueError, KeyError) as e:
            logging.error(f"Error processing lap times: {e}")
            return self.lap_times
        except Exception as e:
            logging.error(f"Unexpected error in get_lap_times: {e}")
            return []
    
    def _reset_lap_tracking(self) -> None:
        """Clear completed-lap history and forget the tracking baseline."""
        self.lap_times = []
        self._lap_tracking_session = None
        self._last_lap_seen = None
        self._reset_fuel_sampling()
        self._reset_pace_tracking()


    def _update_lap_times(self) -> None:
        """Record LapLastLapTime on actual completed-lap transitions.

        Rejects startup partial laps (the first observation only sets a
        baseline), duplicate samples of the same lap, and invalid lap times
        (zero, negative, or non-finite). History resets on session change,
        reconnect, and lap rollback, and is capped at the last 10 laps.

        Fuel burn sampling (see _fuel_*) rides on the same lap detector so
        the two can never disagree about where a lap starts and ends.
        """
        current_lap = self._get_sdk_value('Lap', None)
        if not isinstance(current_lap, (int, float)) or isinstance(current_lap, bool):
            self._fuel_guard(self._fuel_poll_in_lap)
            return
        current_lap = int(current_lap)

        session_num = self._safe_int(self._get_sdk_value('SessionNum', 0))
        if self._lap_tracking_session is None or session_num != self._lap_tracking_session:
            # First observation after (re)connect or a new session: baseline
            # only, so laps completed before we started watching are never
            # recorded as partial samples.
            self._reset_lap_tracking()
            self._lap_tracking_session = session_num
            self._last_lap_seen = current_lap
            self._fuel_guard(self._fuel_begin_lap, False)
            return

        if current_lap < self._last_lap_seen:
            # Lap rollback (session restart): history from the abandoned
            # run is no longer valid.
            self._reset_lap_tracking()
            self._lap_tracking_session = session_num
            self._last_lap_seen = current_lap
            self._fuel_guard(self._fuel_begin_lap, False)
            return

        if current_lap <= self._last_lap_seen:
            self._fuel_guard(self._fuel_poll_in_lap)
            return  # duplicate sample of the current lap

        # At least one lap completed since the last poll. LapLastLapTime
        # holds only the most recently completed lap, so record it once and
        # re-baseline; skipped laps cannot be recovered and are never
        # fabricated.
        last_lap_time = self._finite_or_none(self._get_sdk_value('LapLastLapTime', None))
        valid_lap_time = last_lap_time is not None and last_lap_time > 0
        if valid_lap_time:
            self.lap_times.append(round(last_lap_time, 3))
            if len(self.lap_times) > 10:
                self.lap_times.pop(0)
        self._fuel_guard(self._fuel_close_lap,
                         current_lap == self._last_lap_seen + 1,
                         last_lap_time if valid_lap_time else None)
        self._last_lap_seen = current_lap

    # ------------------------------------------------------------------
    # Fuel burn sampling
    #
    # A burn sample is the fuel used between two observed lap boundaries and
    # is kept only when every poll of that lap was clean: valid fuel readings,
    # no refuel, not on pit road or in a stall, on track and not in replay.
    # Everything here is advisory input; failures reset sampling and never
    # disturb the lap history above.
    # ------------------------------------------------------------------

    def _reset_fuel_sampling(self) -> None:
        # (burn litres, lap seconds) of the most recent clean laps.
        self._fuel_samples: List[tuple] = []
        # Fuel at the observed start of the current lap; None when the lap
        # did not start on an observed boundary (startup, skipped polls).
        self._fuel_lap_start_level: Optional[float] = None
        self._fuel_lap_clean = False
        # Lowest fuel level seen since the last refuel/reset.
        self._fuel_floor: Optional[float] = None

    def _fuel_guard(self, step: Any, *args: Any) -> None:
        try:
            step(*args)
        except Exception as e:
            logging.debug(f"Fuel sampling reset after error: {e}")
            self._reset_fuel_sampling()

    def _valid_fuel_level(self, value: Any) -> Optional[float]:
        """Finite non-negative number, else None. Zero is a real value."""
        if isinstance(value, bool):
            return None
        number = self._finite_or_none(value)
        return number if number is not None and number >= 0 else None

    def _fuel_driving_state_ok(self) -> bool:
        """Conservative guard over whichever driving-state fields exist."""
        for key in ('OnPitRoad', 'PlayerCarInPitStall', 'IsReplayPlaying'):
            if self._get_sdk_value(key, None):
                return False
        on_track = self._get_sdk_value('IsOnTrack', None)
        return on_track is None or bool(on_track)

    def _fuel_observe_poll(self) -> tuple:
        """Read this poll: (fuel level or None, poll is clean).

        A refuel at any poll (a rise above the running minimum, however
        gradual) also discards every earlier burn sample so an old stint
        average cannot mislead the new one.
        """
        level = self._valid_fuel_level(self._get_sdk_value('FuelLevel', None))
        refueled = False
        if level is not None:
            floor = self._fuel_floor
            if floor is not None and level - floor > _REFUEL_RISE_L:
                refueled = True
                self._fuel_samples = []
                floor = None
            self._fuel_floor = level if floor is None else min(floor, level)
        clean = level is not None and not refueled and self._fuel_driving_state_ok()
        return level, clean

    def _fuel_poll_in_lap(self) -> None:
        _, clean = self._fuel_observe_poll()
        if not clean:
            self._fuel_lap_clean = False

    def _fuel_begin_lap(self, on_boundary: bool) -> None:
        level, clean = self._fuel_observe_poll()
        self._fuel_lap_start_level = level if on_boundary else None
        self._fuel_lap_clean = clean

    def _fuel_close_lap(self, consecutive: bool, lap_time: Optional[float]) -> None:
        """Finish the lap that just ended and start the next one."""
        level, clean = self._fuel_observe_poll()
        start = self._fuel_lap_start_level
        if (consecutive and lap_time is not None and clean and self._fuel_lap_clean
                and start is not None and level is not None):
            burn = start - level
            if math.isfinite(burn) and burn > 0:
                self._fuel_samples.append((burn, lap_time))
                del self._fuel_samples[:-_FUEL_SAMPLE_WINDOW]
        self._fuel_lap_start_level = level if consecutive else None
        self._fuel_lap_clean = clean

    # ------------------------------------------------------------------
    # Session progress (shared by the session strip and the finish estimate)
    # ------------------------------------------------------------------

    def _strict_int(self, value: Any) -> Optional[int]:
        """An integral finite number as int; bools, strings and NaN are None."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        return None

    def _get_session_entry(self) -> Optional[Dict[str, Any]]:
        """SessionInfo.Sessions entry for the current SessionNum, if known."""
        session_num = self._strict_int(self._get_sdk_value('SessionNum', None))
        if session_num is None:
            return None
        sessions = self._get_session_dict('SessionInfo').get('Sessions')
        if not isinstance(sessions, list):
            return None
        for session in sessions:
            if isinstance(session, dict) and self._strict_int(session.get('SessionNum')) == session_num:
                return session
        return None

    def _parse_laps_limit(self, raw: Any) -> tuple:
        """SessionLaps metadata -> ('unlimited'|'limited'|None, laps or None)."""
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text == 'unlimited':
                return 'unlimited', None
            raw = int(text) if text.isdigit() else None
        laps = self._strict_int(raw)
        if laps is not None and laps > 0:
            return 'limited', laps
        return None, None

    def _parse_time_limit(self, raw: Any) -> tuple:
        """SessionTime metadata -> ('unlimited'|'limited'|None, seconds or None)."""
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text == 'unlimited':
                return 'unlimited', None
            match = _SESSION_TIME_RE.match(text)
            raw = float(match.group(1)) if match else None
        seconds = None if isinstance(raw, bool) else self._finite_or_none(raw)
        if seconds is not None and seconds > 0:
            return 'limited', seconds
        return None, None

    def _read_laps_remaining(self, laps_state: Optional[str]) -> tuple:
        """(laps, source key). Prefers SessionLapsRemainEx; the legacy field
        is only a fallback when the extended one is absent. 0 is a confirmed
        finish; sentinels, negatives and NaN are unavailable."""
        if laps_state == 'unlimited':
            return None, None
        for key in ('SessionLapsRemainEx', 'SessionLapsRemain'):
            raw = self._get_sdk_value(key, None)
            if raw is None:
                continue
            laps = self._strict_int(raw)
            if laps is None or not 0 <= laps < _LAPS_UNLIMITED_FROM:
                return None, None
            return laps, key
        return None, None

    def _read_time_remaining(self, time_state: Optional[str]) -> Optional[float]:
        if time_state == 'unlimited':
            return None
        raw = self._get_sdk_value('SessionTimeRemain', None)
        seconds = None if isinstance(raw, bool) else self._finite_or_none(raw)
        if seconds is None or not 0 <= seconds < _TIME_UNLIMITED_FROM_S:
            return None
        return round(seconds, 3)

    def _get_session_progress(self) -> Dict[str, Any]:
        entry = self._get_session_entry() or {}
        laps_state, laps_total = self._parse_laps_limit(entry.get('SessionLaps'))
        time_state, time_total = self._parse_time_limit(entry.get('SessionTime'))
        if laps_state == 'unlimited' and time_state == 'unlimited':
            limit = 'unlimited'
        elif laps_state == 'limited' and time_state == 'limited':
            limit = 'laps_and_time'
        elif laps_state == 'limited' and time_state == 'unlimited':
            limit = 'laps'
        elif laps_state == 'unlimited' and time_state == 'limited':
            limit = 'time'
        else:
            limit = None
        laps_remaining, laps_source = self._read_laps_remaining(laps_state)
        session_type = entry.get('SessionType')
        return {
            'session_type': session_type if isinstance(session_type, str) and session_type else None,
            'limit': limit,
            'session_laps_total': laps_total,
            'session_time_total_s': round(time_total, 3) if time_total is not None else None,
            'laps_remaining': laps_remaining,
            'laps_remaining_source': laps_source,
            'time_remaining_s': self._read_time_remaining(time_state),
        }

    def _player_ranking(self, key: str) -> Optional[int]:
        player_idx = self._strict_int(self._get_sdk_value('PlayerCarIdx', None))
        values = self._safe_list(self._get_sdk_value(key, []))
        if player_idx is None or not 0 <= player_idx < len(values):
            return None
        rank = self._strict_int(values[player_idx])
        return rank if rank is not None and rank > 0 else None

    def _build_session_strip_data(self) -> Dict[str, Any]:
        """Session strip payload: real metadata only, None when unavailable."""
        payload: Dict[str, Any] = {
            'session_type': None, 'limit': None,
            'session_laps_total': None, 'session_time_total_s': None,
            'laps_remaining': None, 'laps_remaining_source': None, 'time_remaining_s': None,
            'state': None, 'state_code': None, 'flags': None,
            'position': None, 'class_position': None, 'lap': None,
        }
        try:
            payload.update(self._get_session_progress())
            state_code = self._strict_int(self._get_sdk_value('SessionState', None))
            if state_code in _SESSION_STATE_NAMES:
                payload['state'] = _SESSION_STATE_NAMES[state_code]
                payload['state_code'] = state_code
            flags = self._strict_int(self._get_sdk_value('SessionFlags', None))
            if flags is not None and flags >= 0:
                payload['flags'] = [name for bit, name in sorted(_SESSION_FLAG_NAMES.items())
                                    if flags & bit]
            payload['position'] = self._player_ranking('CarIdxPosition')
            payload['class_position'] = self._player_ranking('CarIdxClassPosition')
            lap = self._strict_int(self._get_sdk_value('Lap', None))
            payload['lap'] = lap if lap is not None and lap >= 0 else None
        except Exception as e:
            logging.debug(f"Session strip data unavailable: {e}")
        return payload

    # ------------------------------------------------------------------
    # Fuel & finish payload
    # ------------------------------------------------------------------

    def _estimate_finish_laps(self, progress: Dict[str, Any]) -> tuple:
        """(laps still to run, basis) or (None, None) when not knowable.

        Lap-limited sessions use the reported laps remaining as-is: whole
        laps, so a lap in progress counts fully (never short). Timed
        sessions cannot give an exact distance; the estimate assumes the
        fastest recently sampled clean lap, so it errs towards more laps,
        and adds one lap for finishing the lap in progress after the clock.
        """
        if progress['laps_remaining'] is not None:
            return progress['laps_remaining'], 'laps_remaining'
        if progress['limit'] not in ('time', 'laps_and_time'):
            return None, None  # SessionInfo does not establish a time limit
        time_remaining = progress['time_remaining_s']
        if time_remaining is not None and self._fuel_samples:
            fastest_lap = min(lap_time for _, lap_time in self._fuel_samples)
            return round(time_remaining / fastest_lap + 1.0, 3), 'timed_conservative_estimate'
        return None, None

    def _build_fuel_finish_data(self) -> Dict[str, Any]:
        """Fuel & Finish payload: measured fuel, observed burn, advisory finish."""
        payload: Dict[str, Any] = {
            'fuel_level_l': None, 'fuel_level_pct': None,
            'avg_burn_l_per_lap': None, 'burn_sample_count': 0, 'burn_source': None,
            'laps_of_fuel': None,
            'finish_laps_remaining': None, 'finish_basis': None,
            'finish_fuel_needed_l': None, 'finish_fuel_to_add_l': None,
            'is_estimate': True, 'advisory': True,
        }
        try:
            level = self._valid_fuel_level(self._get_sdk_value('FuelLevel', None))
            fraction = self._valid_fuel_level(self._get_sdk_value('FuelLevelPct', None))
            payload['fuel_level_l'] = round(level, 3) if level is not None else None
            if fraction is not None and fraction <= 1.0:
                payload['fuel_level_pct'] = round(fraction * 100.0, 2)

            samples = list(self._fuel_samples)
            payload['burn_sample_count'] = len(samples)
            average = None
            if samples:
                average = sum(burn for burn, _ in samples) / len(samples)
                payload['avg_burn_l_per_lap'] = round(average, 3)
                payload['burn_source'] = 'observed_clean_laps'
                if level is not None:
                    payload['laps_of_fuel'] = round(level / average, 2)

            finish_laps, basis = self._estimate_finish_laps(self._get_session_progress())
            payload['finish_laps_remaining'] = finish_laps
            payload['finish_basis'] = basis
            if finish_laps is not None and average is not None:
                needed = average * finish_laps
                payload['finish_fuel_needed_l'] = round(needed, 3)
                if level is not None:
                    payload['finish_fuel_to_add_l'] = round(max(needed - level, 0.0), 3)
        except Exception as e:
            logging.debug(f"Fuel data unavailable: {e}")
        return payload

    # ------------------------------------------------------------------
    # Pit Assistant and Weather payloads
    #
    # Read-only observations of SDK variables (names and units from
    # kutu/pyirsdk vars.txt). Missing, non-finite, negative or mistyped
    # values are None; a real 0 or False is kept. Nothing is commanded,
    # forecast or defaulted to a pleasant value.
    # ------------------------------------------------------------------

    def _sdk_number(self, value: Any, minimum: Optional[float] = None, scale: float = 1.0) -> Optional[float]:
        """A finite number from a numeric SDK value, times scale; bools and text are not numbers.

        A product that overflows to inf is unavailable, never sent as inf.
        """
        if isinstance(value, (bool, str)):
            return None
        number = self._finite_or_none(value)
        if number is None or (minimum is not None and number < minimum):
            return None
        return self._finite_or_none(number * scale)

    def _sdk_bool(self, key: str) -> Optional[bool]:
        value = self._get_sdk_value(key, None)
        return value if isinstance(value, bool) else None

    def _percent_from_fraction(self, key: str) -> Optional[float]:
        """An SDK 0..1 ratio as percent; anything outside 0..1 is not rescaled."""
        fraction = self._sdk_number(self._get_sdk_value(key, None), 0.0)
        return round(fraction * 100.0, 2) if fraction is not None and fraction <= 1.0 else None

    def _pit_speed_limit_kmh(self) -> Optional[float]:
        raw = self._get_session_dict('WeekendInfo').get('TrackPitSpeedLimit')
        match = _PIT_LIMIT_RE.match(raw.strip()) if isinstance(raw, str) else None
        if match is None:
            return None
        limit = float(match.group(1)) * _TO_KMH[match.group(2).lower()]
        return round(limit, 3) if limit > 0 else None

    def _build_pit_assistant_data(self) -> Dict[str, Any]:
        """Pit Assistant payload: observed pit status, limit margin and service request."""
        payload: Dict[str, Any] = {
            'speed_kmh': None,
            'on_pit_road': None, 'in_pit_stall': None, 'pits_open': None, 'service_active': None,
            'pit_speed_limit_kmh': None, 'pit_speed_limit_source': None,
            'pit_speed_margin_kmh': None, 'pit_speed_state': None,
            'repair_left_s': None, 'optional_repair_left_s': None, 'tow_time_s': None,
            'service_flags': None, 'service_flags_raw': None,
            'service_status': None, 'service_status_code': None,
            # PitSvFuel is liters or kWh depending on the car and the SDK does
            # not say which, so the amount keeps the SDK's own unit label.
            'service_fuel_amount': None, 'service_fuel_unit': 'L/kWh',
            'service_fuel_requested': None,
            'read_only': True,
        }
        try:
            speed = self._sdk_number(self._get_sdk_value('Speed', None), 0.0, 3.6)
            payload['speed_kmh'] = round(speed, 3) if speed is not None else None
            for key, var in (('on_pit_road', 'OnPitRoad'), ('in_pit_stall', 'PlayerCarInPitStall'),
                             ('pits_open', 'PitsOpen'), ('service_active', 'PitstopActive')):
                payload[key] = self._sdk_bool(var)
            for key, var in (('repair_left_s', 'PitRepairLeft'), ('optional_repair_left_s', 'PitOptRepairLeft'),
                             ('tow_time_s', 'PlayerCarTowTime'), ('service_fuel_amount', 'PitSvFuel')):
                payload[key] = self._sdk_number(self._get_sdk_value(var, None), 0.0)

            limit = self._pit_speed_limit_kmh()
            if limit is not None:
                payload['pit_speed_limit_kmh'] = limit
                payload['pit_speed_limit_source'] = 'WeekendInfo.TrackPitSpeedLimit'
                # The limit only applies on pit road, so there is no margin elsewhere.
                if payload['on_pit_road'] is True and payload['speed_kmh'] is not None:
                    margin = round(limit - payload['speed_kmh'], 3)
                    payload['pit_speed_margin_kmh'] = margin
                    payload['pit_speed_state'] = 'over_limit' if margin < 0 else 'within_limit'

            flags = self._strict_int(self._get_sdk_value('PitSvFlags', None))
            if flags is not None and flags >= 0:
                payload['service_flags_raw'] = flags
                payload['service_flags'] = [name for bit, name in sorted(_PIT_SERVICE_FLAG_NAMES.items())
                                            if flags & bit]
                payload['service_fuel_requested'] = 'fuel_fill' in payload['service_flags']
            status = self._strict_int(self._get_sdk_value('PlayerCarPitSvStatus', None))
            if status is not None:
                payload['service_status_code'] = status
                payload['service_status'] = _PIT_SERVICE_STATUS_NAMES.get(status)
        except Exception as e:
            logging.debug(f"Pit assistant data unavailable: {e}")
        return payload

    def _build_weather_data(self) -> Dict[str, Any]:
        """Weather payload: conditions observed at the start/finish line, never a forecast."""
        payload: Dict[str, Any] = {
            'air_temp_c': None, 'track_temp_c': None, 'humidity_pct': None,
            'wind_speed_ms': None, 'wind_speed_kmh': None, 'wind_dir_deg': None,
            'precipitation_pct': None, 'track_wetness': None, 'track_wetness_code': None,
            'declared_wet': None, 'observed': True,
        }
        try:
            # TrackTempCrew only: the older TrackTemp is deprecated by the SDK.
            for key, var in (('air_temp_c', 'AirTemp'), ('track_temp_c', 'TrackTempCrew')):
                temp = self._sdk_number(self._get_sdk_value(var, None))
                payload[key] = round(temp, 2) if temp is not None else None
            payload['humidity_pct'] = self._percent_from_fraction('RelativeHumidity')
            payload['precipitation_pct'] = self._percent_from_fraction('Precipitation')
            wind = self._sdk_number(self._get_sdk_value('WindVel', None), 0.0)
            wind_kmh = self._sdk_number(self._get_sdk_value('WindVel', None), 0.0, 3.6)
            payload['wind_speed_ms'] = round(wind, 3) if wind is not None else None
            payload['wind_speed_kmh'] = round(wind_kmh, 3) if wind_kmh is not None else None
            degrees = self._sdk_number(self._get_sdk_value('WindDir', None), None, 180.0 / math.pi)
            if degrees is not None:
                payload['wind_dir_deg'] = round(degrees % 360.0, 1) % 360.0
            wetness = self._strict_int(self._get_sdk_value('TrackWetness', None))
            if wetness is not None:
                payload['track_wetness_code'] = wetness
                payload['track_wetness'] = _TRACK_WETNESS_NAMES.get(wetness)
            payload['declared_wet'] = self._sdk_bool('WeatherDeclaredWet')
        except Exception as e:
            logging.debug(f"Weather data unavailable: {e}")
        return payload

    # ------------------------------------------------------------------
    # Standings and battle/pace
    #
    # Built from per-car SDK arrays that may be short, hold sentinels or
    # NaN. Unknown stays None: ranks, names, classes, gaps and lap times are
    # never inferred or zero-filled. Opponent lap observation keeps its own
    # resettable state and never touches the player lap sampler above.
    # ------------------------------------------------------------------

    def _reset_pace_tracking(self) -> None:
        self._pace_session: Optional[int] = None
        # car idx -> completed laps at the last poll, consecutive observed
        # lap times, and whether the car touched pit road during this lap.
        self._pace_cars: Dict[int, Dict[str, Any]] = {}

    def _car_array(self, key: str) -> List[Any]:
        return self._safe_list(self._get_sdk_value(key, []))

    def _at(self, values: List[Any], idx: int) -> Any:
        """values[idx] for an in-range index, else None (never wraps negative)."""
        return values[idx] if 0 <= idx < len(values) else None

    def _rank(self, value: Any) -> Optional[int]:
        rank = self._strict_int(value)
        return rank if rank is not None and rank > 0 else None

    def _lap_seconds(self, value: Any) -> Optional[float]:
        """A real lap time; the SDK's -1/0 sentinels and NaN are unknown."""
        if isinstance(value, bool):
            return None
        seconds = self._finite_or_none(value)
        return round(seconds, 3) if seconds is not None and seconds > 0 else None

    def _text_or_none(self, value: Any) -> Optional[str]:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        return str(value).strip() or None

    def _get_standings_roster(self) -> Dict[int, Dict[str, Any]]:
        """CarIdx -> real DriverInfo identity and class; unknown fields are None.

        Field names follow the published iRacing session YAML model
        (IRSDKSharper IRacingSdkSessionInfo.cs): CarIdx, UserName, CarNumber,
        CarClassID, CarClassShortName, CarIsPaceCar and IsSpectator. Pace cars
        and spectators are marked excluded.
        """
        info = self._get_session_dict('DriverInfo')
        if not info:
            info = self._get_session_dict('SessionInfo').get('DriverInfo') or {}
        drivers = info.get('Drivers') if isinstance(info, dict) else None
        roster: Dict[int, Dict[str, Any]] = {}
        for driver in drivers if isinstance(drivers, list) else []:
            idx = self._strict_int(driver.get('CarIdx')) if isinstance(driver, dict) else None
            if idx is None or idx < 0 or idx in roster:
                continue
            class_id = self._strict_int(driver.get('CarClassID'))
            roster[idx] = {
                'name': self._text_or_none(driver.get('UserName')),
                'car_number': self._text_or_none(driver.get('CarNumber')),
                'class_id': class_id if class_id is not None and class_id >= 0 else None,
                'class_name': self._text_or_none(driver.get('CarClassShortName')),
                'excluded': any(self._finite_or_none(driver.get(key))
                                for key in ('CarIsPaceCar', 'IsSpectator')),
            }
        return roster

    def _read_race_timing(self) -> tuple:
        """(session type or None, whether race timing may be read).

        The type comes only from SessionInfo for the current SessionNum; the
        legacy _current_session_type default of 'Race' is not trusted here.
        """
        raw = (self._get_session_entry() or {}).get('SessionType')
        session_type = raw.strip() if isinstance(raw, str) and raw.strip() else None
        state = _SESSION_STATE_NAMES.get(self._strict_int(self._get_sdk_value('SessionState', None)))
        confirmed = (session_type is not None and session_type.lower() == 'race'
                     and state in _RACE_TIMING_STATES)
        return session_type, confirmed

    def _observe_pace_laps(self) -> None:
        """Record each car's last lap time on observed completed-lap boundaries.

        A lap is kept only when the completed-lap counter rose by exactly one
        since the previous poll and the car stayed off pit road. First sight,
        a skipped poll or a rollback only re-baselines, repeated polls add
        nothing, and any unusable lap ends the consecutive run.
        """
        session_num = self._safe_int(self._get_sdk_value('SessionNum', 0))
        if session_num != self._pace_session:
            self._reset_pace_tracking()
            self._pace_session = session_num
        completed = self._car_array('CarIdxLapCompleted')
        last_laps = self._car_array('CarIdxLastLapTime')
        on_pit = self._car_array('CarIdxOnPitRoad')
        seen = set()
        for idx, raw_completed in enumerate(completed):
            laps = self._strict_int(raw_completed)
            if laps is None or laps < 0:
                continue
            seen.add(idx)
            pit = bool(self._at(on_pit, idx))
            state = self._pace_cars.get(idx)
            if state is None or laps < state['laps_completed'] or laps > state['laps_completed'] + 1:
                self._pace_cars[idx] = {'laps_completed': laps, 'times': [], 'pit': pit}
            elif laps == state['laps_completed']:
                state['pit'] = state['pit'] or pit
            else:
                lap_time = self._lap_seconds(self._at(last_laps, idx))
                if lap_time is not None and not state['pit'] and not pit:
                    state['times'].append(lap_time)
                    del state['times'][:-_PACE_WINDOW]
                else:
                    state['times'] = []
                state['laps_completed'] = laps
                state['pit'] = pit
        for idx in [idx for idx in self._pace_cars if idx not in seen]:
            del self._pace_cars[idx]

    def _pace_times(self, car_idx: int) -> List[float]:
        return list(self._pace_cars.get(car_idx, {}).get('times', []))

    def _summarize_pace(self, times: List[float]) -> Dict[str, Any]:
        """Average and least-squares slope (s/lap) of observed consecutive laps."""
        count = len(times)
        mean = sum(times) / count if count else None
        summary: Dict[str, Any] = {
            'laps': count,
            'avg_lap_s': round(mean, 3) if count >= _PACE_MIN_LAPS else None,
            'trend_s_per_lap': None, 'trend': None,
        }
        if count >= _TREND_MIN_LAPS:
            centre = (count - 1) / 2.0
            slope = (sum((i - centre) * (t - mean) for i, t in enumerate(times))
                     / sum((i - centre) ** 2 for i in range(count)))
            summary['trend_s_per_lap'] = round(slope, 3)
            summary['trend'] = ('improving' if slope <= -_TREND_STEADY_S else
                                'worsening' if slope >= _TREND_STEADY_S else 'steady')
        return summary

    def _pace_delta(self, car: Dict[str, Any], player: Dict[str, Any]) -> Optional[float]:
        """Opponent minus player mean over the laps both have observed."""
        theirs = self._pace_times(car['car_idx'])
        mine = self._pace_times(player['car_idx'])
        shared = min(len(theirs), len(mine))
        if shared < _PACE_MIN_LAPS:
            return None
        return round(sum(theirs[-shared:]) / shared - sum(mine[-shared:]) / shared, 3)

    def _build_field(self) -> Dict[str, Any]:
        """Every classified car with validated rank, identity, class and timing."""
        player_idx = self._strict_int(self._get_sdk_value('PlayerCarIdx', None))
        positions = self._car_array('CarIdxPosition')
        class_positions = self._car_array('CarIdxClassPosition')
        completed = self._car_array('CarIdxLapCompleted')
        lap_pct = self._car_array('CarIdxLapDistPct')
        f2_times = self._car_array('CarIdxF2Time')
        best_laps = self._car_array('CarIdxBestLapTime')
        last_laps = self._car_array('CarIdxLastLapTime')
        on_pit = self._car_array('CarIdxOnPitRoad')
        roster = self._get_standings_roster()
        session_type, race_timing = self._read_race_timing()
        is_race = session_type is not None and session_type.lower() == 'race'

        cars: List[Dict[str, Any]] = []
        for idx in range(max(len(positions), len(best_laps))):
            member = roster.get(idx, {})
            if member.get('excluded'):
                continue
            position = self._rank(self._at(positions, idx))
            best = self._lap_seconds(self._at(best_laps, idx))
            # A race lists ranked cars only; other sessions also list cars
            # that merely have a best lap, ordered by that lap.
            if position is None and (is_race or best is None):
                continue
            laps = self._strict_int(self._at(completed, idx))
            laps = laps if laps is not None and laps >= 0 else None
            pct = self._finite_or_none(self._at(lap_pct, idx))
            pct = pct if pct is not None and 0.0 <= pct <= 1.0 else None
            f2 = self._finite_or_none(self._at(f2_times, idx))
            pit = self._at(on_pit, idx)
            class_id = member.get('class_id')
            cars.append({
                'car_idx': idx,
                'position': position,
                # A class rank means nothing once the class itself is unknown.
                'class_position': self._rank(self._at(class_positions, idx)) if class_id is not None else None,
                'car_number': member.get('car_number'),
                'name': member.get('name'),
                'class_id': class_id,
                'class_name': member.get('class_name'),
                'laps_completed': laps,
                'progress': laps + pct if laps is not None and pct is not None else None,
                'f2_time': f2 if f2 is not None and f2 >= 0 else None,
                'best_lap_s': best,
                'last_lap_s': self._lap_seconds(self._at(last_laps, idx)),
                'on_pit_road': None if pit is None else bool(pit),
                'is_player': player_idx is not None and idx == player_idx,
                'gap_to_leader_s': None, 'laps_down': None,
                'interval_s': None, 'best_lap_delta_s': None,
                # Private: F2Time as a race time, comparable only between cars
                # less than a lap apart. Never part of a payload.
                'race_time_s': None,
            })

        leader = next((car for car in cars if car['position'] == 1), None)
        if race_timing and leader is not None:
            for car in cars:
                self._apply_leader_gap(car, leader)
        return {'cars': cars, 'session_type': session_type,
                'gap_basis': 'race_f2time' if race_timing else None}

    def _apply_leader_gap(self, car: Dict[str, Any], leader: Dict[str, Any]) -> None:
        """Laps down and, on the leader's lap, CarIdxF2Time as seconds behind.

        F2Time only means time behind the leader for a car less than a lap
        down; a lapped car gets a lap count and no time. Progress is compared
        directly, so there is no modulo wrap to turn a lapped car into a
        negative time.
        """
        if car['progress'] is None or leader['progress'] is None:
            return
        car['laps_down'] = int(max(leader['progress'] - car['progress'], 0.0))
        if car is leader:
            car['gap_to_leader_s'] = 0.0
            car['race_time_s'] = 0.0
        elif car['f2_time'] is not None and car['f2_time'] > 0:
            car['race_time_s'] = car['f2_time']
            if car['laps_down'] == 0:
                car['gap_to_leader_s'] = round(car['f2_time'], 3)

    def _time_between(self, ahead: Dict[str, Any], behind: Dict[str, Any]) -> Optional[float]:
        """Seconds from the car ahead to the car behind, when both are timed.

        The two cars' CarIdxF2Time values are only comparable while the pair
        is less than one lap apart, judged from the pair's own race progress
        (never from class rank and never from each car's deficit to the
        overall leader: equal or different whole-lap deficits to the leader
        say nothing about the pair). Progress must put `ahead` in front, so a
        class order that contradicts progress is never turned into a time.
        """
        if ahead['race_time_s'] is None or behind['race_time_s'] is None:
            return None
        if ahead['progress'] is None or behind['progress'] is None:
            return None
        distance = ahead['progress'] - behind['progress']
        if not 0.0 <= distance < 1.0:
            return None
        seconds = behind['race_time_s'] - ahead['race_time_s']
        return round(seconds, 3) if seconds >= 0 else None

    def _delta(self, other: Optional[float], mine: Optional[float]) -> Optional[float]:
        return round(other - mine, 3) if other is not None and mine is not None else None

    def _build_standings_data(self, field: Dict[str, Any]) -> Dict[str, Any]:
        members: Dict[Any, List[Dict[str, Any]]] = {}
        for car in field['cars']:
            members.setdefault(car['class_id'], []).append(car)

        classes = []
        for class_id, cars in members.items():
            known = class_id is not None
            # Unknown-class cars mix real classes, so they follow overall rank.
            rank_key = 'class_position' if known else 'position'
            cars.sort(key=lambda c: (c[rank_key] is None, c[rank_key] or 0,
                                     c['position'] is None, c['position'] or 0,
                                     c['best_lap_s'] is None, c['best_lap_s'] or 0.0, c['car_idx']))
            if known:
                class_best = min((c['best_lap_s'] for c in cars if c['best_lap_s'] is not None), default=None)
                for i, car in enumerate(cars):
                    car['best_lap_delta_s'] = self._delta(car['best_lap_s'], class_best)
                    if i:
                        car['interval_s'] = self._time_between(cars[i - 1], car)
            classes.append({
                'class_id': class_id,
                'class_name': next((c['class_name'] for c in cars if c['class_name']), None),
                'known': known,
                'cars': [{key: car[key] for key in (
                    'car_idx', 'position', 'class_position', 'car_number', 'name', 'laps_completed',
                    'best_lap_s', 'last_lap_s', 'best_lap_delta_s', 'on_pit_road', 'is_player',
                    'gap_to_leader_s', 'laps_down', 'interval_s')} for car in cars],
            })
        classes.sort(key=lambda g: (
            not g['known'],
            min((c['position'] for c in g['cars'] if c['position'] is not None), default=math.inf),
            min((c['best_lap_s'] for c in g['cars'] if c['best_lap_s'] is not None), default=math.inf)))

        player = next((car for car in field['cars'] if car['is_player']), None)
        return {
            'session_type': field['session_type'],
            'gap_basis': field['gap_basis'],
            'player_car_idx': player['car_idx'] if player else None,
            'classes': classes,
        }

    def _battle_entry(self, car: Dict[str, Any]) -> Dict[str, Any]:
        entry = {key: car[key] for key in (
            'car_idx', 'name', 'car_number', 'position', 'class_position', 'laps_completed',
            'last_lap_s', 'best_lap_s', 'on_pit_road', 'laps_down')}
        entry['pace'] = self._summarize_pace(self._pace_times(car['car_idx']))
        return entry

    def _build_battle_pace_data(self, field: Dict[str, Any]) -> Dict[str, Any]:
        """Same-class neighbours around the player; opponent minus player deltas."""
        payload: Dict[str, Any] = {
            'session_type': field['session_type'], 'gap_basis': field['gap_basis'],
            'context': 'player_unavailable', 'class_id': None, 'class_name': None,
            'lap_time_source': 'CarIdxLastLapTime/CarIdxBestLapTime',
            'player': None, 'ahead': None, 'behind': None,
        }
        player = next((car for car in field['cars'] if car['is_player']), None)
        if player is None:
            return payload
        payload['player'] = self._battle_entry(player)
        if player['class_id'] is None:
            payload['context'] = 'class_unknown'
            return payload
        payload['class_id'] = player['class_id']
        payload['class_name'] = player['class_name']
        if player['class_position'] is None:
            payload['context'] = 'class_position_unavailable'
            return payload
        payload['context'] = 'ok'

        def neighbour(rank: int) -> Optional[Dict[str, Any]]:
            matches = [c for c in field['cars']
                       if c['class_id'] == player['class_id'] and c['class_position'] == rank]
            return matches[0] if len(matches) == 1 else None

        for role, rival in (('ahead', neighbour(player['class_position'] - 1)),
                            ('behind', neighbour(player['class_position'] + 1))):
            if rival is None:
                continue
            entry = self._battle_entry(rival)
            entry['gap_s'] = (self._time_between(rival, player) if role == 'ahead'
                              else self._time_between(player, rival))
            entry['last_lap_delta_s'] = self._delta(rival['last_lap_s'], player['last_lap_s'])
            entry['best_lap_delta_s'] = self._delta(rival['best_lap_s'], player['best_lap_s'])
            entry['pace_delta_s'] = self._pace_delta(rival, player)
            payload[role] = entry
        return payload

    def _build_race_overlay_data(self) -> Dict[str, Any]:
        """standings_data and battle_pace_data; None when they cannot be built."""
        payloads: Dict[str, Any] = {'standings_data': None, 'battle_pace_data': None}
        try:
            self._observe_pace_laps()
        except Exception as e:
            logging.debug(f"Opponent pace tracking reset after error: {e}")
            self._reset_pace_tracking()
        try:
            field = self._build_field()
            payloads['standings_data'] = self._build_standings_data(field)
            payloads['battle_pace_data'] = self._build_battle_pace_data(field)
        except Exception as e:
            logging.debug(f"Standings/battle data unavailable: {e}")
        return payloads

    # ------------------------------------------------------------------
    # Broadcast Driver Card
    #
    # Follows the broadcast camera (CamCarIdx) only. Identity comes from
    # DriverInfo.Drivers and statistics from per-car SDK arrays; a field the
    # SDK does not give for that car is None. Player-only variables (speed,
    # pedals, steering, RPM, gear, fuel) are never read, so nothing of the
    # player can be shown as another driver's data. The whole payload is
    # rebuilt every poll and keeps no state between cameras.
    # ------------------------------------------------------------------

    def _broadcast_driver_payload(self, reason: Optional[str], **fields: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'available': reason is None, 'reason': reason,
            'camera_car_idx': None, 'identity_available': False,
            'name': None, 'car_number': None, 'class_id': None, 'class_name': None,
            'position': None, 'class_position': None, 'laps_completed': None,
            'last_lap_s': None, 'best_lap_s': None, 'on_pit_road': None,
            'session_type': None, 'source': 'CamCarIdx',
        }
        payload.update(fields)
        return payload

    def _build_broadcast_driver_data(self) -> Optional[Dict[str, Any]]:
        """Camera-followed driver card; None only if the builder itself fails.

        A missing, negative, boolean, non-integral, non-finite or unknown
        CamCarIdx is an unavailable card: it never falls back to PlayerCarIdx.
        A car is known when DriverInfo lists it or the per-car arrays have a
        slot for it; one missing from DriverInfo keeps its guarded statistics
        with identity unavailable. Pace cars and spectators are unavailable
        too, using the same roster filter as the standings.
        """
        try:
            roster = self._get_standings_roster()
            arrays = {key: self._car_array(key) for key in _BROADCAST_ARRAYS}
            idx = self._strict_int(self._get_sdk_value('CamCarIdx', None))
            slots = max(len(values) for values in arrays.values())
            if idx is None or idx < 0 or (idx not in roster and idx >= slots):
                return self._broadcast_driver_payload('camera_unavailable')
            member = roster.get(idx, {})
            if member.get('excluded'):
                return self._broadcast_driver_payload('camera_target_excluded')

            laps = self._strict_int(self._at(arrays['CarIdxLapCompleted'], idx))
            pit = self._at(arrays['CarIdxOnPitRoad'], idx)
            class_id = member.get('class_id')
            return self._broadcast_driver_payload(
                None, camera_car_idx=idx, identity_available=idx in roster,
                name=member.get('name'), car_number=member.get('car_number'),
                class_id=class_id, class_name=member.get('class_name'),
                position=self._rank(self._at(arrays['CarIdxPosition'], idx)),
                # A class rank means nothing once the class itself is unknown.
                class_position=(self._rank(self._at(arrays['CarIdxClassPosition'], idx))
                                if class_id is not None else None),
                laps_completed=laps if laps is not None and laps >= 0 else None,
                last_lap_s=self._lap_seconds(self._at(arrays['CarIdxLastLapTime'], idx)),
                best_lap_s=self._lap_seconds(self._at(arrays['CarIdxBestLapTime'], idx)),
                on_pit_road=pit if isinstance(pit, bool) else None,
                session_type=self._read_race_timing()[0])
        except Exception as e:
            logging.debug(f"Broadcast driver data unavailable: {e}")
            return None

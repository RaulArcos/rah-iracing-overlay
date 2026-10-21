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
        
        return {
            **base,
            **self._compute_overlay_metrics(),
            "relative_data": self._build_relative_data(),
            "track_map_data": self._build_track_map_data(),
            "radar_data": self._build_radar_data(),
            "blindspot_data": self._build_blindspot_data(),
            "laptime_graph_data": self._build_laptime_graph_data(),
        }

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

    def _update_lap_times(self) -> None:
        """Record LapLastLapTime on actual completed-lap transitions.

        Rejects startup partial laps (the first observation only sets a
        baseline), duplicate samples of the same lap, and invalid lap times
        (zero, negative, or non-finite). History resets on session change,
        reconnect, and lap rollback, and is capped at the last 10 laps.
        """
        current_lap = self._get_sdk_value('Lap', None)
        if not isinstance(current_lap, (int, float)) or isinstance(current_lap, bool):
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
            return

        if current_lap < self._last_lap_seen:
            # Lap rollback (session restart): history from the abandoned
            # run is no longer valid.
            self._reset_lap_tracking()
            self._lap_tracking_session = session_num
            self._last_lap_seen = current_lap
            return

        if current_lap <= self._last_lap_seen:
            return  # duplicate sample of the current lap

        # At least one lap completed since the last poll. LapLastLapTime
        # holds only the most recently completed lap, so record it once and
        # re-baseline; skipped laps cannot be recovered and are never
        # fabricated.
        last_lap_time = self._finite_or_none(self._get_sdk_value('LapLastLapTime', None))
        if last_lap_time is not None and last_lap_time > 0:
            self.lap_times.append(round(last_lap_time, 3))
            if len(self.lap_times) > 10:
                self.lap_times.pop(0)
        self._last_lap_seen = current_lap

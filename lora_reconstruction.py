from __future__ import annotations

import json
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple


EARTH_RADIUS_M = 6371000.0


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc)

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlon_r = math.radians(lon2 - lon1)
    y = math.sin(dlon_r) * math.cos(lat2_r)
    x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon_r)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> Tuple[float, float]:
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    angular_distance = distance_m / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )

    return math.degrees(lat2), ((math.degrees(lon2) + 540.0) % 360.0) - 180.0


@dataclass
class TelemetryRecord:
    node_id: str
    timestamp: datetime
    lat: Optional[float]
    lon: Optional[float]
    speed_mps: Optional[float] = None
    heading_deg: Optional[float] = None
    altitude_m: Optional[float] = None
    source: str = "unknown"
    raw_packet: str = ""
    packet_status: str = "verified"
    confidence: float = 1.0
    notes: List[str] = field(default_factory=list)
    checksum_valid: Optional[bool] = None

    def to_dashboard_payload(self) -> Dict[str, object]:
        return {
            "node_id": self.node_id,
            "timestamp": self.timestamp.isoformat(),
            "lat": self.lat,
            "lon": self.lon,
            "speed_mps": self.speed_mps,
            "heading_deg": self.heading_deg,
            "altitude_m": self.altitude_m,
            "source": self.source,
            "packet_status": self.packet_status,
            "confidence": round(self.confidence, 3),
            "render_style": "verified-dot" if self.packet_status == "verified" else "estimated-dot",
            "notes": self.notes,
            "checksum_valid": self.checksum_valid,
        }


@dataclass
class NodeState:
    history: Deque[TelemetryRecord] = field(default_factory=lambda: deque(maxlen=10))
    filter_state: Optional[List[List[float]]] = None
    covariance: Optional[List[List[float]]] = None


class ConstantVelocityKalman2D:
    def __init__(self) -> None:
        self.default_covariance = [
            [20.0, 0.0, 0.0, 0.0],
            [0.0, 20.0, 0.0, 0.0],
            [0.0, 0.0, 8.0, 0.0],
            [0.0, 0.0, 0.0, 8.0],
        ]

    def predict(self, state: List[List[float]], covariance: List[List[float]], dt: float) -> Tuple[List[List[float]], List[List[float]]]:
        F = [
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        q = max(dt, 1.0)
        Q = [
            [0.25 * q * q, 0.0, 0.5 * q, 0.0],
            [0.0, 0.25 * q * q, 0.0, 0.5 * q],
            [0.5 * q, 0.0, 1.5, 0.0],
            [0.0, 0.5 * q, 0.0, 1.5],
        ]
        predicted_state = self._matmul(F, state)
        predicted_cov = self._matadd(self._matmul(self._matmul(F, covariance), self._transpose(F)), Q)
        return predicted_state, predicted_cov

    def update(
        self,
        predicted_state: List[List[float]],
        predicted_cov: List[List[float]],
        measurement: Tuple[float, float],
    ) -> Tuple[List[List[float]], List[List[float]]]:
        H = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
        R = [
            [6.0, 0.0],
            [0.0, 6.0],
        ]
        z = [[measurement[0]], [measurement[1]]]
        y = self._matsub(z, self._matmul(H, predicted_state))
        S = self._matadd(self._matmul(self._matmul(H, predicted_cov), self._transpose(H)), R)
        K = self._matmul(self._matmul(predicted_cov, self._transpose(H)), self._inv2(S))
        updated_state = self._matadd(predicted_state, self._matmul(K, y))
        I = self._identity(4)
        updated_cov = self._matmul(self._matsub(I, self._matmul(K, H)), predicted_cov)
        return updated_state, updated_cov

    def bootstrap(self, x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> Tuple[List[List[float]], List[List[float]]]:
        return [[x], [y], [vx], [vy]], [row[:] for row in self.default_covariance]

    def _identity(self, n: int) -> List[List[float]]:
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    def _transpose(self, a: List[List[float]]) -> List[List[float]]:
        return [list(row) for row in zip(*a)]

    def _matmul(self, a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        rows, cols, inner = len(a), len(b[0]), len(b)
        result = [[0.0 for _ in range(cols)] for _ in range(rows)]
        for i in range(rows):
            for j in range(cols):
                result[i][j] = sum(a[i][k] * b[k][j] for k in range(inner))
        return result

    def _matadd(self, a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]

    def _matsub(self, a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        return [[a[i][j] - b[i][j] for j in range(len(a[0]))] for i in range(len(a))]

    def _inv2(self, matrix: List[List[float]]) -> List[List[float]]:
        a, b = matrix[0]
        c, d = matrix[1]
        det = a * d - b * c
        if abs(det) < 1e-9:
            det = 1e-9
        return [[d / det, -b / det], [-c / det, a / det]]


class PacketParser:
    JSON_FIELDS = ("node_id", "timestamp", "lat", "lon", "speed_mps", "heading_deg", "altitude_m")

    def parse(self, raw_packet: str) -> Tuple[Dict[str, object], Dict[str, object]]:
        raw_packet = raw_packet.strip()
        if raw_packet.startswith("{") or "node_id" in raw_packet or raw_packet.endswith("}"):
            return self._parse_json_packet(raw_packet)
        if raw_packet.startswith("$") or raw_packet.upper().startswith(("GPRMC", "GPGGA", "GNRMC", "GNGGA")):
            return self._parse_nmea_packet(raw_packet)
        return {}, {"source": "unknown", "notes": ["Unsupported packet format"], "packet_status": "fragmented"}

    def _parse_json_packet(self, raw_packet: str) -> Tuple[Dict[str, object], Dict[str, object]]:
        metadata = {"source": "json", "notes": [], "packet_status": "verified", "checksum_valid": None}
        candidate = raw_packet
        if not candidate.startswith("{"):
            candidate = "{" + candidate
            metadata["notes"].append("Prepended missing JSON header")
            metadata["packet_status"] = "fragmented"
        if not candidate.endswith("}"):
            candidate = candidate + "}"
            metadata["notes"].append("Appended missing JSON footer")
            metadata["packet_status"] = "fragmented"

        try:
            return json.loads(candidate), metadata
        except json.JSONDecodeError:
            recovered: Dict[str, object] = {}
            for field in self.JSON_FIELDS:
                match = re.search(rf'"?{field}"?\s*:\s*("([^"]*)"|[^,}}]+)', raw_packet)
                if match:
                    raw_value = match.group(2) if match.group(2) is not None else match.group(1)
                    recovered[field] = raw_value.strip('" ')
            if recovered:
                metadata["notes"].append("Recovered partial JSON fields using heuristics")
                metadata["packet_status"] = "fragmented"
            else:
                metadata["notes"].append("JSON payload could not be decoded")
            return recovered, metadata

    def _parse_nmea_packet(self, raw_packet: str) -> Tuple[Dict[str, object], Dict[str, object]]:
        metadata = {"source": "nmea", "notes": [], "packet_status": "verified", "checksum_valid": None}
        packet = raw_packet.strip()
        if not packet.startswith("$"):
            packet = "$" + packet
            metadata["notes"].append("Prepended missing NMEA header")
            metadata["packet_status"] = "fragmented"

        checksum_valid = self._validate_nmea_checksum(packet)
        metadata["checksum_valid"] = checksum_valid
        if checksum_valid is False:
            metadata["packet_status"] = "fragmented"
            metadata["notes"].append("Checksum mismatch detected")

        sentence = packet.split("*", 1)[0]
        parts = sentence.split(",")
        talker = parts[0].replace("$", "").upper()
        if talker.endswith("RMC"):
            return self._parse_rmc(parts), metadata
        if talker.endswith("GGA"):
            return self._parse_gga(parts), metadata

        metadata["packet_status"] = "fragmented"
        metadata["notes"].append("Unsupported NMEA sentence type")
        return {}, metadata

    def _validate_nmea_checksum(self, packet: str) -> Optional[bool]:
        if "*" not in packet:
            return None
        body, checksum = packet[1:].split("*", 1)
        checksum = checksum[:2]
        if len(checksum) != 2:
            return False
        calculated = 0
        for char in body:
            calculated ^= ord(char)
        try:
            return calculated == int(checksum, 16)
        except ValueError:
            return False

    def _parse_rmc(self, parts: List[str]) -> Dict[str, object]:
        timestamp_text = parts[1] if len(parts) > 1 else ""
        status = parts[2] if len(parts) > 2 else ""
        lat = self._parse_nmea_coordinate(parts[3] if len(parts) > 3 else "", parts[4] if len(parts) > 4 else "")
        lon = self._parse_nmea_coordinate(parts[5] if len(parts) > 5 else "", parts[6] if len(parts) > 6 else "")
        speed_knots = _safe_float(parts[7] if len(parts) > 7 else None)
        heading = _safe_float(parts[8] if len(parts) > 8 else None)
        date_text = parts[9] if len(parts) > 9 else ""

        timestamp = datetime.now(timezone.utc)
        if len(date_text) == 6 and len(timestamp_text) >= 6:
            try:
                timestamp = datetime.strptime(date_text + timestamp_text[:6], "%d%m%y%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return {
            "node_id": "nmea-node",
            "timestamp": timestamp.isoformat(),
            "lat": lat,
            "lon": lon,
            "speed_mps": speed_knots * 0.514444 if speed_knots is not None else None,
            "heading_deg": heading,
            "valid_fix": status == "A",
        }

    def _parse_gga(self, parts: List[str]) -> Dict[str, object]:
        lat = self._parse_nmea_coordinate(parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else "")
        lon = self._parse_nmea_coordinate(parts[4] if len(parts) > 4 else "", parts[5] if len(parts) > 5 else "")
        altitude = _safe_float(parts[9] if len(parts) > 9 else None)
        return {
            "node_id": "nmea-node",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lat": lat,
            "lon": lon,
            "altitude_m": altitude,
        }

    def _parse_nmea_coordinate(self, value: str, direction: str) -> Optional[float]:
        value = value.strip()
        if not value:
            return None
        try:
            numeric = float(value)
        except ValueError:
            return None
        degrees = int(numeric // 100)
        minutes = numeric - (degrees * 100)
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"):
            decimal *= -1
        return decimal


class LoRaTelemetryReconstructor:
    def __init__(self, history_size: int = 10) -> None:
        self.states: Dict[str, NodeState] = defaultdict(NodeState)
        self.parser = PacketParser()
        self.kalman = ConstantVelocityKalman2D()
        self.history_size = history_size

    def ingest(self, raw_packet: str) -> Dict[str, object]:
        fields, metadata = self.parser.parse(raw_packet)
        record = self._normalize_record(fields, metadata, raw_packet)
        state = self.states[record.node_id]
        state.history = deque(state.history, maxlen=self.history_size)

        if record.lat is not None and record.lon is not None and record.packet_status != "estimated":
            self._update_filter_with_measurement(state, record)
            state.history.append(record)
            return record.to_dashboard_payload()

        estimated = self._estimate_record(record, state)
        state.history.append(estimated)
        self._update_filter_with_measurement(state, estimated)
        return estimated.to_dashboard_payload()

    def _normalize_record(
        self,
        fields: Dict[str, object],
        metadata: Dict[str, object],
        raw_packet: str,
    ) -> TelemetryRecord:
        node_id = str(fields.get("node_id") or "unknown-node")
        timestamp = _parse_timestamp(fields.get("timestamp"))
        lat = _safe_float(fields.get("lat"))
        lon = _safe_float(fields.get("lon"))
        speed_mps = _safe_float(fields.get("speed_mps"))
        heading_deg = _safe_float(fields.get("heading_deg"))
        altitude_m = _safe_float(fields.get("altitude_m"))
        status = metadata.get("packet_status", "verified")

        if lat is None or lon is None:
            status = "fragmented"

        return TelemetryRecord(
            node_id=node_id,
            timestamp=timestamp,
            lat=lat,
            lon=lon,
            speed_mps=speed_mps,
            heading_deg=heading_deg,
            altitude_m=altitude_m,
            source=str(metadata.get("source", "unknown")),
            raw_packet=raw_packet,
            packet_status=status,
            confidence=1.0 if status == "verified" else 0.55,
            notes=list(metadata.get("notes", [])),
            checksum_valid=metadata.get("checksum_valid"),
        )

    def _estimate_record(self, record: TelemetryRecord, state: NodeState) -> TelemetryRecord:
        history = list(state.history)
        if not history:
            record.packet_status = "estimated"
            record.confidence = 0.2
            record.notes.append("No historical state available for prediction")
            return record

        last = history[-1]
        dt = self._seconds_since(last.timestamp, record.timestamp)
        lat, lon, speed_mps, heading_deg = self._predict_from_history(history, dt, record)

        record.lat = lat
        record.lon = lon
        record.speed_mps = speed_mps
        record.heading_deg = heading_deg
        record.packet_status = "estimated"
        record.confidence = self._confidence_from_history(len(history), dt, record.notes)
        record.notes.append("Position reconstructed from historical buffer and motion model")
        return record

    def _predict_from_history(
        self,
        history: List[TelemetryRecord],
        dt: float,
        record: TelemetryRecord,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        last = history[-1]
        previous = history[-2] if len(history) >= 2 else None

        if last.lat is None or last.lon is None:
            return None, None, record.speed_mps, record.heading_deg

        if previous and previous.lat is not None and previous.lon is not None:
            previous_dt = self._seconds_since(previous.timestamp, last.timestamp)
            previous_dt = max(previous_dt, 1.0)
            derived_speed = _haversine_m(previous.lat, previous.lon, last.lat, last.lon) / previous_dt
            derived_heading = _bearing_deg(previous.lat, previous.lon, last.lat, last.lon)
        else:
            derived_speed = record.speed_mps or last.speed_mps or 0.0
            derived_heading = record.heading_deg if record.heading_deg is not None else (last.heading_deg or 0.0)

        speed = record.speed_mps if record.speed_mps is not None else (last.speed_mps if last.speed_mps is not None else derived_speed)
        heading = record.heading_deg if record.heading_deg is not None else (last.heading_deg if last.heading_deg is not None else derived_heading)

        predicted_lat, predicted_lon = _destination_point(last.lat, last.lon, heading, speed * max(dt, 1.0))

        if self.states[record.node_id].filter_state is not None and self.states[record.node_id].covariance is not None:
            predicted_lat, predicted_lon = self._predict_with_filter(self.states[record.node_id], last, dt, predicted_lat, predicted_lon)
            record.notes.append("Kalman prediction blended with kinematic estimate")

        return predicted_lat, predicted_lon, speed, heading

    def _predict_with_filter(
        self,
        state: NodeState,
        last: TelemetryRecord,
        dt: float,
        fallback_lat: float,
        fallback_lon: float,
    ) -> Tuple[float, float]:
        if state.filter_state is None or state.covariance is None or last.lat is None or last.lon is None:
            return fallback_lat, fallback_lon

        predicted_state, predicted_cov = self.kalman.predict(state.filter_state, state.covariance, max(dt, 1.0))
        vx = predicted_state[2][0]
        vy = predicted_state[3][0]
        distance = math.sqrt(vx * vx + vy * vy) * max(dt, 1.0)
        if distance < 0.1:
            return fallback_lat, fallback_lon

        bearing = (math.degrees(math.atan2(vx, vy)) + 360.0) % 360.0
        filter_lat, filter_lon = _destination_point(last.lat, last.lon, bearing, distance)
        state.filter_state = predicted_state
        state.covariance = predicted_cov
        blended_lat = (fallback_lat * 0.65) + (filter_lat * 0.35)
        blended_lon = (fallback_lon * 0.65) + (filter_lon * 0.35)
        return blended_lat, blended_lon

    def _update_filter_with_measurement(self, state: NodeState, record: TelemetryRecord) -> None:
        if record.lat is None or record.lon is None:
            return

        if not state.history:
            state.filter_state, state.covariance = self.kalman.bootstrap(0.0, 0.0)
            return

        anchor = state.history[-1]
        if anchor.lat is None or anchor.lon is None:
            state.filter_state, state.covariance = self.kalman.bootstrap(0.0, 0.0)
            return

        dt = self._seconds_since(anchor.timestamp, record.timestamp)
        dx = _haversine_m(anchor.lat, anchor.lon, anchor.lat, record.lon)
        dy = _haversine_m(anchor.lat, anchor.lon, record.lat, anchor.lon)
        if record.lon < anchor.lon:
            dx *= -1
        if record.lat < anchor.lat:
            dy *= -1

        if state.filter_state is None or state.covariance is None:
            vx = dx / max(dt, 1.0)
            vy = dy / max(dt, 1.0)
            state.filter_state, state.covariance = self.kalman.bootstrap(dx, dy, vx, vy)
            return

        predicted_state, predicted_cov = self.kalman.predict(state.filter_state, state.covariance, max(dt, 1.0))
        state.filter_state, state.covariance = self.kalman.update(predicted_state, predicted_cov, (dx, dy))

    def _confidence_from_history(self, history_depth: int, dt: float, notes: List[str]) -> float:
        confidence = 0.35 + min(history_depth, 5) * 0.1
        confidence -= min(dt, 30.0) * 0.01
        if any("Checksum mismatch" in note for note in notes):
            confidence -= 0.05
        return max(0.15, min(confidence, 0.92))

    def _seconds_since(self, earlier: datetime, later: datetime) -> float:
        seconds = (later - earlier).total_seconds()
        return max(seconds, 1.0)


def demo_packets() -> List[str]:
    return [
        '{"node_id":"alpha-1","timestamp":"2026-04-18T10:00:00Z","lat":17.3850,"lon":78.4867,"speed_mps":4.2,"heading_deg":90}',
        '{"node_id":"alpha-1","timestamp":"2026-04-18T10:00:08Z","lat":17.3850,"lon":78.4871,"speed_mps":4.3,"heading_deg":89}',
        '{"node_id":"alpha-1","timestamp":"2026-04-18T10:00:16Z","lat":17.3850,"lon":78.487',
        '$GPRMC,100025,A,1723.102,N,07829.244,E,8.1,89.0,180426,,,A*6A',
        '{"node_id":"alpha-1","timestamp":"2026-04-18T10:00:32Z","speed_mps":4.4,"heading_deg":88}',
        'node_id":"alpha-1","timestamp":"2026-04-18T10:00:40Z","lat":17.3850,"lon":78.4888,"speed_mps":4.4,"heading_deg":87',
    ]

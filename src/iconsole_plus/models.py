from dataclasses import dataclass


@dataclass(frozen=True)
class TelemetryData:
    duration_seconds: int
    speed_kmh: float
    power_watts: int
    distance_km: float
    calories_kcal: int
    heart_rate_bpm: int
    cadence_rpm: float
    is_running: bool
    raw: str

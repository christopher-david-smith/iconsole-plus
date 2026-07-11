from .models import TelemetryData


class ProtocolCodec:
    @staticmethod
    def calculate_checksum(data: list[int] | bytes) -> int:
        return (sum(data[1:]) + 0xF0) & 0xFF

    @classmethod
    def encode_ping(cls) -> bytes:
        base = [0xF0, 0xA0, 0x01, 0x01]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_manual_mode(cls) -> bytes:
        base = [0xF0, 0xA1, 0x01, 0x01]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_heartbeat(cls) -> bytes:
        base = [0xF0, 0xA2, 0x01, 0x01]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_init_packet(cls) -> bytes:
        # Standard 15-byte init sequence from capture
        base = [0xF0, 0xA4] + [0x01] * 12
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_start(cls) -> bytes:
        base = [0xF0, 0xA5, 0x01, 0x01, 0x02]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_stop(cls) -> bytes:
        base = [0xF0, 0xA5, 0x01, 0x01, 0x03]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @classmethod
    def encode_set_level(cls, level: int) -> bytes:
        # level is 1-32, protocol uses value + 1
        base = [0xF0, 0xA6, 0x01, 0x01, (level + 1) & 0xFF]
        base.append(cls.calculate_checksum(base))
        return bytes(base)

    @staticmethod
    def decode_telemetry(data: bytes) -> TelemetryData | None:
        if len(data) < 21 or data[0:2] != b"\xf0\xb2":
            return None

        def val(idx):
            return (data[idx] - 1) * 100 + (data[idx + 1] - 1)

        return TelemetryData(
            duration_seconds=(data[4] - 1) * 60 + (data[5] - 1),
            speed_kmh=val(6) / 10.0,
            power_watts=val(16) / 10.0,
            distance_km=val(10) / 10.0,
            calories_kcal=val(12),
            heart_rate_bpm=val(14),
            cadence_rpm=val(8),
            is_running=data[19] == 0x02,
            raw=data.hex("-").upper(),
        )

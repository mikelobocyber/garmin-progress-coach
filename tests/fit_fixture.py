"""Minimal FIT file encoder — test fixture generator only.

Builds just enough of the FIT binary format (header, file_id, optional
activity and session messages, CRC) for garmin-fit-sdk to decode. Not a
general-purpose encoder.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

ENUM, UINT8, UINT16, UINT32 = 0x00, 0x02, 0x84, 0x86

SPORT = {"running": 1, "cycling": 2, "training": 10, "walking": 11}
SUB_SPORT = {"generic": 0, "treadmill": 1, "strength_training": 20}

CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]


def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF]
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def _fit_ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - FIT_EPOCH).total_seconds())


def _definition(local: int, global_num: int, fields: list[tuple[int, int, int]]) -> bytes:
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for def_num, size, base_type in fields:
        out += struct.pack("<BBB", def_num, size, base_type)
    return out


def make_fit_bytes(
    *,
    start_utc: datetime,
    sport: str = "running",
    sub_sport: str = "generic",
    distance_meters: float | None = 3218.7,
    timer_seconds: float = 1104.0,
    calories: int = 240,
    avg_hr: int = 171,
    max_hr: int = 187,
    utc_offset_hours: float = 0.0,
    include_session: bool = True,
) -> bytes:
    ts = _fit_ts(start_utc)
    records = b""

    # file_id: type=4 (activity), time_created
    records += _definition(0, 0, [(0, 1, ENUM), (4, 4, UINT32)])
    records += struct.pack("<BBI", 0x00, 4, ts)

    # activity: timestamp + local_timestamp (how real files carry the UTC offset)
    records += _definition(1, 34, [(253, 4, UINT32), (5, 4, UINT32)])
    records += struct.pack("<BII", 0x01, ts, ts + int(utc_offset_hours * 3600))

    if include_session:
        fields = [
            (2, 4, UINT32),   # start_time
            (5, 1, ENUM),     # sport
            (6, 1, ENUM),     # sub_sport
            (7, 4, UINT32),   # total_elapsed_time (s * 1000)
            (8, 4, UINT32),   # total_timer_time (s * 1000)
            (9, 4, UINT32),   # total_distance (m * 100)
            (11, 2, UINT16),  # total_calories
            (16, 1, UINT8),   # avg_heart_rate
            (17, 1, UINT8),   # max_heart_rate
        ]
        records += _definition(2, 18, fields)
        distance_cm = int(round((distance_meters or 0) * 100))
        records += struct.pack(
            "<BIBBIIIHBB",
            0x02,
            ts,
            SPORT.get(sport, 0),
            SUB_SPORT.get(sub_sport, 0),
            int(timer_seconds * 1000) + 5000,  # elapsed slightly longer than timer
            int(timer_seconds * 1000),
            distance_cm,
            calories,
            avg_hr,
            max_hr,
        )

    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(records), b".FIT")
    header += struct.pack("<H", _crc16(header))
    return header + records + struct.pack("<H", _crc16(records))

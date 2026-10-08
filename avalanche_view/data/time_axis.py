"""Read actual model dates before considering a filename fallback."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import numpy as np


def parse_datetime(value) -> datetime | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        value = np.datetime_as_string(value, unit="us")
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, (str, datetime)):
        # cftime dates in standard calendars are representable as Python dates.
        if hasattr(value, "calendar") and value.calendar in {
            "standard",
            "gregorian",
            "proleptic_gregorian",
        }:
            value = str(value)
        else:
            return None
    try:
        date = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(
                value.strip()
                .strip("\x00")
                .removesuffix(" UTC")
                .replace("_", "T")
                .replace("Z", "+00:00")
            )
        )
        return date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)
    except ValueError:
        return None


def filename_datetime(path: Path) -> datetime | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}[_T]\d{2}:\d{2}:\d{2}", unquote(path.name))
    return parse_datetime(match[0]) if match else None


def read_time_axis(raw, time_dimension, count: int, path: Path):
    if "Times" in raw:
        values = np.atleast_1d(raw["Times"].to_numpy())
        rows = []
        for row in values:
            if np.ndim(row):
                row = b"".join(row) if row.dtype.kind == "S" else "".join(row)
            rows.append(parse_datetime(row))
        if len(rows) == count and all(date is not None for date in rows):
            return rows
    names = [time_dimension, "Time", "time", "XTIME"]
    names += [
        name
        for name, coord in raw.coords.items()
        if coord.attrs.get("axis") == "T" or coord.attrs.get("standard_name") == "time"
    ]
    for name in dict.fromkeys(names):
        if name not in raw or raw[name].ndim != 1 or raw[name].size != count:
            continue
        coord = raw[name]
        values = coord.to_numpy()
        dates = [parse_datetime(value) for value in values]
        if all(date is not None for date in dates):
            return dates
        units = str(coord.attrs.get("units", ""))
        if " since " in units and np.issubdtype(values.dtype, np.number):
            from xarray.coding.times import decode_cf_datetime

            try:
                decoded = decode_cf_datetime(values, units, coord.attrs.get("calendar", "standard"))
                dates = [parse_datetime(value) for value in decoded]
                if all(date is not None for date in dates):
                    return dates
            except (ValueError, TypeError, OverflowError):
                pass
        if name == "XTIME" and np.issubdtype(values.dtype, np.number):
            start = parse_datetime(
                raw.attrs.get("START_DATE", raw.attrs.get("SIMULATION_START_DATE"))
            )
            if start and units.lower() in {"", "min", "minutes", "minute"}:
                return [start + timedelta(minutes=float(value)) for value in values]
    # One filename cannot define dates for multiple internal timesteps.
    date = filename_datetime(path) if count == 1 else None
    return [date] if date else [None] * count


def format_timestamp(date: datetime) -> str:
    return (
        date.strftime("%Y-%m-%d %H:%M:%S")
        + (f".{date.microsecond:06d}" if date.microsecond else "")
        + " UTC"
    )

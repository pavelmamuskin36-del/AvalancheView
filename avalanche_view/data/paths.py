"""Windows Unicode path adaptation for NetCDF-C's narrow filename API."""

import os
from pathlib import Path


def native_netcdf_path(path: str | Path) -> Path:
    """Use the existing file's ASCII short name when the filesystem provides it.

    No copy or eager loading is needed. HDF5/h5netcdf use the original Unicode
    path; only the NetCDF-C fallback needs this compatibility step.
    """
    path = Path(path)
    if os.name != "nt" or str(path).isascii():
        return path
    import ctypes
    from ctypes import wintypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    function.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    function.restype = wintypes.DWORD
    absolute = str(path.resolve())
    length = function(absolute, None, 0)
    if not length:
        return path
    buffer = ctypes.create_unicode_buffer(length)
    if function(absolute, buffer, length):
        return Path(buffer.value)
    return path

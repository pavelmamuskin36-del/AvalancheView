# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 bundle; Qt hooks collect WebEngineProcess, plugins and Qt resources."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH)
onefile = os.environ.get("AVALANCHEVIEW_BUILD_MODE", "onefile") == "onefile"
datas = collect_data_files("avalanche_view") + [(str(root / "LICENSE"), ".")]
for distribution in ("xarray", "netCDF4", "h5netcdf", "rasterio", "rioxarray", "geopandas", "pyogrio"):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=datas,
    binaries=[],
    hiddenimports=[
        "xarray.backends.netCDF4_", "xarray.backends.h5netcdf_", "xarray.backends.scipy_",
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebChannel",
        "matplotlib.backends.backend_qtagg", "rasterio.sample", "pyogrio",
    ],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["QtAgg", "Agg"]}},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide2", "PySide6", "tkinter", "IPython", "notebook", "pytest", "_pytest", "ruff"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
options = dict(
    name="AvalancheView", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(root / "build/AvalancheView.ico"),
)
if onefile:
    executable = EXE(archive, analysis.scripts, analysis.binaries, analysis.datas, [], **options)
else:
    executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, **options)
    distribution = COLLECT(executable, analysis.binaries, analysis.datas,
                           strip=False, upx=False, name="AvalancheView")

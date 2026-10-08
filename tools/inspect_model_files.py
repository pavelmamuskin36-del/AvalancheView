"""Save per-file metadata without reading weather fields or changing inputs."""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
INTERPRETER = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if INTERPRETER.exists() and Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
    raise SystemExit(
        subprocess.call([str(INTERPRETER), str(Path(__file__).resolve()), *sys.argv[1:]])
    )
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from avalanche_view.data.dataset_series import DatasetCompatibilityChecker, FileEntry  # noqa: E402
from avalanche_view.data.wrf_dataset import WRFDataset  # noqa: E402
from avalanche_view.services.file_service import model_files  # noqa: E402


def serializable(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, nargs="?", default=ROOT / "demo_data")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "demo_data_metadata.json")
    args = parser.parse_args()
    records = []
    first = None
    checker = DatasetCompatibilityChecker()
    for path in model_files(args.directory):
        entry = FileEntry.inspect(path)
        with WRFDataset(path, cache_limit=0) as dataset:
            grid = dataset.coordinates()
            record = {
                "filename": path.name,
                "dimensions": entry.dimensions,
                "coordinates": list(dataset.raw.coords),
                "time_dimension": entry.time_dimension,
                "time_variables": {
                    name: {
                        "dimensions": dataset.raw[name].dims,
                        "values": dataset.raw[name].to_numpy(),
                        "attributes": dict(dataset.raw[name].attrs),
                    }
                    for name in ("Time", "Times", "XTIME", "time")
                    if name in dataset.raw
                },
                "latitude": entry.latitude_name,
                "longitude": entry.longitude_name,
                "coordinate_bounds": {
                    "lat": [float(np.nanmin(grid.y)), float(np.nanmax(grid.y))],
                    "lon": [float(np.nanmin(grid.x)), float(np.nanmax(grid.x))],
                },
                "coordinate_signature": entry.coordinate_signature,
                "domain": entry.domain,
                "type": entry.model_type,
                "projection": str(entry.projection),
                "metadata": entry.metadata,
                "timestamps": dataset.timestamps,
                "vertical_dimensions": {
                    dim: size
                    for dim, size in entry.dimensions.items()
                    if dim
                    not in {
                        entry.time_dimension,
                        entry.x_dimension,
                        entry.y_dimension,
                        entry.x_dimension + "_stag",
                        entry.y_dimension + "_stag",
                    }
                },
                "variables": {name: asdict(info) for name, info in entry.variables.items()},
                "compatibility_with_first": asdict(checker.check(first or entry, entry)),
            }
        first = first or entry
        records.append(record)
        print(
            f"{path.name}: {entry.domain}, {dataset.timestamps[0]}, {len(entry.variables)} variables",
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=serializable), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()

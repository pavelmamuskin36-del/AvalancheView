"""Run with `py tools/create_demo_dataset.py` from the project directory."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
INTERPRETER = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if INTERPRETER.exists() and Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
    raise SystemExit(
        subprocess.call([str(INTERPRETER), str(Path(__file__).resolve()), *sys.argv[1:]])
    )
sys.path.insert(0, str(ROOT))

from avalanche_view.data.demo import create_demo_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic WRF data")
    parser.add_argument("--output", type=Path, default=ROOT / "demo_data" / "demo_wrf.nc")
    parser.add_argument("--timesteps", type=int, default=12)
    args = parser.parse_args()
    print(create_demo_dataset(args.output, timesteps=args.timesteps))


if __name__ == "__main__":
    main()
